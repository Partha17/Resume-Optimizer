"""JobSpy adapter: pulls jobs from Naukri / LinkedIn / Indeed / Glassdoor / Google
and emits the same job dict shape produced by :mod:`src.job_fetcher` so the
ranker and engagement filter stay source-agnostic.

Why this exists alongside ``job_fetcher.py``:
- JSearch (the existing fetcher) covers LinkedIn + Indeed + Google Jobs as an
  aggregator, but its India / Naukri coverage is thin. Pharma QC roles in India
  live disproportionately on Naukri.com, which JobSpy scrapes directly.
- JobSpy is best-effort: LinkedIn rate-limits aggressively without a proxy;
  Naukri tends to be reliable but description text is sometimes truncated.

Output schema (matches ``src.job_fetcher`` keys consumed by the ranker):

    {
        "job_id": str,
        "job_title": str,
        "employer_name": str,
        "job_city": str,
        "job_state": str,
        "job_country": str,
        "job_is_remote": bool,
        "job_posted_at_timestamp": int | None,    # epoch seconds
        "job_posted_at_datetime_utc": str | None,
        "job_min_salary": float | None,
        "job_max_salary": float | None,
        "job_salary_currency": str,
        "job_salary_period": str,
        "job_description": str,
        "job_apply_link": str,
        "_source": "jobspy:<site_name>",
        "_source_location": str,                  # the location string we queried
        "_applicant_count": int | None,           # LinkedIn surfaces this for some jobs
    }
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h


@dataclass
class JobSpyQuery:
    role: str
    locations: list[str] = field(default_factory=lambda: ["Bangalore"])
    sites: list[str] = field(default_factory=lambda: ["naukri", "indeed", "linkedin"])
    results_wanted: int = 25
    hours_old: int = 24 * 14   # 2 weeks of recency
    country_indeed: str = "India"
    is_remote: bool = False
    distance_km: int = 50
    linkedin_fetch_description: bool = False  # slower; enable when LinkedIn is critical


def _cache_path(params: dict[str, Any]) -> Path:
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return CACHE_DIR / f"jobspy_{key}.json"


def _load_cache(path: Path, ttl: int) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_cache(path: Path, payload: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _is_available() -> bool:
    try:
        import jobspy  # noqa: F401
        return True
    except Exception:
        return False


def _safe_float(value: Any) -> float | None:
    if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    f = _safe_float(value)
    return int(f) if f is not None else None


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _to_epoch(value: Any) -> int | None:
    if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def _normalise_row(row: dict[str, Any], site: str, location: str) -> dict[str, Any]:
    """Map a JobSpy row (dict from DataFrame.to_dict) to the JSearch-shaped job dict."""
    title = _safe_str(row.get("title"))
    employer = _safe_str(row.get("company"))
    city = _safe_str(row.get("city")) or _safe_str(row.get("location"))
    state = _safe_str(row.get("state"))
    country = _safe_str(row.get("country"))
    is_remote = bool(row.get("is_remote") or False)
    description = _safe_str(row.get("description"))
    apply_link = (
        _safe_str(row.get("job_url_direct"))
        or _safe_str(row.get("job_url"))
        or _safe_str(row.get("url"))
    )

    posted_str = _safe_str(row.get("date_posted"))
    posted_ts = _to_epoch(row.get("date_posted"))

    salary_min = _safe_float(row.get("min_amount"))
    salary_max = _safe_float(row.get("max_amount"))
    salary_cur = _safe_str(row.get("currency")) or ("INR" if country.lower().startswith("india") else "")
    salary_period = _safe_str(row.get("interval")) or "yearly"

    applicants = _safe_int(row.get("listing_type"))  # JobSpy doesn't expose this; placeholder
    # Some JobSpy versions expose ``num_urgent`` or ``applicants`` for LinkedIn — try both.
    for key in ("applicants", "num_applicants", "linkedin_applicants"):
        if (v := _safe_int(row.get(key))) is not None:
            applicants = v
            break

    raw_id = _safe_str(row.get("id")) or apply_link or f"{employer}|{title}|{city}"
    job_id = f"jobspy:{site}:{hashlib.sha1(raw_id.encode()).hexdigest()[:16]}"

    return {
        "job_id": job_id,
        "job_title": title,
        "employer_name": employer,
        "job_city": city,
        "job_state": state,
        "job_country": country,
        "job_is_remote": is_remote,
        "job_posted_at_timestamp": posted_ts,
        "job_posted_at_datetime_utc": posted_str or None,
        "job_min_salary": salary_min,
        "job_max_salary": salary_max,
        "job_salary_currency": salary_cur,
        "job_salary_period": salary_period,
        "job_description": description,
        "job_apply_link": apply_link,
        "_source": f"jobspy:{site}",
        "_source_location": location,
        "_applicant_count": applicants,
    }


def fetch_jobs(
    query: JobSpyQuery,
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    force_refresh: bool = False,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run JobSpy for every (location, site) pair, dedupe, return JSearch-shaped jobs.

    The dedupe key is (employer_name, job_title, job_city) lowercased so the same
    posting cross-listed on multiple boards collapses to one row.
    """
    if not _is_available():
        if not quiet:
            print("[jobspy_fetcher] python-jobspy not installed; returning [].")
        return []

    from jobspy import scrape_jobs  # type: ignore

    all_jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    live_calls = 0

    for location in query.locations:
        params = {
            "site_name": query.sites,
            "search_term": query.role,
            "location": location,
            "results_wanted": query.results_wanted,
            "hours_old": query.hours_old,
            "country_indeed": query.country_indeed,
            "is_remote": query.is_remote,
            "linkedin_fetch_description": query.linkedin_fetch_description,
            "distance": query.distance_km,
        }
        cache_path = _cache_path(params)
        rows: list[dict[str, Any]] | None = None
        if not force_refresh:
            rows = _load_cache(cache_path, ttl)

        if rows is None:
            try:
                df = scrape_jobs(**params)
            except Exception as e:
                if not quiet:
                    print(f"[jobspy_fetcher] scrape_jobs failed for {location}: {e}")
                continue
            try:
                rows = df.to_dict(orient="records") if df is not None else []
            except Exception:
                rows = []
            live_calls += 1
            _save_cache(cache_path, rows)
            time.sleep(0.8)  # politeness gap between locations

        for row in rows or []:
            site = _safe_str(row.get("site")) or "unknown"
            normalised = _normalise_row(row, site=site, location=location)
            dedupe_key = (
                normalised["employer_name"].lower(),
                normalised["job_title"].lower(),
                normalised["job_city"].lower(),
            )
            dedupe_key_str = "|".join(dedupe_key)
            if dedupe_key_str in seen:
                continue
            seen.add(dedupe_key_str)
            all_jobs.append(normalised)

    if not quiet:
        print(
            f"[jobspy_fetcher] {len(all_jobs)} unique jobs across "
            f"{len(query.locations)} location(s) × {len(query.sites)} site(s), "
            f"{live_calls} live scrape(s) (rest from cache)"
        )
    return all_jobs


def fetch_for_role_aliases(
    role_aliases: Iterable[str],
    *,
    locations: list[str],
    sites: list[str] | None = None,
    hours_old: int = 24 * 14,
    results_wanted: int = 25,
    country_indeed: str = "India",
    force_refresh: bool = False,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Convenience helper: run ``fetch_jobs`` once per alias, dedupe globally."""
    seen: set[str] = set()
    pooled: list[dict[str, Any]] = []
    sites_resolved = sites or ["naukri", "indeed", "linkedin"]

    for alias in role_aliases:
        q = JobSpyQuery(
            role=alias,
            locations=locations,
            sites=sites_resolved,
            results_wanted=results_wanted,
            hours_old=hours_old,
            country_indeed=country_indeed,
        )
        for job in fetch_jobs(q, force_refresh=force_refresh, quiet=quiet):
            if job["job_id"] in seen:
                continue
            seen.add(job["job_id"])
            pooled.append(job)
    return pooled
