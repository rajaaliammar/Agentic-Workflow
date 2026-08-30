"""Analyzer agent — website audit & pain-point detection."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import get_settings
from core.state import LeadState, LeadStatus
from prompts.analyzer_prompts import ANALYZER_SYSTEM_PROMPT, build_analyzer_user_prompt
from utils.helpers import extract_json_block, truncate
from utils.logger import logger


def _get_llm() -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        api_key=settings.openai_api_key.get_secret_value() or None,
    )


def _analyze_one(lead: dict[str, Any], llm: ChatOpenAI) -> dict[str, Any]:
    content = lead.get("scraped_content") or ""
    if not content.strip():
        return {
            **lead,
            "status": LeadStatus.DISQUALIFIED.value,
            "analysis_summary": "",
            "pain_points": [],
            "tech_stack": [],
            "qualification_reason": "No scraped content",
        }

    user_prompt = build_analyzer_user_prompt(
        company_name=lead.get("company_name") or "Unknown",
        website=lead.get("website") or "",
        industry=lead.get("industry") or "",
        location=lead.get("location") or "",
        scraped_content=truncate(content, 12_000),
    )

    response = llm.invoke(
        [
            SystemMessage(content=ANALYZER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    raw = response.content if isinstance(response.content, str) else str(response.content)
    data = extract_json_block(raw) or {}

    if not data:
        logger.warning("Analyzer non-JSON for {}; using fallback", lead.get("company_name"))
        data = {
            "summary": truncate(raw, 500),
            "tech_stack": [],
            "pain_points": [
                {
                    "title": "Unstructured analysis",
                    "description": truncate(raw, 300),
                    "severity": "medium",
                    "evidence": "",
                }
            ],
            "contact_hints": {},
            "suggested_score": 5.0,
        }

    hints = data.get("contact_hints") or {}
    updated = {
        **lead,
        "analysis_summary": str(data.get("summary") or ""),
        "tech_stack": list(data.get("tech_stack") or []),
        "pain_points": list(data.get("pain_points") or []),
        "status": LeadStatus.ANALYZED.value,
        "metadata": {
            **(lead.get("metadata") or {}),
            "suggested_score": data.get("suggested_score"),
        },
    }
    if isinstance(hints, dict):
        if hints.get("email") and not updated.get("contact_email"):
            updated["contact_email"] = hints["email"]
        if hints.get("name") and not updated.get("contact_name"):
            updated["contact_name"] = hints["name"]
        if hints.get("title") and not updated.get("contact_title"):
            updated["contact_title"] = hints["title"]

    return updated


def run_analyzer(state: LeadState) -> dict[str, Any]:
    """LangGraph node body: audit scraped sites and extract pain points."""
    leads = state.get("leads") or []
    messages: list[str] = []
    errors: list[str] = []

    targets = [
        lead
        for lead in leads
        if lead.get("status") == LeadStatus.DISCOVERED.value and lead.get("scraped_content")
    ]
    messages.append(f"Analyzing {len(targets)} lead(s)")
    logger.info("Analyzer agent | targets={}", len(targets))

    if not targets:
        return {
            "leads": leads,
            "messages": messages + ["No discovered leads with content to analyze"],
            "step": "analysis",
        }

    llm = _get_llm()
    analyzed: list[dict[str, Any]] = []
    target_keys = {
        (t.get("website") or t.get("company_name") or "").lower() for t in targets
    }

    for lead in leads:
        key = (lead.get("website") or lead.get("company_name") or "").lower()
        if key not in target_keys:
            analyzed.append(lead)
            continue
        try:
            result = _analyze_one(lead, llm)
            analyzed.append(result)
            pp_count = len(result.get("pain_points") or [])
            messages.append(f"Analyzed {result.get('company_name')} — {pp_count} pain point(s)")
        except Exception as exc:
            logger.exception("Analysis failed for {}", lead.get("company_name"))
            errors.append(f"Analyze failed for {lead.get('company_name')}: {exc}")
            analyzed.append({**lead, "status": LeadStatus.FAILED.value})

    return {
        "leads": analyzed,
        "messages": messages,
        "errors": errors,
        "step": "analysis",
    }
