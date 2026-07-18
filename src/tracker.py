"""Google Sheets-backed application tracker.

One row per (job_id) — the Sheet is the source of truth for the pipeline so the
user can also edit it on mobile. Functions are defensive: if gspread isn't
installed or no credentials are available, callers get a clear warning and a
no-op stand-in so the rest of the pipeline still runs.

Auth model: a Google service-account JSON key with Sheets + Drive scope. The
target Sheet must be shared with the service-account email as an Editor.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import config as cfg

load_dotenv()

DEFAULT_COLUMNS = [
    "job_id",
    "source",
    "company",
    "title",
    "location",
    "posted_days_ago",
    "salary_mid_lpa",
    "fit_score",
    "composite_score",
    "apply_link",
    "status",
    "queued_at",
    "applied_at",
    "last_response_at",
    "last_response_summary",
    "artifact_dir",
    "notes",
]

VALID_STATUSES = {
    "queued",
    "applied",
    "viewed",
    "screening",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
    "skipped",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _gspread_available() -> bool:
    try:
        import gspread  # noqa: F401
        from google.oauth2.service_account import Credentials  # noqa: F401
        return True
    except Exception:
        return False


class TrackerError(RuntimeError):
    pass


class Tracker:
    """Thin wrapper around a single gspread worksheet."""

    def __init__(
        self,
        spreadsheet_id: str | None = None,
        worksheet_name: str = "applications",
        service_account_json: str | Path | None = None,
        columns: list[str] | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SHEET_ID", "").strip()
        self.worksheet_name = worksheet_name
        self.service_account_json = str(service_account_json or os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_JSON", "./secrets/service_account.json"
        ))
        self.columns = columns or DEFAULT_COLUMNS
        self._ws = None
        self._connect()

    def _connect(self) -> None:
        if not _gspread_available():
            raise TrackerError(
                "gspread/google-auth not installed. Run `pip install gspread google-auth`."
            )
        if not self.spreadsheet_id:
            raise TrackerError("GOOGLE_SHEET_ID not configured.")

        import gspread
        from google.oauth2.service_account import Credentials

        sa_path = cfg.resolve_repo_path(self.service_account_json)
        if not sa_path.exists():
            raise TrackerError(
                f"Service-account JSON not found at {sa_path}. "
                "Create one in Google Cloud Console (Service Accounts) and share the Sheet with it."
            )
        creds = Credentials.from_service_account_file(
            str(sa_path),
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        client = gspread.authorize(creds)
        sh = client.open_by_key(self.spreadsheet_id)
        try:
            ws = sh.worksheet(self.worksheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=self.worksheet_name, rows=1000, cols=max(20, len(self.columns)))
        self._ensure_header(ws)
        self._ws = ws

    def _ensure_header(self, ws: Any) -> None:
        existing = ws.row_values(1)
        if existing == self.columns:
            return
        if not existing:
            ws.update("A1", [self.columns])
            return
        # Mismatch — only extend with missing columns, never reorder destructively.
        missing = [c for c in self.columns if c not in existing]
        if missing:
            new_header = existing + missing
            ws.update("A1", [new_header])
            self.columns = new_header

    def _col_index(self, name: str) -> int:
        try:
            return self.columns.index(name) + 1  # gspread is 1-indexed
        except ValueError as e:
            raise TrackerError(f"Unknown column {name!r}") from e

    def list_rows(self) -> list[dict[str, Any]]:
        if self._ws is None:
            return []
        return self._ws.get_all_records()

    def find_row_by_job_id(self, job_id: str) -> int | None:
        """1-indexed row number, or None."""
        if self._ws is None:
            return None
        col_idx = self._col_index("job_id")
        values = self._ws.col_values(col_idx)
        for i, v in enumerate(values, start=1):
            if i == 1:  # header
                continue
            if v == job_id:
                return i
        return None

    def upsert_job(self, job_row: dict[str, Any]) -> int:
        """Insert if absent (status=queued), or update mutable fields if present.
        Returns the 1-indexed row number of the affected row.
        """
        if self._ws is None:
            raise TrackerError("Tracker not connected")

        job_id = job_row.get("job_id") or ""
        if not job_id:
            raise TrackerError("job_row missing 'job_id'")

        existing_row = self.find_row_by_job_id(job_id)
        payload = {col: job_row.get(col, "") for col in self.columns}
        if existing_row is None:
            payload.setdefault("status", "queued")
            payload["queued_at"] = payload.get("queued_at") or _now_iso()
            self._ws.append_row(
                [self._to_cell(payload.get(col, "")) for col in self.columns],
                value_input_option="USER_ENTERED",
            )
            new_row = self.find_row_by_job_id(job_id)
            return new_row or 0
        # Refresh only the non-status-overriding columns
        protected = {"status", "queued_at", "applied_at", "last_response_at", "last_response_summary", "notes"}
        for col, value in payload.items():
            if col in protected:
                continue
            if value in ("", None, []):
                continue
            self._ws.update_cell(existing_row, self._col_index(col), self._to_cell(value))
        return existing_row

    def set_status(
        self,
        job_id: str,
        status: str,
        *,
        notes: str | None = None,
        response_summary: str | None = None,
    ) -> bool:
        if status not in VALID_STATUSES:
            raise TrackerError(f"Invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}")
        if self._ws is None:
            return False
        row = self.find_row_by_job_id(job_id)
        if row is None:
            return False
        self._ws.update_cell(row, self._col_index("status"), status)
        if status == "applied":
            self._ws.update_cell(row, self._col_index("applied_at"), _now_iso())
        if response_summary is not None:
            self._ws.update_cell(row, self._col_index("last_response_at"), _now_iso())
            self._ws.update_cell(
                row, self._col_index("last_response_summary"), response_summary[:400]
            )
        if notes:
            self._ws.update_cell(row, self._col_index("notes"), notes[:400])
        return True

    def queued_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self.list_rows() if (r.get("status") or "queued") == "queued"]
        if limit is not None:
            return rows[:limit]
        return rows

    def applied_rows(self) -> list[dict[str, Any]]:
        return [r for r in self.list_rows() if (r.get("status") or "") == "applied"]

    @staticmethod
    def _to_cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        return value


# ---------- adapter helpers ----------

def job_dict_to_row(
    job: dict[str, Any],
    *,
    artifact_dir: str | Path | None = None,
    fit_score: float | None = None,
    composite_score: float | None = None,
    salary_mid_lpa: float | None = None,
    posted_days_ago: float | None = None,
) -> dict[str, Any]:
    """Project a ranker/fetcher row down to the Sheet schema."""
    return {
        "job_id": job.get("job_id") or "",
        "source": job.get("_source") or "jsearch",
        "company": job.get("employer_name") or job.get("company") or "",
        "title": job.get("job_title") or job.get("title") or "",
        "location": (
            job.get("job_city") or job.get("city") or job.get("_source_location") or ""
        ),
        "posted_days_ago": _round(posted_days_ago, 1),
        "salary_mid_lpa": _round(salary_mid_lpa, 2),
        "fit_score": _round(fit_score, 4),
        "composite_score": _round(composite_score, 4),
        "apply_link": job.get("job_apply_link") or job.get("apply_link") or "",
        "status": "queued",
        "queued_at": _now_iso(),
        "applied_at": "",
        "last_response_at": "",
        "last_response_summary": "",
        "artifact_dir": str(artifact_dir) if artifact_dir else "",
        "notes": "",
    }


def _round(v: Any, n: int) -> Any:
    if v is None or v == "":
        return ""
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return v


# ---------- in-memory fallback for offline / no-credential mode ----------

class InMemoryTracker:
    """Drop-in stand-in for ``Tracker`` when no Google credentials exist.

    Useful for dev / unit tests. Persists to ``data/output/applications.json``
    so state survives across runs.
    """

    def __init__(self, persist_path: str | Path = "data/output/applications.json") -> None:
        self.persist_path = cfg.resolve_repo_path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._rows: list[dict[str, Any]] = []
        if self.persist_path.exists():
            try:
                self._rows = json.loads(self.persist_path.read_text(encoding="utf-8"))
            except Exception:
                self._rows = []

    def _save(self) -> None:
        self.persist_path.write_text(
            json.dumps(self._rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_rows(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def upsert_job(self, job_row: dict[str, Any]) -> int:
        jid = job_row.get("job_id") or ""
        for i, r in enumerate(self._rows):
            if r.get("job_id") == jid:
                self._rows[i] = {**r, **{k: v for k, v in job_row.items() if v not in (None, "")}}
                self._save()
                return i + 1
        row = {**job_row}
        row.setdefault("status", "queued")
        row.setdefault("queued_at", _now_iso())
        self._rows.append(row)
        self._save()
        return len(self._rows)

    def set_status(
        self,
        job_id: str,
        status: str,
        *,
        notes: str | None = None,
        response_summary: str | None = None,
    ) -> bool:
        if status not in VALID_STATUSES:
            raise TrackerError(f"Invalid status {status!r}")
        for r in self._rows:
            if r.get("job_id") == job_id:
                r["status"] = status
                if status == "applied":
                    r["applied_at"] = _now_iso()
                if response_summary is not None:
                    r["last_response_at"] = _now_iso()
                    r["last_response_summary"] = response_summary[:400]
                if notes:
                    r["notes"] = notes[:400]
                self._save()
                return True
        return False

    def queued_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self._rows if (r.get("status") or "queued") == "queued"]
        return rows[:limit] if limit is not None else rows

    def applied_rows(self) -> list[dict[str, Any]]:
        return [r for r in self._rows if (r.get("status") or "") == "applied"]

    def find_row_by_job_id(self, job_id: str) -> int | None:
        for i, r in enumerate(self._rows, start=1):
            if r.get("job_id") == job_id:
                return i
        return None


def open_tracker(prefs: dict[str, Any] | None = None, *, prefer_sheet: bool = True):
    """Convenience factory: try Sheets; fall back to local JSON with a warning."""
    sheet_cfg = (prefs or {}).get("sheet", {}) or {}
    worksheet_name = sheet_cfg.get("worksheet_name") or "applications"
    columns = sheet_cfg.get("columns") or DEFAULT_COLUMNS
    if prefer_sheet:
        try:
            return Tracker(worksheet_name=worksheet_name, columns=columns)
        except TrackerError as e:
            print(f"[tracker] Google Sheets unavailable ({e}); falling back to local JSON.")
    return InMemoryTracker()
