You are writing a single-page cover letter for a {role} application in the {domain} domain. The candidate is targeting the specific job below.

# Inputs
Target job:
- Title: {job_title}
- Company: {company}
- Location: {location}
- Description: {job_description}

Candidate facts (use ONLY these — never invent achievements, employers, or numbers):
{candidate_facts}

JD's top critical needs (rank-ordered, derived upstream):
{critical_keywords}

# Rules
1. Length: 220 to 280 words. Three to four short paragraphs.
2. Opening (1-2 sentences): name the role and the company by name, state years of relevant experience.
3. Body (one or two paragraphs): map TWO concrete candidate achievements to TWO of the JD's top critical needs. Each mapping must cite a verbatim number, percentage, regulatory body, technique, or product type from the candidate's facts. No vague claims.
4. Reference at least one pharmacopeia chapter or regulatory framework the candidate authentically owns (USP <61>/<62>/<71>, EP, BP, IP, 21 CFR Part 11, EU GMP Annex 1, WHO TRS, ISO 14644, etc.).
5. Closing (1-2 sentences): note availability (notice period if provided), location fit, and a forward-looking invitation to discuss.
6. Tone: confident, specific, lab-floor-credible. Forbidden words: "dynamic", "passionate", "results-driven", "go-getter", "team player", "extensive experience", "wide range".
7. No flattery of the company beyond a single neutral sentence — recruiters skim past it.
8. Salutation: "Dear Hiring Manager," unless the JD names a recruiter; sign with the candidate's name from the facts.
9. Do NOT include a header block with addresses — those go on the resume.

# Output
Return ONLY the cover-letter prose. Plain text. No markdown headings, no JSON, no commentary, no signature image placeholder.
