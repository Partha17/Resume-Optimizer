Extract the salary range from this job description. Return JSON only.

# Input
{job_description}

# Output schema
{{
  "currency": "INR" | "USD" | "EUR" | "GBP" | "SGD" | "" ,
  "min_lpa": <number or null>,
  "max_lpa": <number or null>,
  "period": "annual" | "monthly" | "hourly" | "",
  "raw_match": "<the exact substring you used>"
}}

# Rules
- Convert to "lakhs per annum" (LPA) if the source is INR.
- If currency is non-INR, leave the numbers as the annual amount in the original currency and set `currency` accordingly; the pipeline will convert downstream.
- If the JD says "competitive", "as per industry", "best in industry", or shows no number, return both nulls.
- If only a single number is given (e.g. "12 LPA"), set both min_lpa and max_lpa to that number.

Return ONLY the JSON object, no commentary, no fences.
