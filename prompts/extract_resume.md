You are an expert resume parser. Convert the raw resume text below into structured JSON.

# Rules
- Preserve the candidate's original wording verbatim wherever possible. Do NOT rewrite or embellish.
- If a field is missing in the source, return an empty string or empty list. Do NOT fabricate.
- Dates should be normalized to the form "MMM YYYY" (e.g. "Jan 2022") when day is missing; keep "Present" for current roles.
- For each experience entry, split achievement lines into the `bullets` array. Trim leading bullet characters ("-", "*", "•").

# Output schema (return JSON matching exactly this shape)
{{
  "contact": {{
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": "",
    "portfolio": ""
  }},
  "summary": "",
  "experience": [
    {{
      "title": "",
      "company": "",
      "location": "",
      "start_date": "",
      "end_date": "",
      "bullets": []
    }}
  ],
  "skills": [],
  "education": [
    {{ "degree": "", "institution": "", "location": "", "start_date": "", "end_date": "", "details": "" }}
  ],
  "certifications": [
    {{ "name": "", "issuer": "", "date": "" }}
  ],
  "projects": [
    {{ "name": "", "description": "", "bullets": [] }}
  ],
  "publications": [],
  "languages": [],
  "awards": []
}}

# Raw resume text
{resume_text}

Return ONLY the JSON object, no commentary, no markdown fences.
