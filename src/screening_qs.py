"""Pre-fill answers to common Indian-pharma screening questions per job.

The output JSON is saved alongside the tailored resume + cover letter in the
job's artifact directory so the user can copy-paste each answer into the portal
form. Heavy guardrails in :file:`prompts/screening_answers.md` ensure we never
fabricate CTC, years, or audit experience.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import llm


def _candidate_facts(resume: dict[str, Any]) -> dict[str, Any]:
    contact = resume.get("contact", {}) or {}
    return {
        "name": contact.get("name") or "",
        "location": contact.get("location") or "",
        "summary": (resume.get("summary") or "")[:1500],
        "skills": (resume.get("skills") or [])[:80],
        "experience": [
            {
                "title": e.get("title", ""),
                "company": e.get("company", ""),
                "location": e.get("location", ""),
                "start_date": e.get("start_date", ""),
                "end_date": e.get("end_date", ""),
                "bullets": (e.get("bullets") or [])[:10],
            }
            for e in (resume.get("experience") or [])
        ],
        "education": resume.get("education") or [],
        "certifications": resume.get("certifications") or [],
    }


def _candidate_preferences(prefs: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    """Pull the explicit user preferences from preferences.yaml + parsed resume contact."""
    cand = (prefs or {}).get("candidate", {}) or {}
    contact = resume.get("contact", {}) or {}
    name_parts = (contact.get("name") or "").split()
    first_name = cand.get("first_name") or (name_parts[0] if name_parts else "")
    return {
        "first_name": first_name,
        "current_ctc_lpa": cand.get("current_ctc_lpa"),
        "expected_ctc_lpa": cand.get("expected_ctc_lpa"),
        "notice_period_days": cand.get("notice_period_days"),
        "willing_to_relocate": cand.get("willing_to_relocate"),
        "earliest_join_date": cand.get("earliest_join_date") or "",
    }


def generate_screening_answers(
    resume: dict[str, Any],
    job: dict[str, Any],
    *,
    prefs: dict[str, Any],
) -> dict[str, Any] | None:
    """Call Gemini with strict JSON output. Returns None if model is unconfigured."""
    if not llm.is_available():
        print("[screening_qs] Gemini not configured; returning blank screening answers.")
        return _blank_answers()

    facts = _candidate_facts(resume)
    user_prefs = _candidate_preferences(prefs, resume)

    try:
        prompt = llm.load_prompt(
            "screening_answers",
            job_title=job.get("job_title") or job.get("title") or "",
            company=job.get("employer_name") or job.get("company") or "",
            location=job.get("job_city") or job.get("city") or "",
            job_description=(job.get("job_description") or job.get("description") or "")[:6000],
            candidate_facts=json.dumps(facts, ensure_ascii=False)[:8000],
            candidate_preferences=json.dumps(user_prefs, ensure_ascii=False),
        )
        out = llm.complete_json(prompt, temperature=0.2)
    except Exception as e:
        print(f"[screening_qs] generation failed: {e}")
        return _blank_answers()
    llm.throttle(0.5)
    if not isinstance(out, dict):
        return _blank_answers()
    return _merge_with_prefs(out, user_prefs)


def _merge_with_prefs(answers: dict[str, Any], prefs: dict[str, Any]) -> dict[str, Any]:
    """User-explicit values from preferences.yaml always win over the LLM's guess."""
    if prefs.get("current_ctc_lpa") is not None:
        answers["current_ctc_lpa"] = prefs["current_ctc_lpa"]
    if prefs.get("expected_ctc_lpa") is not None:
        answers["expected_ctc_lpa"] = prefs["expected_ctc_lpa"]
    if prefs.get("notice_period_days") is not None:
        answers["notice_period_days"] = prefs["notice_period_days"]
    if prefs.get("willing_to_relocate") is not None:
        answers["willing_to_relocate_to_job_location"] = bool(prefs["willing_to_relocate"])
    if prefs.get("earliest_join_date"):
        answers["earliest_join_date"] = prefs["earliest_join_date"]
    return answers


def _blank_answers() -> dict[str, Any]:
    return {
        "years_of_total_experience": "",
        "years_of_qc_micro_experience": "",
        "current_ctc_lpa": "",
        "expected_ctc_lpa": "",
        "notice_period_days": "",
        "current_location": "",
        "willing_to_relocate_to_job_location": "",
        "earliest_join_date": "",
        "highest_qualification": "",
        "regulatory_audits_faced": [],
        "core_techniques": [],
        "instruments_handled": [],
        "people_managed": "",
        "why_this_role": "",
        "open_to_shift_work": "",
        "screening_red_flags": [],
    }


def write_answers_json(answers: dict[str, Any], output_path: str | Path) -> Path:
    """Persist answers to a pretty-printed JSON file for copy/paste use."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def render_answers_markdown(answers: dict[str, Any]) -> str:
    """Render a human-friendly view of the screening answers (for the apply queue UI)."""
    lines: list[str] = ["# Screening answers"]
    label_map = {
        "years_of_total_experience": "Total years of experience",
        "years_of_qc_micro_experience": "Years in QC Microbiology",
        "current_ctc_lpa": "Current CTC (LPA)",
        "expected_ctc_lpa": "Expected CTC (LPA)",
        "notice_period_days": "Notice period (days)",
        "current_location": "Current location",
        "willing_to_relocate_to_job_location": "Willing to relocate?",
        "earliest_join_date": "Earliest join date",
        "highest_qualification": "Highest qualification",
        "regulatory_audits_faced": "Regulatory audits faced",
        "core_techniques": "Core techniques",
        "instruments_handled": "Instruments handled",
        "people_managed": "People managed",
        "why_this_role": "Why this role",
        "open_to_shift_work": "Open to shift work?",
        "screening_red_flags": "Likely recruiter probes",
    }
    for key, label in label_map.items():
        value = answers.get(key, "")
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value) if value else "(none)"
        lines.append(f"- **{label}**: {value if value != '' else '(blank)'}")
    return "\n".join(lines)
