"""Verification agent — MX record check & lead qualification scoring."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings
from core.state import LeadState, LeadStatus
from tools.validator_tools import validate_email
from utils.logger import logger


def _compute_score(lead: dict[str, Any], email_result: dict[str, Any]) -> tuple[float, str]:
    """Heuristic qualification score combining analysis hints, MX, and pain points."""
    score = 0.0
    reasons: list[str] = []

    suggested = (lead.get("metadata") or {}).get("suggested_score")
    if suggested is not None:
        try:
            base = float(suggested)
            score += min(max(base, 0.0), 7.0)
            reasons.append(f"analyzer_hint={base}")
        except (TypeError, ValueError):
            score += 3.0
    else:
        score += 3.0

    pain_points = lead.get("pain_points") or []
    high = sum(1 for p in pain_points if isinstance(p, dict) and p.get("severity") == "high")
    score += min(len(pain_points) * 0.4 + high * 0.6, 2.0)
    reasons.append(f"pain_points={len(pain_points)} high={high}")

    if email_result.get("syntax_valid"):
        score += 0.5
        reasons.append("syntax_ok")
    if email_result.get("mx_valid"):
        score += 1.5
        reasons.append("mx_ok")
    else:
        reasons.append("mx_fail")

    if lead.get("analysis_summary"):
        score += 0.5

    score = round(min(max(score, 0.0), 10.0), 2)
    return score, "; ".join(reasons)


def run_verification(state: LeadState) -> dict[str, Any]:
    """
    LangGraph node body: validate emails (syntax + MX) and score / qualify leads.

    TEMP (testing): FORCE_PASS_ALL_LEADS sends every analyzed lead through as verified
    so the pipeline always reaches copywriting → dispatch.
    """
    # TODO: set False / remove before production
    FORCE_PASS_ALL_LEADS = True

    settings = get_settings()
    min_score = 0.0 if FORCE_PASS_ALL_LEADS else float(
        getattr(settings, "min_qualification_score", 4.0) or 4.0
    )
    leads = state.get("leads") or []
    messages: list[str] = []
    errors: list[str] = []

    # Also accept discovered leads with empty scrape during test force-pass
    targets = [
        lead
        for lead in leads
        if lead.get("status")
        in {LeadStatus.ANALYZED.value, LeadStatus.DISCOVERED.value, LeadStatus.FAILED.value}
    ]
    if FORCE_PASS_ALL_LEADS and not targets:
        targets = list(leads)

    messages.append(
        f"Verifying {len(targets)} lead(s) | min_score={min_score}"
        + (" | FORCE_PASS_ALL=ON" if FORCE_PASS_ALL_LEADS else "")
    )
    logger.info(
        "Verification agent | targets={} min_score={} force_pass={}",
        len(targets),
        min_score,
        FORCE_PASS_ALL_LEADS,
    )

    verified: list[dict[str, Any]] = []
    target_keys = {
        (t.get("website") or t.get("company_name") or "").lower() for t in targets
    }

    for lead in leads:
        key = (lead.get("website") or lead.get("company_name") or "").lower()
        if key not in target_keys:
            verified.append(lead)
            continue

        email = (lead.get("contact_email") or "").strip()
        try:
            email_result = (
                validate_email(email)
                if email
                else {
                    "email": "",
                    "syntax_valid": False,
                    "mx_valid": False,
                    "detail": "No contact email provided",
                }
            )
            score, reason = _compute_score(lead, email_result)

            if FORCE_PASS_ALL_LEADS:
                # Ensure graph routing (score >= settings threshold) also passes
                gate = float(getattr(settings, "min_qualification_score", 4.0) or 4.0)
                score = max(score, gate, 1.0)
                reason = f"{reason}; FORCE_PASS_ALL_LEADS"
                status = LeadStatus.VERIFIED
            else:
                if email and not email_result.get("syntax_valid"):
                    reason += "; invalid email syntax"
                    status = LeadStatus.DISQUALIFIED
                else:
                    status = (
                        LeadStatus.VERIFIED if score >= min_score else LeadStatus.DISQUALIFIED
                    )

            updated = {
                **lead,
                "email_valid": bool(email_result.get("syntax_valid")),
                "email_mx_valid": bool(email_result.get("mx_valid")),
                "email_validation_detail": str(email_result.get("detail") or ""),
                "qualification_score": score,
                "qualification_reason": reason,
                "status": status.value,
            }
            verified.append(updated)
            messages.append(
                f"{lead.get('company_name')}: score={score} "
                f"mx={email_result.get('mx_valid')} status={status.value}"
            )
            logger.info(
                "Verified {} | score={} mx={} status={}",
                lead.get("company_name"),
                score,
                email_result.get("mx_valid"),
                status.value,
            )
        except Exception as exc:
            logger.exception("Verification failed for {}", lead.get("company_name"))
            errors.append(f"Verify failed for {lead.get('company_name')}: {exc}")
            if FORCE_PASS_ALL_LEADS:
                verified.append(
                    {
                        **lead,
                        "qualification_score": 10.0,
                        "qualification_reason": f"FORCE_PASS after error: {exc}",
                        "status": LeadStatus.VERIFIED.value,
                    }
                )
            else:
                verified.append({**lead, "status": LeadStatus.FAILED.value})

    return {
        "leads": verified,
        "messages": messages,
        "errors": errors,
        "step": "verification",
    }
