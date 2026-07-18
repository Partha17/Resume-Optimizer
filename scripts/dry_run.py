"""Dry-run the Resume Optimizer pipeline across multiple target roles.

Useful when:
  - You don't have a JSearch (RapidAPI) key yet and want to use the bundled
    JD fixtures instead.
  - You want to compare the optimized resume across two or three potential
    target roles (e.g. QA vs CDM vs Microbiologist) to decide which market
    to commit to.

Usage:
    python scripts/dry_run.py                # all three preset roles
    python scripts/dry_run.py --roles qa cdm # subset
    python scripts/dry_run.py --resume data/input/resume.pdf

Outputs land in data/output/{role_slug}/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import (  # noqa: E402
    ats_scorer,
    job_fetcher,
    keyword_extractor,
    llm,
    ranker,
    resume_parser,
    resume_writer,
)


@dataclass(frozen=True)
class RolePreset:
    slug: str
    role: str
    domain: str
    fixture: str
    description: str


PRESETS: dict[str, RolePreset] = {
    "qa": RolePreset(
        slug="qa",
        role="Quality Assurance Executive",
        domain="pharmaceutical biopharma quality compliance",
        fixture="tests/fixtures/jd_qa.json",
        description="QA / Quality Assurance — matches career objective, typically highest paid",
    ),
    "cdm": RolePreset(
        slug="cdm",
        role="Clinical Data Manager",
        domain="clinical research clinical data management",
        fixture="tests/fixtures/jd_cdm.json",
        description="Clinical Data Management — certified pivot direction, remote-friendly",
    ),
    "microbiologist": RolePreset(
        slug="microbiologist",
        role="Senior Microbiologist",
        domain="biotech pharmaceutical biopharma microbiology",
        fixture="tests/fixtures/jd_microbiologist.json",
        description="Senior Microbiologist — builds on current 4yr depth",
    ),
}


def _print_section(title: str) -> None:
    bar = "=" * (len(title) + 4)
    print(f"\n{bar}\n  {title}\n{bar}")


def run_one(
    preset: RolePreset,
    resume: dict,
    *,
    output_root: Path,
    top_n: int,
) -> dict:
    """Run the full pipeline for a single role preset. Returns a summary dict."""
    _print_section(f"ROLE: {preset.role}  ({preset.slug})")
    out_dir = output_root / preset.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    fixture_path = REPO / preset.fixture
    print(f"loading fixture: {fixture_path}")
    jobs = job_fetcher.from_file(fixture_path)
    print(f"  {len(jobs)} jobs in pool")

    print("ranking ...")
    ranked = ranker.rank_jobs(jobs, resume)
    top = ranked.head(top_n)
    print(f"  top-{len(top)} composite_score range: "
          f"{top['composite_score'].min():.3f} - {top['composite_score'].max():.3f}")
    print(f"  top hit: {top.iloc[0]['title']} @ {top.iloc[0]['company']} "
          f"({top.iloc[0]['salary_mid_lpa']} LPA)")

    print("mining keywords ...")
    descs = top["description"].fillna("").tolist()
    market_records = keyword_extractor.extract_market_keywords(
        descs, role=preset.role, domain=preset.domain, top_per_jd=25,
    )
    critical = [r for r in market_records if r.tier == "critical"]
    print(f"  {len(market_records)} keywords, {len(critical)} critical")
    print(f"  sample critical: {[r.display for r in critical[:8]]}")

    print("gap analysis ...")
    tokens = keyword_extractor.resume_tokens(resume)
    buckets = keyword_extractor.diff_against_resume(market_records, tokens)
    print(f"  must_add={len(buckets['must_add'])}, "
          f"should_emphasize={len(buckets['should_emphasize'])}, "
          f"already_have={len(buckets['already_have'])}")

    print("rendering baseline DOCX ...")
    baseline_path = out_dir / "baseline_resume.docx"
    resume_writer.write_docx(resume, baseline_path)
    before = ats_scorer.score_resume(baseline_path, market_records)
    print(f"  baseline ATS: {before.overall:.1f} / 100")

    print("rewriting with Gemini ..." if llm.is_available() else "rewrite skipped (no Gemini key)")
    crit_list = [r.display for r in market_records if r.tier == "critical"]
    rec_list = [r.display for r in market_records if r.tier == "recommended"]
    optimized = resume_writer.optimize_resume(
        resume,
        role=preset.role,
        domain=preset.domain,
        critical_keywords=crit_list,
        recommended_keywords=rec_list,
    )

    optimized_path = out_dir / "optimized_resume.docx"
    resume_writer.write_docx(optimized, optimized_path)
    resume_writer.write_pdf_if_possible(optimized_path, out_dir / "optimized_resume.pdf")

    after = ats_scorer.score_resume(optimized_path, market_records)
    delta = after.overall - before.overall
    print(f"  optimized ATS: {after.overall:.1f} / 100  (delta: {delta:+.1f})")

    # persist artifacts
    (out_dir / "jobs.json").write_text(
        json.dumps(ranked.to_dict(orient="records"), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (out_dir / "keywords.json").write_text(
        json.dumps([r.__dict__ for r in market_records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "ats_report.json").write_text(
        json.dumps({"before": before.to_dict(), "after": after.to_dict()}, indent=2),
        encoding="utf-8",
    )
    (out_dir / "optimized_resume.json").write_text(
        json.dumps(optimized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  artifacts in: {out_dir.relative_to(REPO)}")

    return {
        "role": preset.role,
        "slug": preset.slug,
        "top_salary_lpa": float(top.iloc[0]["salary_mid_lpa"] or 0),
        "median_salary_lpa": float(top["salary_mid_lpa"].dropna().median() or 0),
        "n_critical_kw": len(critical),
        "must_add": len(buckets["must_add"]),
        "ats_before": before.overall,
        "ats_after": after.overall,
        "ats_delta": round(delta, 1),
        "output_dir": str(out_dir.relative_to(REPO)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        default="data/input/resume.pdf",
        help="Path to the resume file (PDF/DOCX/TXT).",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        default=list(PRESETS.keys()),
        choices=list(PRESETS.keys()),
        help="Subset of role presets to run.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="How many top JDs feed the keyword miner (default 10).",
    )
    parser.add_argument(
        "--output",
        default="data/output",
        help="Output root directory.",
    )
    args = parser.parse_args()

    output_root = REPO / args.output
    output_root.mkdir(parents=True, exist_ok=True)

    resume_path = REPO / args.resume
    if not resume_path.is_absolute():
        resume_path = REPO / args.resume
    if not resume_path.exists():
        print(f"ERROR: resume not found at {resume_path}", file=sys.stderr)
        return 1

    _print_section("PARSING RESUME")
    print(f"file: {resume_path}")
    print(f"Gemini available: {llm.is_available()}")
    print(f"JSearch available: {job_fetcher._has_key()}")
    started = time.time()
    resume = resume_parser.parse_resume(resume_path, use_llm=llm.is_available())
    print(f"  name: {resume['contact'].get('name')}")
    print(f"  experiences: {len(resume['experience'])}, "
          f"skills: {len(resume['skills'])}, "
          f"certs: {len(resume['certifications'])}")
    print(f"  parsed in {time.time() - started:.1f}s")

    (output_root / "_resume_parsed.json").write_text(
        json.dumps(resume, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summaries = []
    for slug in args.roles:
        preset = PRESETS[slug]
        try:
            summaries.append(
                run_one(preset, resume, output_root=output_root, top_n=args.top_n)
            )
        except Exception as e:
            print(f"\n[!] {slug} failed: {e}")
            summaries.append({
                "role": preset.role, "slug": slug, "error": str(e),
            })

    _print_section("SUMMARY")
    cols = ["slug", "role", "top_salary_lpa", "median_salary_lpa",
            "n_critical_kw", "must_add", "ats_before", "ats_after", "ats_delta"]
    widths = {c: max(len(c), max(len(str(s.get(c, ""))) for s in summaries)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for s in summaries:
        print("  ".join(str(s.get(c, "")).ljust(widths[c]) for c in cols))

    # write final comparison
    (output_root / "_dry_run_summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nFull artifacts under: {output_root.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
