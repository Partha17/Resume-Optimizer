"""Score, rank, and surface the best-fit & best-paid jobs from a JSearch result list.

Composite score formula (weights configurable):
    score = 0.45 * fit + 0.35 * salary_z + 0.20 * recency

- fit:      cosine similarity between resume text embedding and JD text embedding
            (sentence-transformers/all-MiniLM-L6-v2, runs locally, ~80MB)
- salary_z: z-normalised LPA across the candidate pool; jobs without salary info
            get the median (so we neither reward nor penalise omission)
- recency:  exp(-days_old / 30); jobs older than ~3 months decay toward 0

Salary parsing strategy:
1. Use JSearch's structured fields if present (job_min_salary, job_max_salary,
   job_salary_currency, job_salary_period).
2. Fall back to a regex sweep over the description for "X LPA", "X-Y lakhs", etc.
3. (Optional) Gemini fallback via prompts/extract_salary.md if neither matches —
   batched to keep us under the free-tier RPM cap.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
import pandas as pd

from . import llm

# ---------- embeddings ----------

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_embed_model = None


def _get_embedder():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
    return _embed_model


def _embed(texts: Sequence[str]) -> np.ndarray:
    model = _get_embedder()
    return np.asarray(model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # already L2-normalised


# ---------- salary parsing ----------

@dataclass
class SalaryInfo:
    min_lpa: float | None
    max_lpa: float | None
    currency: str
    source: str  # "structured", "regex", "llm", "missing"

    @property
    def mid_lpa(self) -> float | None:
        if self.min_lpa is None and self.max_lpa is None:
            return None
        if self.min_lpa is None:
            return self.max_lpa
        if self.max_lpa is None:
            return self.min_lpa
        return (self.min_lpa + self.max_lpa) / 2


# rough fx into INR-LPA. Refresh manually if you care about precision.
_FX_TO_INR = {
    "INR": 1.0,
    "USD": 86.0,
    "EUR": 92.0,
    "GBP": 108.0,
    "SGD": 64.0,
}


def _normalise_to_inr_lpa(value: float, currency: str, period: str) -> float:
    fx = _FX_TO_INR.get(currency.upper(), 1.0)
    annual = value
    if period.lower() == "monthly":
        annual = value * 12
    elif period.lower() == "hourly":
        annual = value * 40 * 52  # 40h/wk * 52wk
    inr_annual = annual * fx
    return round(inr_annual / 100_000, 2)  # to lakhs


_LPA_RE = re.compile(
    r"(?P<lo>\d{1,3}(?:\.\d{1,2})?)\s*(?:-|to|–|—)\s*(?P<hi>\d{1,3}(?:\.\d{1,2})?)\s*(?:LPA|lakh|lakhs|lacs|L\.P\.A)",
    re.I,
)
_SINGLE_LPA_RE = re.compile(
    r"(?P<v>\d{1,3}(?:\.\d{1,2})?)\s*(?:LPA|lakh|lakhs|lacs|L\.P\.A)\b",
    re.I,
)
_INR_K_RE = re.compile(
    r"(?:INR|Rs\.?|₹)\s*(?P<lo>\d{1,3}(?:,\d{3})*)\s*(?:-|to|–|—)?\s*(?P<hi>\d{1,3}(?:,\d{3})*)?",
)


def parse_salary(job: dict[str, Any]) -> SalaryInfo:
    """Best-effort salary extraction. Returns LPA if currency is INR."""
    structured_min = job.get("job_min_salary")
    structured_max = job.get("job_max_salary")
    currency = (job.get("job_salary_currency") or "").upper()
    period = (job.get("job_salary_period") or "").lower()

    if structured_min or structured_max:
        cur = currency or "INR"
        per = period or "annual"
        lo = _normalise_to_inr_lpa(structured_min, cur, per) if structured_min else None
        hi = _normalise_to_inr_lpa(structured_max, cur, per) if structured_max else None
        return SalaryInfo(min_lpa=lo, max_lpa=hi, currency=cur, source="structured")

    desc = job.get("job_description") or ""
    if m := _LPA_RE.search(desc):
        return SalaryInfo(
            min_lpa=float(m.group("lo")),
            max_lpa=float(m.group("hi")),
            currency="INR",
            source="regex",
        )
    if m := _SINGLE_LPA_RE.search(desc):
        v = float(m.group("v"))
        return SalaryInfo(min_lpa=v, max_lpa=v, currency="INR", source="regex")

    return SalaryInfo(min_lpa=None, max_lpa=None, currency=currency or "", source="missing")


def parse_salary_with_llm(job: dict[str, Any]) -> SalaryInfo:
    """LLM fallback for the trickiest descriptions. Call sparingly."""
    base = parse_salary(job)
    if base.mid_lpa is not None or not llm.is_available():
        return base
    desc = (job.get("job_description") or "")[:3500]
    if not desc:
        return base
    try:
        prompt = llm.load_prompt("extract_salary", job_description=desc)
        out = llm.complete_json(prompt)
    except Exception:
        return base
    if not isinstance(out, dict):
        return base
    cur = (out.get("currency") or "INR").upper()
    period = out.get("period") or "annual"
    lo_raw = out.get("min_lpa")
    hi_raw = out.get("max_lpa")
    lo = _normalise_to_inr_lpa(float(lo_raw), cur, period) if lo_raw else None
    hi = _normalise_to_inr_lpa(float(hi_raw), cur, period) if hi_raw else None
    if lo is None and hi is None:
        return base
    return SalaryInfo(min_lpa=lo, max_lpa=hi, currency=cur, source="llm")


# ---------- recency ----------

def _days_since(posted_at_unix: int | None, posted_at_str: str | None) -> float | None:
    if posted_at_unix:
        try:
            dt = datetime.fromtimestamp(int(posted_at_unix), tz=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            pass
    if posted_at_str:
        try:
            dt = datetime.fromisoformat(posted_at_str.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            pass
    return None


def _recency_score(days: float | None) -> float:
    if days is None:
        return 0.5  # neutral
    return math.exp(-max(days, 0) / 30.0)


# ---------- resume text ----------

def resume_to_text(resume: dict[str, Any]) -> str:
    """Flatten the structured resume into one big string for embedding."""
    parts: list[str] = [resume.get("summary", "")]
    for exp in resume.get("experience", []):
        parts.append(f"{exp.get('title','')} at {exp.get('company','')}")
        parts.extend(exp.get("bullets", []) or [])
    parts.extend(resume.get("skills", []) or [])
    for proj in resume.get("projects", []):
        parts.append(proj.get("name", ""))
        parts.extend(proj.get("bullets", []) or [])
    for cert in resume.get("certifications", []):
        parts.append(cert.get("name", ""))
    return "\n".join(p for p in parts if p)


def job_to_text(job: dict[str, Any]) -> str:
    return "\n".join(
        s for s in [
            job.get("job_title", ""),
            job.get("employer_name", ""),
            job.get("job_description", ""),
        ] if s
    )


# ---------- main ranker ----------

def rank_jobs(
    jobs: list[dict[str, Any]],
    resume: dict[str, Any],
    *,
    weights: tuple[float, float, float] = (0.45, 0.35, 0.20),
    use_llm_salary_fallback: bool = False,
) -> pd.DataFrame:
    """Return a DataFrame sorted by composite score (descending), one row per job."""
    if not jobs:
        return pd.DataFrame()

    w_fit, w_sal, w_rec = weights
    w_total = w_fit + w_sal + w_rec

    resume_text = resume_to_text(resume)
    if not resume_text.strip():
        resume_text = "experienced professional"

    job_texts = [job_to_text(j) for j in jobs]
    resume_vec = _embed([resume_text])[0]
    job_vecs = _embed(job_texts)

    fits = np.array([_cosine(resume_vec, v) for v in job_vecs])
    # squash to 0-1 from cosine in [-1,1]
    fits = (fits + 1) / 2

    salaries: list[SalaryInfo] = []
    for j in jobs:
        info = (parse_salary_with_llm if use_llm_salary_fallback else parse_salary)(j)
        salaries.append(info)
    mids = np.array([s.mid_lpa if s.mid_lpa is not None else np.nan for s in salaries])
    if np.isnan(mids).all():
        salary_z = np.zeros(len(jobs))
    else:
        median = float(np.nanmedian(mids))
        std = float(np.nanstd(mids)) or 1.0
        filled = np.where(np.isnan(mids), median, mids)
        salary_z = (filled - median) / std
        # squash to 0-1 via sigmoid
        salary_z = 1 / (1 + np.exp(-salary_z))

    recencies = np.array([
        _recency_score(_days_since(j.get("job_posted_at_timestamp"), j.get("job_posted_at_datetime_utc")))
        for j in jobs
    ])

    composite = (w_fit * fits + w_sal * salary_z + w_rec * recencies) / w_total

    rows = []
    for i, job in enumerate(jobs):
        rows.append(
            {
                "job_id": job.get("job_id", ""),
                "title": job.get("job_title", ""),
                "company": job.get("employer_name", ""),
                "city": job.get("job_city") or job.get("_source_location", ""),
                "state": job.get("job_state", ""),
                "remote": bool(job.get("job_is_remote")),
                "posted_days_ago": _days_since(
                    job.get("job_posted_at_timestamp"),
                    job.get("job_posted_at_datetime_utc"),
                ),
                "salary_min_lpa": salaries[i].min_lpa,
                "salary_max_lpa": salaries[i].max_lpa,
                "salary_mid_lpa": salaries[i].mid_lpa,
                "salary_source": salaries[i].source,
                "fit_score": round(float(fits[i]), 4),
                "salary_score": round(float(salary_z[i]), 4),
                "recency_score": round(float(recencies[i]), 4),
                "composite_score": round(float(composite[i]), 4),
                "apply_link": job.get("job_apply_link") or job.get("job_google_link", ""),
                "description": job.get("job_description", ""),
            }
        )

    df = pd.DataFrame(rows)
    return df.sort_values("composite_score", ascending=False).reset_index(drop=True)


def top_n(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    return df.head(n).copy()
