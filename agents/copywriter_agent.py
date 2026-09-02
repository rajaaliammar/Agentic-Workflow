"""Copywriter agent — personalized cold email & LinkedIn pitch generator."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_settings
from core.state import LeadState, LeadStatus
from prompts.outreach_prompts import (
    OUTREACH_SYSTEM_PROMPT,
    build_outreach_user_prompt,
)
from utils.helpers import extract_json_block, format_pain_points, invoke_llm
from utils.logger import logger


def _draft_one(lead: dict[str, Any], framework: str) -> dict[str, Any]:
    settings = get_settings()
    user_prompt = build_outreach_user_prompt(
        company_name=lead.get("company_name") or "there",
        contact_name=lead.get("contact_name") or "",
        contact_title=lead.get("contact_title") or "",
        website=lead.get("website") or "",
        industry=lead.get("industry") or "",
        location=lead.get("location") or "",
        analysis_summary=lead.get("analysis_summary") or "",
        pain_points=format_pain_points(lead.get("pain_points") or []),
        tech_stack=", ".join(lead.get("tech_stack") or []) or "unknown",
        framework=framework,
        from_name=settings.outreach_from_name,
        from_company=settings.outreach_from_company,
    )

    response = invoke_llm(
        [
            SystemMessage(content=OUTREACH_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ],
        temperature=max(settings.openai_temperature, 0.45),
    )
    raw = response.content if isinstance(response.content, str) else str(response.content)
    data = extract_json_block(raw) or {}

    subject = str(data.get("subject") or "Quick idea for your team")
    body = str(data.get("body") or raw)
    linkedin = str(data.get("linkedin_pitch") or "")

    return {
        **lead,
        "email_subject": subject,
        "email_body": body,
        "linkedin_pitch": linkedin,
        "outreach_framework": framework,
        "status": LeadStatus.DRAFTED.value,
        "hitl_status": "pending",
    }


def run_copywriter(state: LeadState) -> dict[str, Any]:
    """LangGraph node body: draft PAS/AIDA emails for verified leads."""
    settings = get_settings()
    framework = (state.get("outreach_framework") or settings.outreach_framework or "PAS").upper()
    min_score = settings.min_qualification_score
    leads = state.get("leads") or []
    messages: list[str] = []
    errors: list[str] = []

    targets = [
        lead
        for lead in leads
        if lead.get("status") == LeadStatus.VERIFIED.value
        and float(lead.get("qualification_score") or 0) >= min_score
    ]
    messages.append(f"Copywriting {len(targets)} verified lead(s) | framework={framework}")
    logger.info("Copywriter agent | targets={} framework={}", len(targets), framework)

    if not targets:
        return {
            "leads": leads,
            "messages": messages + ["No verified leads for copywriting"],
            "step": "copywriting",
        }

    updated: list[dict[str, Any]] = []
    target_keys = {
        (t.get("website") or t.get("company_name") or "").lower() for t in targets
    }

    for lead in leads:
        key = (lead.get("website") or lead.get("company_name") or "").lower()
        if key not in target_keys:
            updated.append(lead)
            continue
        try:
            drafted = _draft_one(lead, framework)
            updated.append(drafted)
            messages.append(f"Drafted outreach for {drafted.get('company_name')}")
        except Exception as exc:
            logger.exception("Copywriting failed for {}", lead.get("company_name"))
            errors.append(f"Copywrite failed for {lead.get('company_name')}: {exc}")
            updated.append({**lead, "status": LeadStatus.FAILED.value})

    return {
        "leads": updated,
        "messages": messages,
        "errors": errors,
        "step": "copywriting",
    }
