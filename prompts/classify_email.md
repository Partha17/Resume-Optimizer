You are classifying ONE inbound recruiter email for a job-application tracker.

# Inputs
Email metadata:
- From: {from_address}
- Subject: {subject}
- Received at (UTC): {received_at}

Email body (first 4000 chars, plain text):
{body}

Known applied companies (lowercased substrings — at least one of these usually appears in From, Subject, or body):
{known_companies}

# Output schema
Return ONLY a JSON object (no commentary, no fences):
{{
  "label": "<one of: viewed | screening | interviewing | offer | rejected | irrelevant>",
  "matched_company": "<lowercased substring from known_companies that this email relates to, or ''>",
  "confidence": <number 0.0-1.0>,
  "evidence_snippet": "<<=200 char verbatim quote from the email that drove the label>",
  "next_action_suggestion": "<<=120 char suggestion for the candidate, or ''>"
}}

# Label definitions
- viewed: Automated 'your application has been received' or 'we are reviewing your profile'.
- screening: Recruiter asking for screening info (CTC, notice period, willing to relocate, availability for a call), OR a phone-screen invitation.
- interviewing: Technical/managerial round invite, panel scheduling, or assignment dispatch.
- offer: Offer letter attached/mentioned, compensation discussion, BGV/joining formalities, or congratulations on selection.
- rejected: 'We will not be moving forward', 'position has been filled', 'we have selected other candidates', etc.
- irrelevant: Marketing newsletter from a job board, unrelated transactional email, OR no clear match against ``known_companies``.

# Rules
1. Prefer the strongest applicable label: offer > interviewing > screening > viewed > rejected > irrelevant. Rejection only wins if explicit.
2. If matched_company is empty, label MUST be ``irrelevant``.
3. Confidence: 0.9+ when the evidence quote contains a label-defining phrase verbatim; 0.5-0.8 for soft matches; below 0.5 only when guessing.
4. Never invent quotes — ``evidence_snippet`` must be a substring of the email body.
