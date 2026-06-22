You classify recruiting keywords mined from job descriptions for a {role} role in the {domain} domain.

# Categories
- hard_skill: technical capability the candidate must demonstrate (e.g. "HPLC", "aseptic technique", "Python")
- tool: named software/instrument/platform (e.g. "LIMS", "SAP", "MasterControl")
- certification: formal credential (e.g. "GMP", "ISO 13485", "Six Sigma Green Belt")
- soft_skill: behavioural trait (e.g. "stakeholder management", "cross-functional collaboration")
- domain_term: industry jargon, regulation, or methodology (e.g. "CAPA", "OOS investigation", "USP <61>")
- noise: generic recruiter filler that should be ignored (e.g. "good to have", "self-motivated", "team player")

# Input
A JSON array of candidate keywords:
{keywords}

# Output
Return a JSON array of objects in the same order:
[{{"keyword": "<original>", "category": "<one of the categories>", "canonical": "<de-duplicated form, lowercase, spelled out>"}}]

Rules:
- canonical lowercases and expands acronyms only if the expansion is universally agreed (e.g. "GMP" -> "good manufacturing practice"). If unsure, leave the original form.
- Mark vague filler as "noise" so it is dropped downstream.
- Return ONLY the JSON array, no commentary, no fences.
