"""Drop ghost / dead postings before they hit the ranker.

Signals used (in order of strictness):

1. **Recency** — older than ``max_age_days`` is gone. Postings that have sat
   open for a month on LinkedIn/Naukri are almost always ghost jobs at this
   point.
2. **Applicant pile-up** — if the source surfaces ``_applicant_count`` and it
   exceeds ``max_applicants``, drop. You'll be a needle in a haystack.
3. **Apply link health** — optional HEAD check; 4xx/5xx means the posting was
   pulled but the listing hasn't been delisted yet.
4. **Cross-source dedupe** — same (employer, title, city) keep the freshest
   posting, drop the rest.
5. **Third-party recruiter de-prioritise** — recruiters (consultancy/staffing
   agencies) get a flag set on the job dict so the ranker can downweight; we do
   not drop because some of these are legitimate retained-search firms.

Each input job is a dict shaped like ``src.job_fetcher``/``src.jobspy_fetcher``
output. The filter is non-destructive; it returns a new list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import requests


@dataclass
class FilterStats:
    input_count: int = 0
    dropped_stale: int = 0
    dropped_crowded: int = 0
    dropped_broken_link: int = 0
    dropped_blacklist: int = 0
    dropped_low_salary: int = 0
    collapsed_duplicates: int = 0
    flagged_recruiter: int = 0
    output_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input_count,
            "dropped_stale": self.dropped_stale,
            "dropped_crowded": self.dropped_crowded,
            "dropped_broken_link": self.dropped_broken_link,
            "dropped_blacklist": self.dropped_blacklist,
            "dropped_low_salary": self.dropped_low_salary,
            "collapsed_duplicates": self.collapsed_duplicates,
            "flagged_recruiter": self.flagged_recruiter,
            "output": self.output_count,
        }


def _days_since(job: dict[str, Any]) -> float | None:
    ts = job.get("job_posted_at_timestamp")
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except Exception:
            pass
    iso = job.get("job_posted_at_datetime_utc")
    if iso:
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except Exception:
            pass
    return None


def _is_recruiter(name: str, needles: Iterable[str]) -> bool:
    n = name.lower()
    return any(needle.lower() in n for needle in needles)


def _validate_link(url: str, timeout: float = 4.0) -> bool:
    """HEAD-check; treat 4xx/5xx as dead. Some sites 405 on HEAD, in which case
    we fall back to a small GET. Returns True if reachable."""
    if not url:
        return False
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code == 405:
            r = requests.get(url, timeout=timeout, stream=True)
        return 200 <= r.status_code < 400
    except Exception:
        return False


def _salary_mid_lpa(job: dict[str, Any]) -> float | None:
    """Quick salary read for the floor check (full normalisation lives in ranker.py)."""
    cur = (job.get("job_salary_currency") or "INR").upper()
    if cur != "INR":
        # Conservatively let non-INR through; the ranker does the FX maths properly.
        return None
    lo = job.get("job_min_salary")
    hi = job.get("job_max_salary")
    period = (job.get("job_salary_period") or "yearly").lower()
    vals: list[float] = []
    for v in (lo, hi):
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            f = None
        if f is None:
            continue
        if period.startswith("month"):
            f *= 12
        elif period.startswith("hour"):
            f *= 40 * 52
        # INR salaries are usually quoted in absolute rupees on JobSpy/Naukri;
        # convert to lakhs.
        if f > 1000:
            f = f / 100_000
        vals.append(f)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _dedupe_key(job: dict[str, Any]) -> str:
    employer = (job.get("employer_name") or "").strip().lower()
    title = (job.get("job_title") or "").strip().lower()
    city = (job.get("job_city") or "").strip().lower()
    title = re.sub(r"\s+", " ", title)
    return f"{employer}|{title}|{city}"


def filter_jobs(
    jobs: list[dict[str, Any]],
    *,
    max_age_days: int = 21,
    max_applicants: int | None = 200,
    validate_apply_link: bool = False,
    employer_blacklist: list[str] | None = None,
    recruiter_keywords: list[str] | None = None,
    salary_floor_lpa: float | None = None,
) -> tuple[list[dict[str, Any]], FilterStats]:
    """Run all engagement filters; returns (kept_jobs, stats)."""
    stats = FilterStats(input_count=len(jobs))
    blacklist = [b.lower() for b in (employer_blacklist or [])]
    recruiter_kw = list(recruiter_keywords or [])

    # Pass 1: stale / blacklisted / crowded / low-salary
    survivors: list[dict[str, Any]] = []
    for job in jobs:
        employer = (job.get("employer_name") or "").strip()
        if blacklist and any(b in employer.lower() for b in blacklist):
            stats.dropped_blacklist += 1
            continue

        age = _days_since(job)
        if age is not None and age > max_age_days:
            stats.dropped_stale += 1
            continue

        if max_applicants is not None:
            count = job.get("_applicant_count")
            if isinstance(count, int) and count > max_applicants:
                stats.dropped_crowded += 1
                continue

        if salary_floor_lpa is not None:
            mid = _salary_mid_lpa(job)
            if mid is not None and mid < salary_floor_lpa:
                stats.dropped_low_salary += 1
                continue

        # Flag recruiters but keep them
        if recruiter_kw and _is_recruiter(employer, recruiter_kw):
            job["_is_third_party_recruiter"] = True
            stats.flagged_recruiter += 1
        else:
            job["_is_third_party_recruiter"] = False

        # Carry the computed age so downstream code doesn't recompute
        job["_days_since_posted"] = age
        survivors.append(job)

    # Pass 2: cross-source dedupe — keep the freshest
    by_key: dict[str, dict[str, Any]] = {}
    for job in survivors:
        key = _dedupe_key(job)
        if not key.strip("|"):
            # No employer or title — keep as-is, treat as unique
            by_key[f"_uniq_{id(job)}"] = job
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = job
            continue
        # Prefer the one with a more recent posted date; tiebreak on description length
        new_age = job.get("_days_since_posted")
        old_age = existing.get("_days_since_posted")
        if (new_age is not None and old_age is not None and new_age < old_age) or (
            new_age is not None and old_age is None
        ):
            by_key[key] = job
            stats.collapsed_duplicates += 1
        elif new_age == old_age and len(job.get("job_description") or "") > len(
            existing.get("job_description") or ""
        ):
            by_key[key] = job
            stats.collapsed_duplicates += 1
        else:
            stats.collapsed_duplicates += 1
    deduped = list(by_key.values())

    # Pass 3: optional link health (expensive — only run on the trimmed pool)
    if validate_apply_link:
        kept: list[dict[str, Any]] = []
        for job in deduped:
            url = job.get("job_apply_link") or ""
            if not url:
                kept.append(job)
                continue
            if _validate_link(url):
                kept.append(job)
            else:
                stats.dropped_broken_link += 1
        deduped = kept

    stats.output_count = len(deduped)
    return deduped, stats


def merge_sources(*pools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten multiple fetcher outputs into one list with global job_id dedupe."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for pool in pools:
        for job in pool:
            jid = job.get("job_id") or ""
            key = jid or _dedupe_key(job)
            if key in seen:
                continue
            seen.add(key)
            out.append(job)
    return out
