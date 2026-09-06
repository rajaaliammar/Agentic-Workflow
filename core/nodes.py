"""Individual LangGraph execution nodes wrapping agent callables."""

from __future__ import annotations

from typing import Any

from agents.analyzer_agent import run_analyzer
from agents.copywriter_agent import run_copywriter
from agents.discovery_agent import run_discovery
from agents.verification_agent import run_verification
from config.settings import get_settings
from core.state import HITLDecision, LeadState, LeadStatus
from tools.gmail_tools import create_draft, send_email
from utils.logger import logger


def discovery_node(state: LeadState) -> dict[str, Any]:
    """Discover companies matching industry + location."""
    print("[START] Discovery Node", flush=True)
    logger.info("[START] Discovery Node")
    result = run_discovery(state)
    print("[END] Discovery Node", flush=True)
    logger.info("[END] Discovery Node | leads={}", len(result.get("leads") or []))
    return result


def analysis_node(state: LeadState) -> dict[str, Any]:
    """Deep website audit & pain-point extraction."""
    print("[START] Analyzer Node", flush=True)
    logger.info("[START] Analyzer Node")
    result = run_analyzer(state)
    print("[END] Analyzer Node", flush=True)
    logger.info("[END] Analyzer Node")
    return result


def verification_node(state: LeadState) -> dict[str, Any]:
    """MX validation + qualification scoring."""
    print("[START] Verification Node", flush=True)
    logger.info("[START] Verification Node")
    result = run_verification(state)
    print("[END] Verification Node", flush=True)
    logger.info("[END] Verification Node")
    return result


def copywriting_node(state: LeadState) -> dict[str, Any]:
    """Generate personalized cold email + LinkedIn pitch."""
    print("[START] Copywriter Node", flush=True)
    logger.info("[START] Copywriter Node")
    result = run_copywriter(state)
    print("[END] Copywriter Node", flush=True)
    logger.info("[END] Copywriter Node")
    return result


def human_approval_node(state: LeadState) -> dict[str, Any]:
    """
    HITL gate.

    - If auto_approve / HITL disabled: mark drafts approved.
    - If decisions present in state (from Streamlit): apply them.
    - Otherwise: pause pipeline (awaiting_human=True) for UI review.
    """
    print("[START] Human Approval Node", flush=True)
    logger.info("[START] Human Approval Node")

    settings = get_settings()
    leads = list(state.get("leads") or [])
    decisions = dict(state.get("hitl_decisions") or {})
    auto_approve = bool(state.get("auto_approve")) or not settings.require_human_approval
    messages: list[str] = []

    drafted = [
        lead
        for lead in leads
        if lead.get("status") in {LeadStatus.DRAFTED.value, LeadStatus.PENDING_APPROVAL.value}
    ]

    if not drafted:
        messages.append("HITL: no drafted leads to review")
        print("[END] Human Approval Node (no drafts)", flush=True)
        return {
            "messages": messages,
            "step": "human_approval",
            "awaiting_human": False,
            "status": "completed",
        }

    if auto_approve and not decisions:
        updated = []
        for lead in leads:
            if lead.get("status") in {
                LeadStatus.DRAFTED.value,
                LeadStatus.PENDING_APPROVAL.value,
            }:
                updated.append(
                    {
                        **lead,
                        "status": LeadStatus.APPROVED.value,
                        "hitl_status": HITLDecision.SKIPPED.value,
                        "hitl_notes": "Auto-approved (HITL bypass)",
                    }
                )
            else:
                updated.append(lead)
        messages.append(f"HITL bypassed — auto-approved {len(drafted)} draft(s)")
        logger.info("HITL auto-approve applied to {} lead(s)", len(drafted))
        print("[END] Human Approval Node (auto-approved)", flush=True)
        return {
            "leads": updated,
            "messages": messages,
            "step": "human_approval",
            "awaiting_human": False,
            "status": "running",
        }

    pending = 0
    updated = []
    for lead in leads:
        key = (lead.get("website") or lead.get("company_name") or "").lower()
        if lead.get("status") not in {
            LeadStatus.DRAFTED.value,
            LeadStatus.PENDING_APPROVAL.value,
            LeadStatus.APPROVED.value,
            LeadStatus.REJECTED.value,
        }:
            updated.append(lead)
            continue

        decision = decisions.get(key)
        if decision == "approve":
            updated.append(
                {
                    **lead,
                    "status": LeadStatus.APPROVED.value,
                    "hitl_status": HITLDecision.APPROVED.value,
                }
            )
            messages.append(f"Approved: {lead.get('company_name')}")
        elif decision == "reject":
            updated.append(
                {
                    **lead,
                    "status": LeadStatus.REJECTED.value,
                    "hitl_status": HITLDecision.REJECTED.value,
                }
            )
            messages.append(f"Rejected: {lead.get('company_name')}")
        else:
            pending += 1
            updated.append(
                {
                    **lead,
                    "status": LeadStatus.PENDING_APPROVAL.value,
                    "hitl_status": HITLDecision.PENDING.value,
                }
            )

    awaiting = pending > 0
    if awaiting:
        messages.append(f"HITL: awaiting human review for {pending} draft(s)")
        logger.info("Awaiting HITL approval for {} draft(s)", pending)
    else:
        messages.append("HITL: all decisions collected")

    print(f"[END] Human Approval Node (awaiting={awaiting})", flush=True)
    return {
        "leads": updated,
        "messages": messages,
        "step": "human_approval",
        "awaiting_human": awaiting,
        "status": "awaiting_approval" if awaiting else "running",
    }


