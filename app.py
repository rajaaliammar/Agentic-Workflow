"""
Agentic-Workflow — Streamlit Web Interface

Run:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import get_settings
from core.graph import resume_after_hitl, stream_workflow
from core.state import LeadStatus
from utils.logger import setup_logging

setup_logging()
settings = get_settings()

# ---------------------------------------------------------------------------
# Page config & styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Agentic Workflow",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .metric-card {
        background: linear-gradient(135deg, #1e1e2f 0%, #2d2d44 100%);
        padding: 1.2rem 1.4rem;
        border-radius: 12px;
        border: 1px solid #3d3d5c;
    }
    .metric-card label {
        color: #a0a0b8;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-card .value {
        color: #ffffff;
        font-size: 2rem;
        font-weight: 700;
        margin-top: 0.25rem;
    }
    div[data-testid="stSidebar"] {
        background-color: #161622;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "pipeline_state" not in st.session_state:
    st.session_state.pipeline_state = None
if "hitl_decisions" not in st.session_state:
    st.session_state.hitl_decisions = {}


def _lead_key(lead: dict) -> str:
    return (lead.get("website") or lead.get("company_name") or "").lower()


def _is_qualified(lead: dict) -> bool:
    score = float(lead.get("qualification_score") or 0)
    status = lead.get("status") or ""
    return (
        status == LeadStatus.VERIFIED.value
        or status in {
            LeadStatus.DRAFTED.value,
            LeadStatus.PENDING_APPROVAL.value,
            LeadStatus.APPROVED.value,
            LeadStatus.SENT.value,
        }
        and score >= settings.min_qualification_score
    ) or (
        status == LeadStatus.VERIFIED.value
        and score >= settings.min_qualification_score
    )


def _is_drafted_or_approved(lead: dict) -> bool:
    return lead.get("status") in {
        LeadStatus.DRAFTED.value,
        LeadStatus.PENDING_APPROVAL.value,
        LeadStatus.APPROVED.value,
        LeadStatus.SENT.value,
    }


def _is_hitl_pending(lead: dict) -> bool:
    return (
        lead.get("hitl_status") == "pending"
        or lead.get("status")
        in {LeadStatus.DRAFTED.value, LeadStatus.PENDING_APPROVAL.value}
    ) and bool(lead.get("email_body"))


def _leads_summary_table(leads: list[dict]) -> pd.DataFrame:
    rows = []
    for lead in leads:
        mx = lead.get("email_mx_valid")
        rows.append(
            {
                "Company": lead.get("company_name") or "—",
                "Score": lead.get("qualification_score", "—"),
                "Status": lead.get("status") or "—",
                "MX Check": "✓ Valid" if mx else ("✗ Invalid" if mx is False else "—"),
                "URL": lead.get("website") or "—",
            }
        )
    return pd.DataFrame(rows)


def _compute_metrics(leads: list[dict]) -> tuple[int, int, int]:
    total = len(leads)
    qualified = sum(1 for lead in leads if _is_qualified(lead))
    drafted = sum(1 for lead in leads if _is_drafted_or_approved(lead))
    return total, qualified, drafted


def _render_metrics(total: int, qualified: int, drafted: int) -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total Leads Found", total)
    with c2:
        st.metric("Qualified Leads", qualified)
    with c3:
        st.metric("Approved / Drafted Leads", drafted)


def _step_progress(step: str) -> tuple[float, str]:
    return {
        "start": (0.05, "Initializing pipeline…"),
        "discovery": (0.20, "Discovery — scraping leads…"),
        "analysis": (0.40, "Analysis — pain-point detection…"),
        "verification": (0.55, "Verification — MX & scoring…"),
        "copywriting": (0.70, "Copywriting — drafting emails…"),
        "human_approval": (0.85, "HITL — awaiting review…"),
        "dispatch": (0.95, "Dispatch — creating drafts…"),
    }.get(step, (0.50, f"Running: {step}"))


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Agentic Workflow")
st.caption("Autonomous Lead Generation · Enrichment · Human-in-the-Loop Outreach")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Pipeline Configuration")
    industry = st.text_input("Industry", value="Real Estate")
    location = st.text_input("Location", value="Dubai")
    max_leads = st.slider("Max Leads", min_value=1, max_value=10, value=3)
    framework = st.selectbox(
        "Copywriting Framework",
        options=["PAS", "AIDA", "BAB"],
        index=0,
    )
    auto_approve = st.checkbox("Auto-Approve HITL", value=False)
    st.divider()
    st.caption(f"LLM: `{settings.llm_provider}` / `{settings.active_llm_model}`")
    st.caption(f"Dry run: `{settings.dry_run}`")
    start_clicked = st.button(
        "Start Pipeline Execution",
        type="primary",
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Main layout placeholders
# ---------------------------------------------------------------------------
metrics_container = st.container()
progress_container = st.container()
results_container = st.container()
hitl_container = st.container()

# ---------------------------------------------------------------------------
# Pipeline execution (stream_workflow mirrors run_workflow with live updates)
# ---------------------------------------------------------------------------
if start_clicked:
    if not industry.strip() or not location.strip():
        st.error("Industry and Location are required.")
    else:
        st.session_state.hitl_decisions = {}
        progress_bar = progress_container.progress(0, text="Starting pipeline…")
        status_msg = progress_container.empty()

        final_state = None
        try:
            with st.spinner("Executing agent pipeline…"):
                for event in stream_workflow(
                    industry=industry.strip(),
                    location=location.strip(),
                    max_leads=max_leads,
                    dry_run=settings.dry_run,
                    auto_approve=auto_approve,
                    outreach_framework=framework,
                ):
                    final_state = event
                    step = event.get("step") or "start"
                    pct, label = _step_progress(step)
                    progress_bar.progress(pct, text=label)
                    leads = event.get("leads") or []
                    total, qualified, drafted = _compute_metrics(leads)
                    with metrics_container:
                        _render_metrics(total, qualified, drafted)

            st.session_state.pipeline_state = final_state

            if final_state and final_state.get("awaiting_human"):
                progress_bar.progress(0.85, text="Awaiting HITL approval")
                status_msg.warning("Pipeline paused — review drafts below and Approve or Reject.")
            elif final_state and final_state.get("status") == "failed":
                progress_bar.progress(0.0, text="Failed")
                status_msg.error("Pipeline finished with errors. Check the log below.")
            else:
                progress_bar.progress(1.0, text="Completed")
                status_msg.success("Pipeline execution completed.")

        except Exception as exc:
            progress_bar.progress(0.0, text="Failed")
            status_msg.error(f"Pipeline failed: {exc}")
            st.exception(exc)

# ---------------------------------------------------------------------------
# Results & HITL review
# ---------------------------------------------------------------------------
state = st.session_state.pipeline_state

with metrics_container:
    if state:
        leads = state.get("leads") or []
        _render_metrics(*_compute_metrics(leads))
    else:
        _render_metrics(0, 0, 0)

with results_container:
    if not state:
        st.info("Configure the sidebar and click **Start Pipeline Execution** to begin.")
    else:
        leads = state.get("leads") or []

        st.subheader("Lead Results")
        st.dataframe(
            _leads_summary_table(leads),
            use_container_width=True,
            hide_index=True,
        )

        pending_hitl = [lead for lead in leads if _is_hitl_pending(lead)]

        with hitl_container:
            if pending_hitl:
                st.subheader("HITL Approval — Email Drafts")
                st.caption(
                    "Review generated outreach below. Approve to create a Gmail draft, "
                    "or reject to skip."
                )

                tabs = st.tabs(
                    [lead.get("company_name") or f"Lead {i + 1}" for i, lead in enumerate(pending_hitl)]
                )

                for tab, lead in zip(tabs, pending_hitl):
                    key = _lead_key(lead)
                    with tab:
                        col_preview, col_actions = st.columns([3, 1])

                        with col_preview:
                            st.markdown(f"**To:** `{lead.get('contact_email') or 'unknown'}`")
                            st.markdown(f"**Subject:** {lead.get('email_subject') or '(no subject)'}")
                            st.text_area(
                                "Email body",
                                value=lead.get("email_body") or "",
                                height=220,
                                disabled=True,
                                label_visibility="collapsed",
                            )
                            if lead.get("linkedin_pitch"):
                                with st.expander("LinkedIn pitch"):
                                    st.write(lead["linkedin_pitch"])

                        with col_actions:
                            st.metric("Score", lead.get("qualification_score", "—"))
                            st.write(f"**Status:** `{lead.get('status')}`")
                            st.write(f"**MX:** `{lead.get('email_mx_valid')}`")
                            st.write(f"**Framework:** `{lead.get('outreach_framework') or framework}`")

                            decision = st.session_state.hitl_decisions.get(key)
                            if decision == "approve":
                                st.success("Approved")
                            elif decision == "reject":
                                st.error("Rejected")

                            btn_approve, btn_reject = st.columns(2)
                            with btn_approve:
                                if st.button(
                                    "Approve & Create Draft",
                                    key=f"approve_{key}",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    decisions = {
                                        **st.session_state.hitl_decisions,
                                        key: "approve",
                                    }
                                    with st.spinner("Creating Gmail draft…"):
                                        updated = resume_after_hitl(state, decisions)
                                    st.session_state.hitl_decisions = decisions
                                    st.session_state.pipeline_state = updated
                                    st.rerun()

                            with btn_reject:
                                if st.button(
                                    "Reject",
                                    key=f"reject_{key}",
                                    use_container_width=True,
                                ):
                                    decisions = {
                                        **st.session_state.hitl_decisions,
                                        key: "reject",
                                    }
                                    updated = resume_after_hitl(state, decisions)
                                    st.session_state.hitl_decisions = decisions
                                    st.session_state.pipeline_state = updated
                                    st.rerun()

            elif leads:
                st.info("No leads pending HITL approval.")

        with st.expander("Pipeline log", expanded=False):
            msgs = state.get("messages") or []
            errors = state.get("errors") or []
            if msgs:
                st.code("\n".join(msgs))
            if errors:
                st.warning("Errors:\n" + "\n".join(f"• {e}" for e in errors))
