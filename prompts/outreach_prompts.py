"""Cold outreach prompts using PAS and AIDA frameworks."""

OUTREACH_SYSTEM_PROMPT = """You are an elite B2B copywriter for personalized cold outreach.

You write emails and LinkedIn pitches that feel researched, human, and concise.
Never use spammy language, fake urgency, or generic flattery.

Frameworks (apply the one requested):
- PAS: Problem → Agitate → Solve
- AIDA: Attention → Interest → Desire → Action

Rules:
- Email body ≤ 130 words
- Specific observation tied to a pain point or tech signal
- Soft CTA (reply or 15-min chat)
- LinkedIn pitch ≤ 60 words, conversational

Respond with ONLY valid JSON:
{
  "subject": "<short, specific subject>",
  "body": "<plain-text email with greeting and sign-off>",
  "linkedin_pitch": "<short LinkedIn connection/InMail style note>"
}
"""


def build_outreach_user_prompt(
    company_name: str,
    contact_name: str,
    contact_title: str,
    website: str,
    industry: str,
    location: str,
    analysis_summary: str,
    pain_points: str,
    tech_stack: str,
    framework: str,
    from_name: str,
    from_company: str,
) -> str:
    """Build the user message for the copywriter LLM call."""
    greeting = contact_name.strip() or "there"
    title_line = f" ({contact_title})" if contact_title else ""
    return f"""Draft personalized outreach using the {framework} framework.

Sender: {from_name} at {from_company}
Recipient: {greeting}{title_line}
Company: {company_name}
Website: {website}
Industry: {industry or "unknown"}
Location: {location or "unknown"}
Tech signals: {tech_stack}

Analysis summary:
{analysis_summary or "N/A"}

Pain points:
{pain_points or "N/A"}

Return the JSON object with subject, body, and linkedin_pitch now.
"""
