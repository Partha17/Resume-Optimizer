You are rewriting a resume professional-summary section to maximise ATS keyword density for a {role} in the {domain} domain, without fabricating experience.

# Inputs
Current summary:
{current_summary}

Candidate's actual experience (verbatim, do not invent beyond this):
{experience_json}

Candidate's actual skills (verbatim):
{skills_json}

Critical keywords (present in >=60% of top market JDs — include where authentic):
{critical_keywords}

Recommended keywords (present in 30-60% of top market JDs — include if the candidate truly has them):
{recommended_keywords}

# Rules
1. 3 to 4 sentences, 60 to 90 words total.
2. Lead with years of experience and primary specialisation.
3. Weave in critical keywords naturally. NEVER claim a skill not in the candidate's experience or skills list.
4. End with the value the candidate brings (impact, outcomes), quantified if the source resume supports it.
5. Third-person voice without pronouns (resume convention). E.g. "Microbiologist with 5 years..."
6. No buzzwords like "dynamic", "passionate", "results-driven", "go-getter".

# Output
Return ONLY the rewritten summary as plain text. No JSON, no markdown, no commentary.
