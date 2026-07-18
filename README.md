# Resume Optimizer Pipeline

End-to-end Jupyter pipeline that:

1. Ingests a resume (PDF or DOCX)
2. Fetches live job descriptions from **JSearch** (LinkedIn + Indeed + Google Jobs aggregator) **and JobSpy** (Naukri + LinkedIn + Indeed direct — critical for India pharma)
3. Drops ghost / dead postings via an engagement filter
4. Ranks JDs by salary, semantic fit, and recency
5. Mines critical keywords from the top JDs
6. Uses Gemini 2.0 Flash to rewrite an ATS-optimized master resume
7. For each top-N job, generates a **tailored resume + cover letter + pre-filled screening answers**
8. Logs everything to a **Google Sheets tracker** as `status=queued`
9. Walks an **assist-mode apply queue** (opens artifact folder + apply URL; user clicks Submit)
10. Watches Gmail and **auto-advances the tracker** when recruiters reply (viewed → screening → offer / rejected)

Default target market: Senior QC Microbiology in Indian pharma hubs. Edit [`config/preferences.yaml`](config/preferences.yaml) for anything else.

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

# 4. (optional) edit config/preferences.yaml for your role / locations / CTC
# 5. (optional) set up the tracker + email watcher — see "Tracker setup" below

# 6. run the notebook
jupyter notebook resume_optimizer.ipynb
```

## What you get in `data/output/`

| File | Purpose |
|---|---|
| `optimized_resume.docx` | ATS-clean master resume (upload this to portals) |
| `optimized_resume.pdf`  | Human-readable companion (recruiter email attachments) |
| `applications/<company>_<role>/resume.docx` | Tailored resume for that job |
| `applications/<company>_<role>/cover_letter.docx` | Per-job cover letter |
| `applications/<company>_<role>/screening_answers.json` | Pre-filled screening Qs (CTC, notice, audits, techniques) |
| `applications.json` | Local tracker fallback (used if Sheets is not configured) |
| `match_report.html` | Ranked job table, salary distribution, keyword coverage, before/after ATS scores |
| `jobs.json` | Raw ranked job list with salary, location, link |

## Repo layout

```
resume_optimizer.ipynb     # main pipeline notebook
config/preferences.yaml    # role, locations, CTC, daily caps, filters
src/                       # reusable modules
  resume_parser.py         # PDF/DOCX -> dict
  job_fetcher.py           # JSearch client with disk cache
  jobspy_fetcher.py        # Naukri + LinkedIn + Indeed via python-jobspy
  engagement_filter.py     # drops stale / crowded / dead postings
  ranker.py                # salary + embedding + recency scoring
  keyword_extractor.py     # KeyBERT + Gemini classification
  llm.py                   # Gemini wrapper
  resume_writer.py         # dict -> ATS-clean DOCX (master + per-job tailoring)
  cover_letter.py          # per-job cover letter generator
  screening_qs.py          # pre-fills CTC / notice / techniques / audits
  tracker.py               # Google Sheets tracker (with local JSON fallback)
  apply_queue.py           # assist-mode browser opener + status prompts
  email_watcher.py         # Gmail API + Gemini classifier -> tracker updates
  ats_scorer.py            # coverage + format validation
prompts/                   # editable prompt templates
data/
  input/                   # drop your resume here
  jobs_cache/              # JSON cache, saves API quota
  output/                  # generated artifacts + per-job folders
secrets/                   # OAuth/service-account JSONs (gitignored)
```

## ATS rules enforced

- DOCX output (most ATS parses DOCX more reliably than PDF)
- Standard headings: *Professional Summary*, *Work Experience*, *Skills*, *Education*, *Certifications*
- Single column, no tables, no text boxes, no headers/footers, no images
- Arial 11pt, dates as `MMM YYYY`
- Skills ordered so critical keywords appear first (most ATS truncate after ~10)
- No fabrication: the rewrite + tailor prompts explicitly forbid inserting skills, pharmacopeia chapters, or audit experience the candidate does not actually have.

## Tracker setup (Google Sheets)

The pipeline writes every queued/applied job to a Google Sheet so you can review on mobile and edit notes from anywhere.

1. Create a blank Google Sheet, copy its ID from the URL (`https://docs.google.com/spreadsheets/d/<ID>/edit`).
2. Set `GOOGLE_SHEET_ID=<ID>` in `.env`.
3. In Google Cloud Console: **APIs & Services → Credentials → Create credentials → Service account**. Add a JSON key, save it to `secrets/service_account.json`, set `GOOGLE_SERVICE_ACCOUNT_JSON` to that path.
4. Enable the **Google Sheets API** and **Google Drive API** for the project.
5. Share the Sheet with the service-account email (in the JSON, `client_email`) as **Editor**.
6. The notebook's "Push to tracker" cell will create the `applications` worksheet on first run.

