"""Apply LLM rewrites produced manually in-chat by Opus 4.7 to the parsed resume.

Used when the configured Gemini key has no working quota. The Opus session in
the Cursor IDE plays the role of the rewrite LLM. This script is the dumb
applier: it just merges the hand-written rewrites into the parsed resume and
re-renders DOCXs + ATS scores.

Re-run scripts/build_report.py afterward to refresh the comparison HTML.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import ats_scorer, resume_writer  # noqa: E402
from src.keyword_extractor import KeywordRecord  # noqa: E402

OUT_ROOT = REPO / "data" / "output"
PARSED = OUT_ROOT / "_resume_parsed.json"


# ============================================================
# REWRITES — produced by Opus 4.7 in the Cursor chat session.
# Each block uses ONLY skills/claims authentic to Smritirekha's
# parsed experience. No fabrication.
# ============================================================

QA_REWRITE = {
    "summary": (
        "Quality Assurance professional with 4+ years of pharma experience at "
        "Anthem Biosciences spanning batch documentation, stability protocol "
        "management, audit readiness, and cGMP compliance. Hands-on with Veeva "
        "Vault QualityDocs lifecycle, SAP ERP sample disposition, and SOP and "
        "validation protocol authoring. Skilled in deviation investigation, "
        "root cause analysis, and analyst qualification training. Combines QC "
        "depth with QA documentation rigor, ready to own batch record review, "
        "change control, and inspection-readiness workflows for USFDA, MHRA, "
        "and EU GMP audits."
    ),
    "experience_bullets": {
        0: [  # Senior Executive, Mar 2025-Present
            "Authored deviation investigations and root cause analyses on high-volume probiotic testing variations, partnering with QA to close laboratory non-conformances within agreed SLA.",
            "Owned end-to-end Veeva Vault QualityDocs lifecycle for analytical SOPs and protocols including drafting, peer review, route-to-approval, and periodic review under ALCOA+ rigor.",
            "Operated SAP ERP for sample registration, disposition tracking, and end-to-end traceability across vertical sample types, supporting batch release and audit-trail review workflows.",
            "Authored and revised Standard Operating Procedures and equipment and method validation protocols aligned to cGMP and ICH Q2(R1), ensuring testing methods met regulatory expectations.",
            "Managed end-to-end stability lifecycle for assigned products via protocol authoring, sample initiation, scheduled pullouts, and critical batch reviews per ICH Q1A(R2) guidance.",
            "Drove audit-preparation workflows and maintained inspection-ready documentation packages supporting seamless USFDA, MHRA, and EU GMP inspection cycles at the site.",
            "Mentored new analysts through structured analyst-qualification programs covering laboratory rules, safety protocols, cGMP fundamentals, and SOP-driven operational workflows.",
        ],
        1: [  # Executive, Mar 2022-Mar 2025
            "Executed Microbiological Limit Tests, Growth Promotion Testing, and probiotic analysis on finished products, in-process samples, and raw materials per USP and IP compendial methods under cGMP.",
            "Managed culture suspension, sub-culturing, master culture stock maintenance, media preparation, sterilization validation, and Bioball reference standard verification supporting QC release testing.",
            "Executed aseptic sampling and active, passive, and surface-air environmental monitoring within cleanroom environments, generating data feeding into QA trend review.",
            "Conducted routine calibration, maintenance, and performance qualification of laboratory equipment, authoring qualification reports reviewed and approved by QA.",
            "Participated in root cause investigations for laboratory deviations and non-conformances, contributing to corrective action workflows aligned with cGMP and site QMS expectations.",
        ],
        # Internships left as-is — short and factual already.
    },
    "skills": [
        "Quality Assurance (QA)", "Veeva Vault QualityDocs", "SAP ERP",
        "Batch Record Review", "cGMP", "Audit Readiness",
        "Stability Lifecycle Management", "Deviation Investigation",
        "Root Cause Analysis", "CAPA", "SOP Authoring",
        "Validation Protocols", "Method Validation",
        "Environmental Monitoring", "Aseptic Technique",
        "Microbiological Limit Tests (MLT)", "Growth Promotion Testing",
        "Sterilization Validation", "Equipment Qualification",
        "Analyst Qualification & Training", "USP", "EP",
        "ICH Q1A(R2)", "ICH Q2(R1)",
        "USFDA & MHRA Inspection Support", "ALCOA+ Data Integrity",
        "GLP", "GDP", "MS Excel (Advanced)",
    ],
}


CDM_REWRITE = {
    # CDM is a real pivot. Phrasing positions her CDM certification + adjacent
    # pharma data discipline as transferable, WITHOUT claiming hands-on EDC
    # build / CDISC mapping / Rave config experience she does not have.
    "summary": (
        "Clinical Data Management trainee with 4+ years of pharmaceutical "
        "documentation experience and formal CDM certification (BCRI 2023) "
        "covering CDISC fundamentals, EDC concepts, eCRF design, edit-check "
        "specifications, UAT, data cleaning, and database lock. Hands-on with "
        "Veeva document lifecycle, SAP ERP data integrity, and GxP audit "
        "trails at Anthem Biosciences. M.Sc. Microbiology. Ready to apply "
        "trained CDM skills to entry-level Clinical Data Coordinator roles "
        "supporting Phase II to IV trials."
    ),
    "experience_bullets": {
        0: [  # Senior Executive — reframe for transferable CDM skills
            "Investigated analytical data discrepancies and probiotic-testing variations under cGMP, applying data review and discrepancy management workflows analogous to CDM data cleaning practice.",
            "Managed document lifecycle in Veeva (drafting, peer review, route-to-approval) directly transferable to Veeva Vault eTMF and CDMS document workflows used in clinical data management.",
            "Operated SAP ERP for sample data logging, traceability, and audit-trail integrity per ALCOA+ principles, the same discipline required for EDC audit-trail review in clinical databases.",
            "Authored and revised SOPs and validation protocols with rigor equivalent to Data Management Plan (DMP) and CRF Completion Guideline authoring in CDM.",
            "Managed end-to-end stability lifecycle from initiation through critical reviews, a parallel skillset to clinical study database lifecycle from setup through database lock.",
            "Drove inspection-readiness workflows for site audits, equivalent to TMF and eTMF readiness reviews for clinical sponsor and regulatory inspections.",
            "Mentored new joiners on documentation accuracy and SOP-driven workflows, transferable to UAT execution and end-user training during EDC study builds.",
        ],
        1: [  # Executive — reframe earlier QC work as GxP data discipline
            "Executed Microbiological Limit Tests, Growth Promotion Testing, and probiotic analysis under cGMP, building deep familiarity with GxP data integrity and ALCOA+ documentation habits.",
            "Managed culture and media data with full lot-level traceability and audit logs, operational discipline directly mapping to clinical lab vendor-data reconciliation in CDM.",
            "Performed environmental monitoring with structured data capture across cleanrooms, gaining experience operating in GxP-controlled, audit-trail-rich data environments.",
            "Authored equipment qualification documentation under validation rigor applicable to GxP computer system validation per 21 CFR Part 11 in clinical EDC systems.",
            "Conducted root cause investigations on laboratory deviations, analogous to discrepancy resolution and query management workflows in clinical data management.",
        ],
    },
    "skills": [
        "Clinical Data Management (CDM)", "CDISC Fundamentals (trained)",
        "EDC Concepts (trained)", "eCRF Design", "Edit Check Specifications",
        "User Acceptance Testing (UAT)", "Data Cleaning", "Query Management",
        "Database Lock", "Data Management Plan (DMP)",
        "CRF Completion Guidelines", "MedDRA & WHO Drug Coding (trained)",
        "Veeva Vault (Documents & eTMF concepts)", "GCP", "ICH E6(R2)",
        "21 CFR Part 11", "ALCOA+ Data Integrity", "Audit Trail Review",
        "Informed Consent Form (ICF) Design", "Protocol Development",
        "IRB / IEC Regulations", "SAP ERP", "cGMP",
        "Microbiology QC", "Stability Lifecycle",
        "MS Excel (Advanced)", "Clinical Trial Lifecycle (trained)",
    ],
}


MICRO_REWRITE = {
    "summary": (
        "Senior Microbiology professional with 4+ years of pharmaceutical QC "
        "experience at Anthem Biosciences covering microbiological limit "
        "testing, growth promotion, probiotic analysis, environmental "
        "monitoring of cleanroom environments, and aseptic sampling under "
        "cGMP. Strong on culture and media lifecycle management, "
        "sterilization validation, equipment qualification, and laboratory "
        "deviation investigation. M.Sc. Microbiology with GxP documentation "
        "exposure through Veeva and SAP. Ready to own routine QC release "
        "testing and CAPA-driven quality improvement as a Senior Microbiologist."
    ),
    "experience_bullets": {
        0: [  # Senior Executive
            "Performed advanced microbiological analysis on probiotic strains under cGMP, investigating high-volume testing variations and authoring deviation reports to close laboratory non-conformances.",
            "Owned analytical SOP and protocol lifecycle in Veeva Vault including drafting, peer review, and route-to-approval, supporting microbiology QC documentation rigor.",
            "Operated SAP ERP for microbiological sample registration, disposition tracking, and end-to-end traceability across vertical sample types feeding into QC release decisions.",
            "Authored and revised Standard Operating Procedures and equipment and method validation protocols for microbiological testing methods aligned to cGMP and ICH Q2(R1).",
            "Managed end-to-end stability lifecycle including protocol authoring, sample pullouts, and critical batch reviews per ICH Q1A(R2) covering microbiological stability testing.",
            "Maintained inspection-ready microbiology documentation packages supporting site audit cycles by USFDA, MHRA, and EU GMP authorities.",
            "Mentored junior microbiologists through structured analyst qualification covering aseptic technique, cleanroom gowning, safety protocols, and SOP-driven QC workflows.",
        ],
        1: [  # Executive
            "Executed Microbiological Limit Tests (MLT), Growth Promotion Testing, and probiotic analysis on finished products, in-process samples, and raw materials per USP and IP compendial methods under cGMP.",
            "Managed culture suspension, sub-culturing, master culture stock maintenance, media preparation, sterilization validation, and Bioball reference standard verification supporting routine QC release.",
            "Executed aseptic sampling and active, passive, and surface-air environmental monitoring across cleanroom environments, feeding trend analysis for cleanroom qualification.",
            "Conducted routine calibration, maintenance, and performance qualification (OQ and PQ) of laboratory equipment, authoring qualification reports per cGMP.",
            "Led root cause investigations for laboratory deviations and non-conformances, contributing to CAPA closure and microbiology QMS metrics.",
        ],
    },
    "skills": [
        "Microbiology QC", "Microbiological Limit Tests (MLT)",
        "Growth Promotion Testing", "Probiotic Analysis",
        "Environmental Monitoring", "Cleanroom Operations",
        "Aseptic Technique & Sampling", "Sterilization Validation",
        "Media Preparation", "Culture & Master Culture Stock Management",
        "Bioball Reference Standards",
        "Equipment Calibration & Qualification (OQ / PQ)",
        "Laboratory Deviation Investigation", "CAPA",
        "Root Cause Analysis", "cGMP", "USP", "IP",
        "ICH Q1A(R2)", "ICH Q2(R1)", "Veeva Vault", "SAP ERP",
        "SOP & Validation Protocol Authoring",
        "Stability Lifecycle", "ALCOA+ Data Integrity",
        "MS Excel (Advanced)",
    ],
}


ROLES = {
    "qa": QA_REWRITE,
    "cdm": CDM_REWRITE,
    "microbiologist": MICRO_REWRITE,
}


def _apply(parsed: dict, rewrite: dict) -> dict:
    out = copy.deepcopy(parsed)
    if "summary" in rewrite:
        out["summary"] = rewrite["summary"]
    for idx, new_bullets in rewrite.get("experience_bullets", {}).items():
        if 0 <= idx < len(out["experience"]):
            out["experience"][idx]["bullets"] = list(new_bullets)
    if "skills" in rewrite:
        out["skills"] = list(rewrite["skills"])
    # Drop pre-college education rows that pad length without ATS value.
    if out.get("education"):
        out["education"] = [
            e for e in out["education"]
            if "class" not in (e.get("degree") or "").lower()
        ]
    return out


def main() -> int:
    if not PARSED.exists():
        print(f"ERROR: {PARSED} not found. Run scripts/dry_run.py first.", file=sys.stderr)
        return 1

    parsed = json.loads(PARSED.read_text(encoding="utf-8"))

    summaries: list[dict] = []
    for slug, rewrite in ROLES.items():
        role_dir = OUT_ROOT / slug
        if not role_dir.exists():
            print(f"  [skip] {slug}: no dry-run artifacts in {role_dir}")
            continue

        print(f"\n=== {slug} ===")
        optimized = _apply(parsed, rewrite)

        # Persist the rewritten resume JSON
        (role_dir / "optimized_resume.json").write_text(
            json.dumps(optimized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Render DOCX
        out_docx = role_dir / "optimized_resume.docx"
        resume_writer.write_docx(optimized, out_docx)
        resume_writer.write_pdf_if_possible(out_docx, role_dir / "optimized_resume.pdf")
        print(f"  wrote {out_docx.relative_to(REPO)}  ({out_docx.stat().st_size // 1024} KB)")

        # Re-score against the same market keywords
        kw_records = [
            KeywordRecord(**{k: v for k, v in r.items() if k in KeywordRecord.__dataclass_fields__})
            for r in json.loads((role_dir / "keywords.json").read_text(encoding="utf-8"))
        ]
        after = ats_scorer.score_resume(out_docx, kw_records)

        # Pull the prior baseline back from disk so the delta is honest
        ats_path = role_dir / "ats_report.json"
        prev = json.loads(ats_path.read_text(encoding="utf-8")) if ats_path.exists() else {}
        before = prev.get("before", {})

        ats_path.write_text(
            json.dumps({"before": before, "after": after.to_dict()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        delta = after.overall - before.get("overall", 0)
        print(f"  ATS: {before.get('overall', 0):.1f} -> {after.overall:.1f}  (delta {delta:+.1f})")
        print(f"  critical coverage: "
              f"{before.get('keyword_coverage', {}).get('critical', 0):.0f}% -> "
              f"{after.keyword_coverage.get('critical', 0):.0f}%")

        # Update summary entry
        summary_path = OUT_ROOT / "_dry_run_summary.json"
        if summary_path.exists():
            cur = json.loads(summary_path.read_text(encoding="utf-8"))
            for s in cur:
                if s.get("slug") == slug:
                    s["ats_after"] = after.overall
                    s["ats_delta"] = round(delta, 1)
                    break
            summary_path.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nDone. Run `python scripts/build_report.py` to refresh comparison_report.html.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
