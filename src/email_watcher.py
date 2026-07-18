"""Gmail-based HR response watcher.

Polls the user's Gmail inbox (read-only OAuth scope), classifies new threads
that match any applied employer using Gemini via :file:`prompts/classify_email.md`,
and advances the tracker's status accordingly.

Storage:
- OAuth client secrets path: ``GMAIL_OAUTH_CLIENT_JSON`` env var.
- Token cache path: ``GMAIL_TOKEN_JSON`` env var (refreshed automatically).
- Last-seen historyId per address persisted to ``data/output/.gmail_history.json``
  for incremental polling.

This module is robust to partial failures: if Gmail/Gemini hiccups, the watcher
logs and continues; we never crash the notebook.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from . import config as cfg
from . import llm

load_dotenv()

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _gmail_libs_available() -> bool:
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
        return True
    except Exception:
        return False


def _load_credentials() -> Any:
    """Load Gmail OAuth creds; trigger consent if no cached token exists."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = cfg.resolve_repo_path(
        os.getenv("GMAIL_TOKEN_JSON", "./secrets/gmail_token.json")
    )
    client_path = cfg.resolve_repo_path(
        os.getenv("GMAIL_OAUTH_CLIENT_JSON", "./secrets/gmail_client.json")
    )

    creds: Any = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_path.exists():
                raise RuntimeError(
                    f"Gmail OAuth client JSON not found at {client_path}. "
                    "Download it from Google Cloud Console -> OAuth client (Desktop)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_path), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _build_service() -> Any:
    from googleapiclient.discovery import build
    creds = _load_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in headers}


def _decode_body(payload: dict[str, Any]) -> str:
    """Walk the MIME tree and pull text/plain (preferred) or text/html."""
    parts_to_walk = [payload]
    text_chunks: list[str] = []
    html_chunks: list[str] = []
    while parts_to_walk:
        p = parts_to_walk.pop(0)
        if "parts" in p and isinstance(p["parts"], list):
            parts_to_walk.extend(p["parts"])
            continue
        mime = p.get("mimeType", "")
        body = p.get("body") or {}
        data = body.get("data")
        if not data:
            continue
        try:
            raw = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="ignore")
        except Exception:
            continue
        if mime == "text/plain":
            text_chunks.append(raw)
        elif mime == "text/html":
            html_chunks.append(raw)
    if text_chunks:
        return "\n".join(text_chunks)
    # crude HTML strip as a last resort
    html = "\n".join(html_chunks)
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _build_query(known_companies: Iterable[str], lookback_days: int) -> str:
    """Restrict the Gmail search to likely-relevant threads."""
    company_clause = ""
    cleaned = [c for c in (k.strip() for k in known_companies) if c]
    if cleaned:
        terms = " OR ".join(f'"{c}"' for c in cleaned[:30])
        company_clause = f"({terms})"
    parts = ["category:primary", f"newer_than:{max(1, lookback_days)}d"]
    if company_clause:
        parts.append(company_clause)
    return " ".join(parts)


