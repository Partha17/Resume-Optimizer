"""Render an HTML comparison report from artifacts already produced by dry_run.py.

Pure-Python (no Gemini calls), so it's safe to run repeatedly even when the
upstream LLM quota is exhausted. Reads everything under data/output/{slug}/
and writes data/output/comparison_report.html.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO / "data" / "output"


def _read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _kw_pills(keywords: list[dict], tier_filter: str, limit: int = 25) -> str:
    items = [k for k in keywords if k.get("tier") == tier_filter][:limit]
    if not items:
        return "<em>none</em>"
    return "".join(
        f"<span class='pill {k['tier']}'>{k['display']} "
        f"<small>({int(k['frequency'] * 100)}%)</small></span>"
        for k in items
    )


def _missing_pills(missing: list[str], limit: int = 25) -> str:
    if not missing:
        return "<em>none</em>"
    return "".join(f"<span class='pill miss'>{m}</span>" for m in missing[:limit])


def _fmt_lpa(v) -> str | None:
    """Format a value as an integer LPA string, or None if NaN/missing."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check
        return None
    return f"{int(round(f))}"


def _job_table(jobs: list[dict], n: int = 8) -> str:
    rows = []
    for j in jobs[:n]:
        lo = _fmt_lpa(j.get("salary_min_lpa"))
        hi = _fmt_lpa(j.get("salary_max_lpa"))
        if lo and hi:
            salary = f"₹{lo}-{hi}L"
        elif lo or hi:
            salary = f"₹{lo or hi}L"
        else:
            salary = "—"
        link = j.get("apply_link") or "#"
        rows.append(
            f"<tr>"
            f"<td>{j['title']}</td>"
            f"<td>{j['company']}</td>"
            f"<td>{j.get('city', '')}</td>"
            f"<td>{salary}</td>"
            f"<td>{j.get('posted_days_ago', '—')}d</td>"
            f"<td>{j['composite_score']:.3f}</td>"
            f"<td><a href='{link}' target='_blank'>apply</a></td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Title</th><th>Company</th><th>City</th><th>Salary</th>"
        "<th>Posted</th><th>Fit</th><th>Link</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _role_section(slug: str) -> str:
    role_dir = OUT_ROOT / slug
    jobs = _read_json(role_dir / "jobs.json") or []
    keywords = _read_json(role_dir / "keywords.json") or []
    ats = _read_json(role_dir / "ats_report.json") or {}
    summary_entry = next(
        (s for s in (_read_json(OUT_ROOT / "_dry_run_summary.json") or []) if s.get("slug") == slug),
        {},
    )

    before = ats.get("before", {})
    after = ats.get("after", {})
    cov_before = before.get("keyword_coverage", {})
    cov_after = after.get("keyword_coverage", {})

    role_label = summary_entry.get("role", slug.title())
    top_salary = summary_entry.get("top_salary_lpa", 0)
    median_salary = summary_entry.get("median_salary_lpa", 0)

    return f"""
<section id="{slug}">
  <h2>{role_label}</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-label">Top salary</div><div class="kpi-value">₹{top_salary:.1f}L</div></div>
    <div class="kpi"><div class="kpi-label">Median (top {len(jobs)})</div><div class="kpi-value">₹{median_salary:.1f}L</div></div>
    <div class="kpi"><div class="kpi-label">Baseline ATS</div><div class="kpi-value">{before.get('overall', 0):.1f}</div></div>
    <div class="kpi"><div class="kpi-label">After rewrite</div><div class="kpi-value">{after.get('overall', 0):.1f}</div></div>
    <div class="kpi"><div class="kpi-label">Critical kw missing</div><div class="kpi-value">{summary_entry.get('must_add', '—')}</div></div>
  </div>

  <h3>Top jobs in this market</h3>
  {_job_table(jobs)}

  <h3>Critical keywords (≥60% of top JDs)</h3>
  <div class="pills">{_kw_pills(keywords, 'critical')}</div>

  <h3>Recommended keywords (30-60%)</h3>
  <div class="pills">{_kw_pills(keywords, 'recommended', limit=20)}</div>

  <h3>Coverage by tier</h3>
  <table class="coverage">
    <thead><tr><th>Tier</th><th>Baseline %</th><th>After %</th><th>Delta</th></tr></thead>
    <tbody>
      {''.join(
        f"<tr><td>{tier}</td>"
        f"<td>{cov_before.get(tier, 0)}</td>"
        f"<td>{cov_after.get(tier, 0)}</td>"
        f"<td>{round(cov_after.get(tier, 0) - cov_before.get(tier, 0), 1):+}</td></tr>"
        for tier in ['critical', 'recommended', 'nice_to_have', 'all']
      )}
    </tbody>
  </table>

  <h3>Missing critical keywords (must-add when LLM rewrite available)</h3>
  <div class="pills">{_missing_pills(after.get('keyword_misses', {}).get('critical', []))}</div>

  <p class="artifacts">
    <a href="{slug}/optimized_resume.docx">optimized_resume.docx</a> ·
    <a href="{slug}/baseline_resume.docx">baseline_resume.docx</a> ·
    <a href="{slug}/jobs.json">jobs.json</a> ·
    <a href="{slug}/keywords.json">keywords.json</a>
  </p>
</section>
"""


def main() -> int:
    summaries = _read_json(OUT_ROOT / "_dry_run_summary.json") or []
    if not summaries:
        print("No _dry_run_summary.json found. Run scripts/dry_run.py first.", file=sys.stderr)
        return 1

    # Sort: highest baseline ATS first → most natural target
    summaries.sort(key=lambda s: s.get("ats_before", 0), reverse=True)

    rows = []
    for s in summaries:
        rows.append(
            f"<tr><td><a href='#{s['slug']}'>{s['role']}</a></td>"
            f"<td>₹{s.get('top_salary_lpa', 0):.1f}L</td>"
            f"<td>₹{s.get('median_salary_lpa', 0):.1f}L</td>"
            f"<td>{s.get('n_critical_kw', '—')}</td>"
            f"<td>{s.get('must_add', '—')}</td>"
            f"<td>{s.get('ats_before', 0):.1f}</td>"
            f"<td>{s.get('ats_after', 0):.1f}</td></tr>"
        )

    best = summaries[0]
    body = f"""
<header>
  <h1>Resume Optimizer — Cross-Role Comparison</h1>
  <p>Three target roles evaluated against Bangalore/Remote India biotech &amp; pharma market.
     Sorted by baseline ATS fit (highest = most natural lateral move).</p>
  <div class="banner">
    <strong>Best natural fit:</strong> {best['role']} —
    baseline ATS {best['ats_before']:.1f}, top role ₹{best['top_salary_lpa']:.1f}L
  </div>
</header>

<h2>At-a-glance</h2>
<table>
  <thead><tr>
    <th>Role</th><th>Top salary</th><th>Median (top N)</th>
    <th># Critical kw</th><th>Missing critical</th>
    <th>Baseline ATS</th><th>After rewrite</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>

{''.join(_role_section(s['slug']) for s in summaries)}

<footer>
  <p><small>Generated by <code>scripts/build_report.py</code>. Re-run after <code>scripts/dry_run.py</code> to refresh.</small></p>
</footer>
"""

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Resume Optimizer Comparison</title>
<style>
  :root {{
    --bg: #fafafa; --fg: #222; --muted: #666;
    --accent: #1f6feb; --pill-bg: #eef3ff; --pill-fg: #1f6feb;
    --rec-bg: #fff5d6; --rec-fg: #7a5500;
    --miss-bg: #ffe1e1; --miss-fg: #a00;
    --border: #ddd; --kpi-bg: #fff;
  }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 20px; color: var(--fg); background: var(--bg); }}
  h1 {{ margin-bottom: 4px; }}
  h2 {{ margin-top: 36px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  h3 {{ margin-top: 18px; color: var(--muted); font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .banner {{ background: #e7f3ff; border-left: 4px solid var(--accent); padding: 12px 16px; border-radius: 4px; margin: 12px 0 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 20px; font-size: 14px; }}
  th, td {{ border: 1px solid var(--border); padding: 6px 10px; text-align: left; }}
  th {{ background: #f1f1f1; }}
  .pills {{ margin: 8px 0; }}
  .pill {{ display: inline-block; padding: 3px 10px; margin: 3px 4px 3px 0; border-radius: 12px; background: var(--pill-bg); color: var(--pill-fg); font-size: 13px; }}
  .pill.recommended {{ background: var(--rec-bg); color: var(--rec-fg); }}
  .pill.nice_to_have {{ background: #eaeaea; color: #444; }}
  .pill.miss {{ background: var(--miss-bg); color: var(--miss-fg); }}
  .pill small {{ opacity: 0.7; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 12px 0 20px; }}
  .kpi {{ background: var(--kpi-bg); border: 1px solid var(--border); padding: 10px 14px; border-radius: 6px; }}
  .kpi-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
  .kpi-value {{ font-size: 22px; font-weight: 600; margin-top: 2px; }}
  .coverage td:last-child {{ font-weight: bold; }}
  .artifacts {{ font-size: 13px; color: var(--muted); }}
  a {{ color: var(--accent); }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--muted); }}
</style>
</head><body>{body}</body></html>
"""

    out_path = OUT_ROOT / "comparison_report.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
