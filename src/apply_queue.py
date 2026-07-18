"""Assist-mode application queue.

For each queued row in the tracker (up to ``daily_cap``):
1. Open the job's artifact folder in the OS file manager (Finder/Explorer/Nautilus).
2. Open the apply URL in the default web browser.
3. Print a readable checklist (resume path, cover letter path, screening answers).
4. Prompt the user: ``[s]ubmitted / [k]eep queued / [d]rop / [q]uit``.
5. Update the tracker accordingly.

This module never auto-submits anything. The user still clicks Submit on the
portal — we just stage the artifacts and route to the right tab.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from . import screening_qs


def _open_in_file_manager(path: Path) -> None:
    """Reveal a directory in the OS file manager. Best-effort, never raises."""
    path = Path(path)
    if not path.exists():
        return
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        print(f"[apply_queue] could not reveal {path}: {e}")


def _print_checklist(row: dict[str, Any]) -> None:
    artifact_dir = row.get("artifact_dir") or ""
    print()
    print("=" * 78)
    print(f"  {row.get('company','?')} — {row.get('title','?')}")
    print(f"  Location: {row.get('location','?')}  |  Posted: {row.get('posted_days_ago','?')} days ago")
    print(
        f"  Salary mid: {row.get('salary_mid_lpa','?')} LPA  "
        f"|  Fit: {row.get('fit_score','?')}  |  Score: {row.get('composite_score','?')}"
    )
    print(f"  Source: {row.get('source','?')}")
    print(f"  Apply URL: {row.get('apply_link','(missing)')}")
    print(f"  Artifacts: {artifact_dir or '(none)'}")
    print("-" * 78)

    if artifact_dir:
        d = Path(artifact_dir)
        for label, name in (
            ("Resume (DOCX)", "resume.docx"),
            ("Cover letter (DOCX)", "cover_letter.docx"),
            ("Screening answers", "screening_answers.json"),
        ):
            p = d / name
            mark = "✓" if p.exists() else "✗"
            print(f"  [{mark}] {label}: {p}")
        # Echo the screening answers inline so the user can copy/paste quickly.
        sa_path = d / "screening_answers.json"
        if sa_path.exists():
            try:
                answers = json.loads(sa_path.read_text(encoding="utf-8"))
                print()
                print(screening_qs.render_answers_markdown(answers))
            except Exception:
                pass
    print("=" * 78)


def _prompt_action() -> str:
    while True:
        raw = input("  Action [s]ubmitted / [k]eep queued / [d]rop / [q]uit: ").strip().lower()
        if raw in {"s", "submitted"}:
            return "s"
        if raw in {"k", "keep"}:
            return "k"
        if raw in {"d", "drop", "skip"}:
            return "d"
        if raw in {"q", "quit"}:
            return "q"
        print("  -> please type s, k, d, or q")


def run_queue(
    tracker: Any,
    *,
    daily_cap: int = 12,
    open_browser: bool = True,
    open_files: bool = True,
    auto_advance: bool = True,
    only_with_artifacts: bool = True,
) -> dict[str, int]:
    """Walk queued rows. Returns counts of {submitted, kept, dropped}."""
    counts = {"submitted": 0, "kept": 0, "dropped": 0, "skipped_no_artifacts": 0}
    rows = tracker.queued_rows()
    if only_with_artifacts:
        eligible = [r for r in rows if r.get("artifact_dir")]
    else:
        eligible = rows

    if not eligible:
        print("[apply_queue] no queued rows with artifacts ready. Generate them first.")
        return counts

    print(f"[apply_queue] {len(eligible)} queued; applying up to {daily_cap} this session.")
    processed = 0
    for row in eligible:
        if processed >= daily_cap:
            print(f"[apply_queue] hit daily cap ({daily_cap}); stopping.")
            break
        _print_checklist(row)

        apply_url = row.get("apply_link") or ""
        artifact_dir = row.get("artifact_dir") or ""

        if open_files and artifact_dir:
            _open_in_file_manager(Path(artifact_dir))
        if open_browser and apply_url:
            try:
                webbrowser.open(apply_url, new=2)
            except Exception as e:
                print(f"[apply_queue] couldn't open URL: {e}")

        if not auto_advance:
            counts["kept"] += 1
            processed += 1
            continue

        action = _prompt_action()
        if action == "s":
            tracker.set_status(row["job_id"], "applied")
            counts["submitted"] += 1
        elif action == "d":
            tracker.set_status(row["job_id"], "skipped", notes="Dropped from queue")
            counts["dropped"] += 1
        elif action == "k":
            counts["kept"] += 1
        elif action == "q":
            print("[apply_queue] quitting at user request.")
            break
        processed += 1

    print(
        f"[apply_queue] done. submitted={counts['submitted']} "
        f"kept={counts['kept']} dropped={counts['dropped']}"
    )
    return counts


def dry_run(tracker: Any, *, limit: int = 5) -> None:
    """Print what the queue would do without opening anything or touching the tracker."""
    rows = tracker.queued_rows(limit=limit)
    if not rows:
        print("[apply_queue] dry-run: nothing queued.")
        return
    print(f"[apply_queue] dry-run: {len(rows)} job(s) would be processed:")
    for r in rows:
        _print_checklist(r)


if __name__ == "__main__":  # pragma: no cover - manual entry point
    from . import config as cfg
    from . import tracker as tracker_mod

    prefs = cfg.load_preferences()
    cap = (prefs.get("apply_queue") or {}).get("daily_apply_cap", 12)
    t = tracker_mod.open_tracker(prefs)
    if "--dry-run" in sys.argv:
        dry_run(t)
    else:
        run_queue(t, daily_cap=cap)
