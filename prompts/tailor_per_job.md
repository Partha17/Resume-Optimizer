You are tailoring a master resume to ONE specific job opening. The goal is to nudge the ATS coverage score above 90% without fabrication.

# Inputs
Target job:
- Title: {job_title}
- Company: {company}
- Location: {location}
- Description: {job_description}

Candidate master resume (already optimised generally):
{resume_json}

Critical keywords for this single JD (must appear in resume if the candidate authentically has them):
{job_keywords}

# Rules
1. Modify ONLY: `summary`, individual `experience.bullets`, and the order/wording of `skills`. Do not add or remove experience entries, education, or certifications.
2. The summary should mention the target role/title and 2-3 critical keywords from this JD.
3. Each existing bullet may be lightly rephrased to surface a JD-critical keyword the candidate truly has. Do NOT add new bullets and do NOT delete existing ones.
4. Skills list: keep all existing skills, reorder so the JD-critical ones come first, append any JD keywords that the candidate clearly demonstrated in their experience but had not listed explicitly. Never append a skill with no evidence in the experience section.
5. Preserve every number, date, and proper noun from the input verbatim.
6. For QC / microbiology JDs, surface the exact pharmacopeia chapters (e.g. USP <61>, USP <62>, USP <71>, EP, BP, IP) and regulatory bodies (USFDA, WHO-GMP, EU GMP Annex 1, MHRA, TGA, CDSCO) that the candidate AUTHENTICALLY owns — match against the resume's bullets, certifications, and audits-faced. Never insert a chapter or regulator the resume doesn't already evidence; interview screens will catch the lie immediately.

# Output
Return the FULL resume JSON with the modifications applied, matching the exact schema of the input. No commentary, no fences.