def dispatch_node(state: LeadState) -> dict[str, Any]:
    """Create Gmail drafts / send approved emails (respects dry_run)."""
    print("[START] Dispatch Node", flush=True)
    logger.info("[START] Dispatch Node")

    settings = get_settings()
    # Prefer explicit state; fall back to live .env DRY_RUN
    dry_run = bool(state.get("dry_run", settings.dry_run))
    leads = list(state.get("leads") or [])
    messages: list[str] = []
    errors: list[str] = []
    updated: list[dict[str, Any]] = []

    approved = [lead for lead in leads if lead.get("status") == LeadStatus.APPROVED.value]
    messages.append(f"Dispatching {len(approved)} approved lead(s) | dry_run={dry_run}")
    logger.info("Dispatch node | approved={} dry_run={}", len(approved), dry_run)
    print(f"Dispatch: {len(approved)} approved | DRY_RUN={dry_run}", flush=True)

    approved_keys = {
        (lead.get("website") or lead.get("company_name") or "").lower() for lead in approved
    }

    for lead in leads:
        key = (lead.get("website") or lead.get("company_name") or "").lower()
        if key not in approved_keys:
            updated.append(lead)
            continue

        try:
            to = lead.get("contact_email") or ""
            subject = lead.get("email_subject") or ""
            body = lead.get("email_body") or ""

            if dry_run:
                draft_meta = create_draft(
                    to=to or "dry-run@example.com",
                    subject=subject,
                    body=body,
                    dry_run=True,
                )
                updated.append(
                    {
                        **lead,
                        "status": LeadStatus.APPROVED.value,
                        "gmail_draft_id": draft_meta.get("id", "dry-run-draft"),
                        "metadata": {
                            **(lead.get("metadata") or {}),
                            "dispatch": "dry_run",
                        },
                    }
                )
                messages.append(f"DRY_RUN draft for {lead.get('company_name')}")
                continue

            if not to:
                # Still create a draft-to-self path for OAuth testing when email missing
                to = settings.gmail_sender_email or "me"
                messages.append(
                    f"No contact email for {lead.get('company_name')} — drafting to {to}"
                )

            draft = create_draft(to=to, subject=subject, body=body, dry_run=False)
            # Draft-only by default for safety; send only if sender + recipient look real
            updated.append(
                {
                    **lead,
                    "status": LeadStatus.SENT.value
                    if draft.get("id") and draft.get("id") != "dry-run-draft"
                    else LeadStatus.APPROVED.value,
                    "gmail_draft_id": draft.get("id", ""),
                    "gmail_message_id": "",
                    "metadata": {
                        **(lead.get("metadata") or {}),
                        "dispatch": "gmail_draft",
                    },
                }
            )
            messages.append(f"Gmail draft created for {lead.get('company_name')} → {to}")
        except Exception as exc:
            logger.exception("Dispatch failed for {}", lead.get("company_name"))
            errors.append(f"Dispatch failed for {lead.get('company_name')}: {exc}")
            updated.append({**lead, "status": LeadStatus.FAILED.value})

    print("[END] Dispatch Node", flush=True)
    logger.info("[END] Dispatch Node")
    return {
        "leads": updated,
        "messages": messages,
        "errors": errors,
        "step": "dispatch",
        "awaiting_human": False,
        "status": "completed",
    }
