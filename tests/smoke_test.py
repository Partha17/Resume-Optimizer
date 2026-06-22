"""Offline structural smoke test for the pipeline.

Runs every stage without requiring API keys:
  - resume_parser: uses the heuristic path (no Gemini)
  - job_fetcher: bypassed by loading a canned JSON fixture
  - ranker: full embedding-based ranking
  - keyword_extractor: full KeyBERT pass, classifier falls back to 'hard_skill'
  - resume_writer: rewrite stage is a no-op without Gemini; DOCX render runs
  - ats_scorer: full coverage + format checks

Exits non-zero on any structural failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import (  # noqa: E402
    ats_scorer,
    keyword_extractor,
    ranker,
    resume_parser,
    resume_writer,
)


def main() -> int:
    print("== resume_parser ==")
    resume = resume_parser.parse_resume(
        REPO / "tests" / "sample_resume.txt", use_llm=False
    )
    assert resume["contact"]["email"] == "priya.iyer@example.com", resume["contact"]
    assert resume["contact"]["name"], "name not extracted"
    assert len(resume["experience"]) >= 2, f"too few experience entries: {len(resume['experience'])}"
    assert len(resume["skills"]) >= 5, f"too few skills: {resume['skills']}"
    print(f"  parsed: name={resume['contact']['name']!r}, "
          f"experiences={len(resume['experience'])}, skills={len(resume['skills'])}")

    print("== job_fetcher (fixture) ==")
    fixture = json.loads((REPO / "tests" / "sample_jobs.json").read_text())
    jobs = fixture["data"]
    for j in jobs:
        j["_source_location"] = j.get("job_city", "")
    print(f"  loaded {len(jobs)} fixture jobs")

    print("== ranker ==")
    ranked = ranker.rank_jobs(jobs, resume)
    assert not ranked.empty, "ranker returned empty"
    assert ranked.iloc[0]["composite_score"] >= ranked.iloc[-1]["composite_score"], "not sorted"
    print(
        f"  top: {ranked.iloc[0]['title']} @ {ranked.iloc[0]['company']} "
        f"(score {ranked.iloc[0]['composite_score']:.3f}, "
        f"salary mid={ranked.iloc[0]['salary_mid_lpa']} LPA)"
    )

    print("== keyword_extractor ==")
    descriptions = ranked.head(8)["description"].tolist()
    records = keyword_extractor.extract_market_keywords(
        descriptions, role="Microbiologist", domain="biotech pharma"
    )
    assert records, "no keywords extracted"
    critical = [r for r in records if r.tier == "critical"]
    print(f"  {len(records)} keywords, {len(critical)} critical")
    print(f"  sample critical: {[r.display for r in critical[:6]]}")

    print("== gap analysis ==")
    tokens = keyword_extractor.resume_tokens(resume)
    buckets = keyword_extractor.diff_against_resume(records, tokens)
    print(
        f"  must_add={len(buckets['must_add'])}, "
        f"should_emphasize={len(buckets['should_emphasize'])}, "
        f"already_have={len(buckets['already_have'])}"
    )

    print("== resume_writer (no-LLM path) ==")
    out_dir = REPO / "tests" / "_smoke_out"
    out_dir.mkdir(exist_ok=True)
    baseline_path = out_dir / "baseline.docx"
    resume_writer.write_docx(resume, baseline_path)
    assert baseline_path.exists() and baseline_path.stat().st_size > 1000, "baseline DOCX missing"
    print(f"  baseline DOCX: {baseline_path.stat().st_size} bytes")

    # optimize_resume should be a no-op without Gemini, but skill reorder still runs
    critical_keys = [r.display for r in records if r.tier == "critical"]
    recommended_keys = [r.display for r in records if r.tier == "recommended"]
    optimized = resume_writer.optimize_resume(
        resume,
        role="Microbiologist",
        domain="biotech pharma",
        critical_keywords=critical_keys,
        recommended_keywords=recommended_keys,
    )
    optimized_path = out_dir / "optimized.docx"
    resume_writer.write_docx(optimized, optimized_path)
    assert optimized_path.exists(), "optimized DOCX missing"
    print(f"  optimized DOCX: {optimized_path.stat().st_size} bytes")

    print("== ats_scorer ==")
    before = ats_scorer.score_resume(baseline_path, records)
    after = ats_scorer.score_resume(optimized_path, records)
    print(f"  before: overall={before.overall}, critical={before.keyword_coverage.get('critical')}")
    print(f"  after:  overall={after.overall}, critical={after.keyword_coverage.get('critical')}")
    assert before.overall > 0, "scorer returned 0"
    assert "no_tables" in before.format_checks
    assert "no_images" in before.format_checks
    print(f"  format checks: {before.format_checks}")
    if before.format_notes:
        print(f"  notes: {before.format_notes}")

    print("\nAll stages green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
