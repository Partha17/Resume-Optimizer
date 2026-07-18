You are pre-filling answers to common Indian-pharma screening questions for an application to the role below. The answers must be grounded ONLY in the candidate facts and the explicit candidate preferences. If a fact is not available, return an empty string for that field — never fabricate.

# Inputs
Target job:
- Title: {job_title}
- Company: {company}
- Location: {location}
- Description: {job_description}

Candidate facts (verbatim source of truth):
{candidate_facts}

Candidate explicit preferences:
{candidate_preferences}

# Output schema
Return ONLY a JSON object with exactly these keys (no extras, no commentary, no fences):
{{
  "years_of_total_experience": <number or "">,
  "years_of_qc_micro_experience": <number or "">,
  "current_ctc_lpa": <number or "">,
  "expected_ctc_lpa": <number or "">,
  "notice_period_days": <integer or "">,
  "current_location": "<string>",
  "willing_to_relocate_to_job_location": <true|false|"">,
  "earliest_join_date": "<YYYY-MM-DD or ''>",
  "highest_qualification": "<string>",
  "regulatory_audits_faced": ["<USFDA>", "<EU GMP>", "..."],
  "core_techniques": ["<sterility testing>", "<environmental monitoring>", "..."],
  "instruments_handled": ["<VITEK>", "<MALDI-TOF>", "..."],
  "people_managed": <integer or "">,
  "why_this_role": "<2 sentences, 30-50 words, grounded in facts and JD overlap>",
  "open_to_shift_work": <true|false|"">,
  "screening_red_flags": ["<list any gaps the recruiter will probe e.g. 'employment gap 2019-2020', else empty>"]
}}

# Rules
1. Numeric fields: use the candidate facts; if missing, output an empty string "". Never guess.
2. `regulatory_audits_faced`, `core_techniques`, `instruments_handled`: include ONLY items that appear (case-insensitive substring or canonical match) somewhere in the candidate's experience bullets, skills, or summary.
3. `why_this_role`: cite one concrete candidate strength AND one JD priority. No flattery.
4. `screening_red_flags`: be honest. Surface obvious gaps so the candidate can prepare answers. Leave the array empty if there are none.
5. The JSON object must be parseable by `json.loads`. No trailing commas, no comments.
