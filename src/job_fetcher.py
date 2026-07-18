"""JSearch (RapidAPI) client with on-disk caching and dedup.

Why JSearch: it aggregates LinkedIn, Indeed, Google Jobs, ZipRecruiter et al,
sidesteps each site's hostile-to-scraping ToS, and has a free 200 req/mo tier.

Cache strategy:
- One JSON file per (query, location, page) tuple, keyed by SHA1.
- Default TTL 24h. The pipeline normally needs 5-10 requests per run; the cache
  means re-runs while iterating on prompts cost zero quota.

Offline fallback: if RAPIDAPI_KEY is missing, `fetch_jobs` returns whatever is
already cached, with a clear warning, so the pipeline can be developed/demoed
without a key.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://jsearch.p.rapidapi.com/search"
_HOST = "jsearch.p.rapidapi.com"
_API_KEY = os.getenv("RAPIDAPI_KEY", "").strip()

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "jobs_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h


def _has_key() -> bool:
    return bool(_API_KEY) and not _API_KEY.startswith("your_")


@dataclass
class JobQuery:
    role: str
    domain: str = ""
    locations: list[str] = field(default_factory=lambda: ["Bangalore"])
    employment_types: str = "FULLTIME"  # FULLTIME, PARTTIME, CONTRACTOR, INTERN
    date_posted: str = "month"          # all, today, 3days, week, month
    remote_only: bool = False
    num_pages: int = 2                   # 10 jobs per page, so 2 pages = ~20 hits per location
    country: str = "in"

    def search_string(self, location: str) -> str:
        base = f"{self.role} {self.domain}".strip()
        return f"{base} in {location}".strip()


def _cache_key(params: dict[str, Any]) -> Path:
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def _load_cache(path: Path, ttl: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _request(params: dict[str, Any]) -> dict[str, Any]:
    if not _has_key():
        raise RuntimeError("RAPIDAPI_KEY not set; cannot reach JSearch.")
    headers = {
        "X-RapidAPI-Key": _API_KEY,
        "X-RapidAPI-Host": _HOST,
    }
    resp = requests.get(_BASE_URL, headers=headers, params=params, timeout=30)
    if resp.status_code == 429:
        raise RuntimeError("JSearch rate limit hit (free tier = 200 req/mo). Wait or upgrade.")
    resp.raise_for_status()
    return resp.json()


def fetch_jobs(
    query: JobQuery,
    *,
    ttl: int = DEFAULT_TTL_SECONDS,
    force_refresh: bool = False,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Fetch jobs for every (location, page) combo, dedupe, and return a flat list.

    Each job is augmented with `_source_location` (the location we queried with) so
    the ranker can preserve user intent even after JSearch returns nearby results.
    """
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    api_call_count = 0

    for location in query.locations:
        for page in range(1, query.num_pages + 1):
            params = {
                "query": query.search_string(location),
                "page": str(page),
                "num_pages": "1",
                "country": query.country,
                "date_posted": query.date_posted,
                "employment_types": query.employment_types,
            }
            if query.remote_only:
                params["remote_jobs_only"] = "true"

            cache_path = _cache_key(params)
            payload: dict[str, Any] | None = None
            if not force_refresh:
                payload = _load_cache(cache_path, ttl)

            if payload is None:
                if not _has_key():
                    if not quiet:
                        print(
                            f"[job_fetcher] no RAPIDAPI_KEY and no cache for "
                            f"'{params['query']}' p{page}; skipping."
                        )
                    continue
                try:
                    payload = _request(params)
                    api_call_count += 1
                    _save_cache(cache_path, payload)
                    time.sleep(0.6)  # be polite even within free tier
                except Exception as e:
                    if not quiet:
                        print(f"[job_fetcher] fetch failed for {params['query']} p{page}: {e}")
                    continue

            for job in payload.get("data", []) or []:
                jid = job.get("job_id") or job.get("job_apply_link") or hashlib.sha1(
                    (
                        (job.get("job_title") or "")
                        + (job.get("employer_name") or "")
                        + (job.get("job_city") or "")
                    ).encode()
                ).hexdigest()
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                job["_source_location"] = location
                all_jobs.append(job)

    if not quiet:
        print(
            f"[job_fetcher] {len(all_jobs)} unique jobs, "
            f"{api_call_count} live API calls (rest from cache)"
        )
    return all_jobs


def from_file(path: str | Path, *, source_location: str = "fixture") -> list[dict[str, Any]]:
    """Load a JSearch-shaped JSON fixture from disk.

    Accepts either:
      - the raw JSearch envelope `{"data": [...]}` returned by the live API
      - a bare list `[...]` of job dicts

    Each job gets `_source_location` tagged so the ranker treats it the same
    way as a live fetch.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fixture not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        jobs = payload.get("data") or []
    elif isinstance(payload, list):
        jobs = payload
    else:
        raise ValueError(f"Unsupported fixture shape in {p}: expected dict or list")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = job.get("job_id") or job.get("job_apply_link") or hashlib.sha1(
            (
                (job.get("job_title") or "")
                + (job.get("employer_name") or "")
                + (job.get("job_city") or "")
            ).encode()
        ).hexdigest()
        if jid in seen:
            continue
        seen.add(jid)
        job.setdefault("_source_location", source_location)
        out.append(job)
    return out


def cached_job_files() -> Iterable[Path]:
    """Iterate every cache file (useful for offline rebuilds)."""
    return CACHE_DIR.glob("*.json")


def clear_cache() -> int:
    n = 0
    for f in cached_job_files():
        f.unlink()
        n += 1
    return n
