"""TypedDict & Pydantic models for Lead State & Graph Memory."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field


class LeadStatus(str, Enum):
    """Lifecycle status of a discovered lead."""

    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    VERIFIED = "verified"
    DISQUALIFIED = "disqualified"
    DRAFTED = "drafted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    FAILED = "failed"


class HITLDecision(str, Enum):
    """Human-in-the-loop approval decision."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class PainPoint(BaseModel):
    """A detected business / technical pain point."""

    title: str
    description: str = ""
    severity: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""


class Lead(BaseModel):
    """Single enriched prospect record."""

    company_name: str = ""
    website: str = ""
    linkedin_url: str = ""
    industry: str = ""
    location: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_title: str = ""

    scraped_content: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    pain_points: list[PainPoint] = Field(default_factory=list)
    analysis_summary: str = ""

    qualification_score: float = Field(default=0.0, ge=0.0, le=10.0)
    qualification_reason: str = ""
    email_valid: bool = False
    email_mx_valid: bool = False
    email_validation_detail: str = ""

    email_subject: str = ""
    email_body: str = ""
    linkedin_pitch: str = ""
    outreach_framework: str = "PAS"

    status: LeadStatus = LeadStatus.DISCOVERED
    hitl_status: HITLDecision = HITLDecision.PENDING
    hitl_notes: str = ""
    gmail_draft_id: str = ""
    gmail_message_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def _merge_leads(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reducer: merge leads keyed by website / company name."""
    by_key: dict[str, dict[str, Any]] = {}
    for lead in existing:
        key = (lead.get("website") or lead.get("company_name") or str(id(lead))).lower()
        by_key[key] = lead
    for lead in new:
        key = (lead.get("website") or lead.get("company_name") or str(id(lead))).lower()
        by_key[key] = {**by_key.get(key, {}), **lead}
    return list(by_key.values())


def _extend_list(left: list[str], right: list[str]) -> list[str]:
    return (left or []) + (right or [])


class LeadState(TypedDict, total=False):
    """
    Shared LangGraph memory for the full enrichment & outreach workflow.

    Holds run inputs (industry, location), enriched leads, HITL decisions,
    and execution bookkeeping for the Streamlit Control Center.
    """

    # Run inputs
    industry: str
    location: str
    max_leads: int
    dry_run: bool
    auto_approve: bool
    outreach_framework: str

    # Pipeline data
    leads: Annotated[list[dict[str, Any]], _merge_leads]
    current_lead_index: int

    # HITL
    hitl_required: bool
    hitl_decisions: dict[str, str]  # lead key -> approve|reject
    awaiting_human: bool

    # Bookkeeping
    messages: Annotated[list[str], _extend_list]
    errors: Annotated[list[str], _extend_list]
    status: Literal["pending", "running", "awaiting_approval", "completed", "failed"]
    step: str