If you skip this setup, the pipeline silently falls back to `data/output/applications.json` (same schema, same downstream code).

## Apply queue (assist mode)

```python
from src import tracker as tracker_mod, apply_queue, config as cfg
prefs = cfg.load_preferences()
TRACKER = tracker_mod.open_tracker(prefs)
apply_queue.run_queue(TRACKER, daily_cap=12)
```

For each queued row (up to `daily_apply_cap`):

1. Opens the job's artifact folder in Finder/Explorer so you can grab the tailored resume + cover letter.
2. Opens the apply URL in your default browser.
3. Prints the screening-answer cheat sheet inline.
4. Prompts `[s]ubmitted / [k]eep queued / [d]rop / [q]uit`.
5. On `s`, updates the Sheet to `status=applied`.

**This module never auto-submits anything.** LinkedIn TOS-safe, account-ban-safe. You stay in control; the pipeline removes the toil.

## Email watcher setup (Gmail API, read-only)

The watcher polls Gmail every 15 minutes, classifies new messages from companies you've applied to using Gemini, and auto-advances the tracker (`viewed` → `screening` → `interviewing` → `offer` / `rejected`).

1. Google Cloud Console: **APIs & Services → Library → enable Gmail API**.
2. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON to `secrets/gmail_client.json`.
3. Set `GMAIL_OAUTH_CLIENT_JSON=./secrets/gmail_client.json` and `GMAIL_TOKEN_JSON=./secrets/gmail_token.json` in `.env`.
4. First run of the notebook's email-watcher cell pops a browser for one-time consent (read-only scope). The token is cached locally and refreshed automatically.
5. To run the watcher continuously in a separate terminal:
   ```bash
   python -m src.email_watcher
   ```

The watcher will **never advance the tracker backwards** (e.g. it won't move an `offer` back to `screening`).

## Daily routine

1. `jupyter notebook resume_optimizer.ipynb` → run all cells. (The JD cache means re-runs cost no API quota for ~24h.)
2. Review the ranked table; veto anything obviously wrong by editing the tracker Sheet directly (set `status=skipped`).
3. Run the apply-queue cell → up to 12 browser tabs open one-by-one. Each shows the staged folder + a screening-answer cheat sheet. Click Submit on the portal, press `s` in the notebook.
4. Leave the email-watcher cell running (or `python -m src.email_watcher` in a separate shell). The Sheet auto-updates as recruiters reply.
5. Open the Sheet on mobile to see the status flow.

## Honest caveats

- **JSearch free tier = 200 req/mo.** Cached on disk; a typical run = 5–10 requests.
- **JobSpy LinkedIn rate-limits hard around the 10th page from one IP.** Naukri + Indeed are the workhorses for QC microbiology in India.
- **Naukri descriptions are sometimes truncated**; the keyword miner still works from snippets but tailoring quality improves when you set `linkedin_fetch_description=True` in `jobspy_fetcher.JobSpyQuery` and accept the slowness.
- **No fabrication.** Lying to ATS gets candidates rejected at interview — interview panels for QC roles probe pharmacopeia chapters, audits, and instruments directly.
- **Gemini free tier rate limits** apply (~15 RPM, 1M TPD as of 2026). Pipeline batches and retries.
- **No auto-submit on LinkedIn / Naukri.** This pipeline deliberately uses assist mode to stay TOS-safe.
- **Gmail watcher** uses read-only OAuth scope. Token is stored locally only. Never sent to any third party.
