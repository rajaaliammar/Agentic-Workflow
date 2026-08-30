"""LangGraph workflow definition with conditional HITL review edges."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from config.settings import get_settings
from core.nodes import (
    analysis_node,
    copywriting_node,
    discovery_node,
    dispatch_node,
    human_approval_node,
    verification_node,
)
from core.state import LeadState, LeadStatus
from utils.logger import logger


def _route_after_verification(state: LeadState) -> Literal["copywriting", "end"]:
    """Continue only when at least one lead is verified / qualified."""
    settings = get_settings()
    min_score = settings.min_qualification_score
    leads = state.get("leads") or []
    qualified = [
        lead
        for lead in leads
        if lead.get("status") == LeadStatus.VERIFIED.value
        and float(lead.get("qualification_score") or 0) >= min_score
    ]
    if qualified:
        return "copywriting"
    logger.info("No verified leads — ending before copywriting")
    return "end"


def _route_after_hitl(state: LeadState) -> Literal["dispatch", "end", "wait"]:
    """
    After human_approval:
    - wait: still awaiting Streamlit decisions (interrupt-style pause)
    - dispatch: at least one approved lead
    - end: all rejected or nothing to send
    """
    if state.get("awaiting_human"):
        return "wait"

    leads = state.get("leads") or []
    approved = [lead for lead in leads if lead.get("status") == LeadStatus.APPROVED.value]
    if approved:
        return "dispatch"
    return "end"


def build_graph() -> Any:
    """
    Assemble and compile the enterprise lead workflow.

    Flow:
        START → discovery → analysis → verification
              → (copywriting | END)
              → human_approval
              → (dispatch | END | wait→END for UI interrupt)
    """
    workflow = StateGraph(LeadState)

    workflow.add_node("discovery", discovery_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("copywriting", copywriting_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("dispatch", dispatch_node)

    workflow.add_edge(START, "discovery")
    workflow.add_edge("discovery", "analysis")
    workflow.add_edge("analysis", "verification")
    workflow.add_conditional_edges(
        "verification",
        _route_after_verification,
        {"copywriting": "copywriting", "end": END},
    )
    workflow.add_edge("copywriting", "human_approval")
    workflow.add_conditional_edges(
        "human_approval",
        _route_after_hitl,
        {
            "dispatch": "dispatch",
            "end": END,
            "wait": END,  # pause for Streamlit; resume via run_from_hitl()
        },
    )
    workflow.add_edge("dispatch", END)

    return workflow.compile()


def initial_state(
    industry: str,
    location: str,
    max_leads: int = 10,
    dry_run: bool = True,
    auto_approve: bool = False,
    outreach_framework: str = "PAS",
    hitl_decisions: dict[str, str] | None = None,
) -> LeadState:
    """Build a fresh LeadState for a pipeline run."""
    settings = get_settings()
    return {
        "industry": industry,
        "location": location,
        "max_leads": max_leads,
        "dry_run": dry_run,
        "auto_approve": auto_approve,
        "outreach_framework": outreach_framework or settings.outreach_framework,
        "leads": [],
        "current_lead_index": 0,
        "hitl_required": settings.require_human_approval and not auto_approve,
        "hitl_decisions": hitl_decisions or {},
        "awaiting_human": False,
        "messages": [],
        "errors": [],
        "status": "running",
        "step": "start",
    }


def run_workflow(
    industry: str,
    location: str,
    max_leads: int = 10,
    dry_run: bool = True,
    auto_approve: bool = False,
    outreach_framework: str = "PAS",
) -> LeadState:
    """Execute the full graph synchronously (CLI / batch)."""
    logger.info(
        "Starting workflow | industry={!r} location={!r} max_leads={} auto_approve={}",
        industry,
        location,
        max_leads,
        auto_approve,
    )
    graph = build_graph()
    state = initial_state(
        industry=industry,
        location=location,
        max_leads=max_leads,
        dry_run=dry_run,
        auto_approve=auto_approve,
        outreach_framework=outreach_framework,
    )

    final_state: LeadState = state
    for event in graph.stream(state, stream_mode="values"):
        final_state = event

    if final_state.get("awaiting_human"):
        final_state["status"] = "awaiting_approval"
    elif final_state.get("errors"):
        final_state["status"] = "failed"
    else:
        final_state["status"] = "completed"

    logger.info(
        "Workflow finished | status={} leads={}",
        final_state.get("status"),
        len(final_state.get("leads") or []),
    )
    return final_state


def stream_workflow(
    industry: str,
    location: str,
    max_leads: int = 10,
    dry_run: bool = True,
    auto_approve: bool = False,
    outreach_framework: str = "PAS",
):
    """Yield intermediate states for live Streamlit updates."""
    graph = build_graph()
    state = initial_state(
        industry=industry,
        location=location,
        max_leads=max_leads,
        dry_run=dry_run,
        auto_approve=auto_approve,
        outreach_framework=outreach_framework,
    )
    for event in graph.stream(state, stream_mode="values"):
        yield event


def resume_after_hitl(state: LeadState, hitl_decisions: dict[str, str]) -> LeadState:
    """
    Resume from a paused HITL state with Approve/Reject decisions.

    Re-runs human_approval → dispatch using the accumulated lead payloads.
    """
    merged: LeadState = {
        **state,
        "hitl_decisions": hitl_decisions,
        "awaiting_human": False,
        "auto_approve": False,
        "status": "running",
    }

    # Apply HITL then dispatch directly for a deterministic resume path
    after_hitl = human_approval_node(merged)
    resumed: LeadState = {**merged, **after_hitl}

    if resumed.get("awaiting_human"):
        resumed["status"] = "awaiting_approval"
        return resumed

    route = _route_after_hitl(resumed)
    if route == "dispatch":
        after_dispatch = dispatch_node(resumed)
        resumed = {**resumed, **after_dispatch}
        # Merge message/error lists carefully
        resumed["messages"] = (merged.get("messages") or []) + (after_hitl.get("messages") or []) + (
            after_dispatch.get("messages") or []
        )
        resumed["errors"] = (merged.get("errors") or []) + (after_dispatch.get("errors") or [])
        resumed["status"] = "completed"
    else:
        resumed["messages"] = (merged.get("messages") or []) + (after_hitl.get("messages") or [])
        resumed["status"] = "completed"

    return resumed
