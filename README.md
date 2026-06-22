# Resume Optimizer Pipeline

End-to-end Jupyter pipeline that:

1. Ingests a resume (PDF or DOCX)
2. Fetches live job descriptions from JSearch (LinkedIn + Indeed + Google Jobs + ZipRecruiter aggregator)
3. Ranks JDs by salary, semantic fit, and recency
4. Mines critical keywords from the top JDs
5. Uses Gemini 2.0 Flash to rewrite an ATS-optimized resume
6. Scores the rewrite for keyword coverage and ATS-format compliance

Target market is configurable; default is Bangalore / Remote / Hybrid in India.

## Quick start

```bash
# 1. install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure
cp .env.example .env
# edit .env, add GEMINI_API_KEY (free at https://aistudio.google.com/app/apikey)
# and RAPIDAPI_KEY (free JSearch tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)

# 3. drop your resume
cp /path/to/your_resume.pdf data/input/resume.pdf
#    (also accepts .docx)

# 4. run the notebook
jupyter notebook resume_optimizer.ipynb
```

## What you get in `data/output/`

| File | Purpose |
|---|---|
| `optimized_resume.docx` | ATS-clean master resume (upload this to portals) |
| `optimized_resume.pdf`  | Human-readable companion (recruiter email attachments) |
| `tailored_<company>_<role>.docx` | Per-job variants for top hits where coverage < 90% |
| `match_report.html` | Ranked job table, salary distribution, keyword coverage, before/after ATS scores |
| `jobs.json` | Raw ranked job list with salary, location, link |

## Repo layout

```
resume_optimizer.ipynb     # main pipeline notebook
src/                       # reusable modules
  resume_parser.py         # PDF/DOCX -> dict
  job_fetcher.py           # JSearch client with disk cache
  ranker.py                # salary + embedding + recency scoring
  keyword_extractor.py     # KeyBERT + Gemini classification
  llm.py                   # Gemini wrapper
  resume_writer.py         # dict -> ATS-clean DOCX
  ats_scorer.py            # coverage + format validation
prompts/                   # editable prompt templates
data/
  input/                   # drop your resume here
  jobs_cache/              # JSON cache, saves API quota
  output/                  # generated artifacts
```

## ATS rules enforced

- DOCX output (most ATS parses DOCX more reliably than PDF)
- Standard headings: *Professional Summary*, *Work Experience*, *Skills*, *Education*, *Certifications*
- Single column, no tables, no text boxes, no headers/footers, no images
- Arial 11pt, dates as `MMM YYYY`
- Skills ordered so critical keywords appear first (most ATS truncate after ~10)
- No fabrication: the rewrite prompt explicitly forbids inserting skills the candidate does not have

## Honest caveats

- **JSearch free tier = 200 req/mo.** Cached on disk; a typical run = 5–10 requests.
- **LinkedIn / Naukri direct scraping is omitted** — TOS-hostile and brittle. JSearch indexes most postings anyway. Adzuna India is an easy free fallback if biotech coverage feels thin.
- **No keyword stuffing.** Lying to ATS gets candidates rejected at interview.
- **Gemini free tier rate limits** apply (~15 RPM, 1M TPD as of 2026). Pipeline batches and retries.
