You are rewriting the achievement bullets of ONE work-experience entry for ATS optimisation.

# Inputs
Role: {role} in {domain}

Current experience entry:
{experience_json}

Critical keywords (only inject where authentic to this role):
{critical_keywords}

Recommended keywords (only inject where authentic):
{recommended_keywords}

# Rules
1. Output exactly the same number of bullets as the input (or up to 6 if the input has more).
2. Each bullet: action verb in past tense (or present tense if role is current), 16-28 words, single line.
3. STAR-flavoured: situation/task implied, action explicit, result quantified.
4. Preserve all numbers, percentages, dollar/INR amounts, sample counts, throughput etc. exactly from the source.
5. Inject a critical keyword ONLY if the original bullet plausibly involved that skill — no inference, no fabrication.
6. No first-person pronouns. Start with strong verbs: "Executed", "Validated", "Authored", "Reduced", "Spearheaded", "Engineered", etc.
7. Avoid clichés: "responsible for", "duties included", "team player", "passionate".

# Output
Return a JSON array of strings (the new bullets) in the same order as the input. No commentary, no fences.