def _load_history_file(history_path: Path) -> dict[str, str]:
    if not history_path.exists():
        return {}
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_history_file(history_path: Path, data: dict[str, str]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _classify_message(
    body: str,
    *,
    from_address: str,
    subject: str,
    received_at: str,
    known_companies: list[str],
) -> dict[str, Any] | None:
    if not llm.is_available():
        return None
    try:
        prompt = llm.load_prompt(
            "classify_email",
            from_address=from_address[:200],
            subject=subject[:200],
            received_at=received_at,
            body=body[:4000],
            known_companies=json.dumps(known_companies[:40]),
        )
        out = llm.complete_json(prompt, temperature=0.0)
    except Exception as e:
        print(f"[email_watcher] classification failed: {e}")
        return None
    if not isinstance(out, dict):
        return None
    label = (out.get("label") or "").strip().lower()
    if label not in {"viewed", "screening", "interviewing", "offer", "rejected", "irrelevant"}:
        return None
    return out


_LABEL_TO_STATUS = {
    "viewed": "viewed",
    "screening": "screening",
    "interviewing": "interviewing",
    "offer": "offer",
    "rejected": "rejected",
}

# Status precedence — never regress (e.g. don't go offer -> screening).
_STATUS_ORDER = {
    "queued": 0,
    "applied": 1,
    "viewed": 2,
    "screening": 3,
    "interviewing": 4,
    "offer": 5,
    "rejected": 5,
    "skipped": -1,
    "withdrawn": -1,
}


def _should_advance(current: str, candidate: str) -> bool:
    return _STATUS_ORDER.get(candidate, -2) > _STATUS_ORDER.get(current or "queued", -2)


def _find_applied_company_match(
    matched_company: str,
    known_companies: list[str],
) -> str | None:
    mc = (matched_company or "").strip().lower()
    if not mc:
        return None
    for c in known_companies:
        if mc in c.lower() or c.lower() in mc:
            return c
    return None


def poll_once(
    tracker: Any,
    *,
    lookback_days: int = 7,
    history_path: str | Path = "data/output/.gmail_history.json",
    quiet: bool = False,
) -> dict[str, int]:
    """Single poll cycle. Returns counts {checked, classified, advanced}."""
    counts = {"checked": 0, "classified": 0, "advanced": 0}
    if not _gmail_libs_available():
        if not quiet:
            print("[email_watcher] google-api-python-client not installed; skipping.")
        return counts

    applied = [r for r in tracker.list_rows() if (r.get("status") or "") not in {"", "queued", "skipped"}]
    if not applied:
        if not quiet:
            print("[email_watcher] no applied rows yet; nothing to watch.")
        return counts

    company_to_job: dict[str, dict[str, Any]] = {}
    for r in applied:
        c = (r.get("company") or "").strip().lower()
        if c:
            company_to_job[c] = r
    known_companies = list(company_to_job.keys())

    history_path = cfg.resolve_repo_path(history_path)
    history = _load_history_file(history_path)
    seen_ids = set(history.get("seen_message_ids") or [])

    try:
        service = _build_service()
    except Exception as e:
        print(f"[email_watcher] Gmail auth failed: {e}")
        return counts

    query = _build_query(known_companies, lookback_days=lookback_days)
    try:
        resp = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    except Exception as e:
        print(f"[email_watcher] Gmail list failed: {e}")
        return counts
    messages = resp.get("messages") or []

    for m in messages:
        msg_id = m.get("id") or ""
        if not msg_id or msg_id in seen_ids:
            continue
        counts["checked"] += 1
        try:
            full = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        except Exception as e:
            print(f"[email_watcher] fetch failed for {msg_id}: {e}")
            continue
        payload = full.get("payload") or {}
        headers = _headers_to_dict(payload.get("headers") or [])
        body = _decode_body(payload)
        received_at = datetime.fromtimestamp(
            int(full.get("internalDate", "0")) / 1000.0, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        verdict = _classify_message(
            body,
            from_address=headers.get("from", ""),
            subject=headers.get("subject", ""),
            received_at=received_at,
            known_companies=known_companies,
        )
        seen_ids.add(msg_id)
        if not verdict:
            continue
        counts["classified"] += 1

        label = (verdict.get("label") or "").lower()
        if label == "irrelevant":
            continue
        target_status = _LABEL_TO_STATUS.get(label)
        if not target_status:
            continue

        matched_company = _find_applied_company_match(
            verdict.get("matched_company") or "", known_companies
        )
        if not matched_company:
            continue
        row = company_to_job.get(matched_company)
        if not row:
            continue
        current_status = (row.get("status") or "applied").strip().lower()
        if not _should_advance(current_status, target_status):
            continue
        evidence = (verdict.get("evidence_snippet") or "")[:280]
        if tracker.set_status(
            row["job_id"],
            target_status,
            response_summary=f"{label}: {evidence}",
        ):
            counts["advanced"] += 1
            if not quiet:
                print(
                    f"[email_watcher] {row.get('company')} -> {target_status} "
                    f"(conf={verdict.get('confidence')})"
                )

    history["seen_message_ids"] = list(seen_ids)[-2000:]
    history["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    _save_history_file(history_path, history)
    if not quiet:
        print(
            f"[email_watcher] poll done: checked={counts['checked']} "
            f"classified={counts['classified']} advanced={counts['advanced']}"
        )
    return counts


def watch_forever(
    tracker: Any,
    *,
    poll_interval_minutes: int = 15,
    lookback_days: int = 7,
    max_polls: int | None = None,
    history_path: str | Path = "data/output/.gmail_history.json",
) -> None:
    """Blocking poll loop. Stops cleanly on Ctrl-C."""
    interval = max(1, poll_interval_minutes) * 60
    polls = 0
    try:
        while True:
            poll_once(tracker, lookback_days=lookback_days, history_path=history_path)
            polls += 1
            if max_polls is not None and polls >= max_polls:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[email_watcher] stopped by user.")


if __name__ == "__main__":  # pragma: no cover
    from . import tracker as tracker_mod

    prefs = cfg.load_preferences()
    interval = (prefs.get("email_watcher") or {}).get("poll_interval_minutes", 15)
    history = (prefs.get("email_watcher") or {}).get(
        "history_file", "data/output/.gmail_history.json"
    )
    t = tracker_mod.open_tracker(prefs)
    watch_forever(t, poll_interval_minutes=interval, history_path=history)
