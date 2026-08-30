"""
Agentic-Workflow — Streamlit Interactive Control Center & HITL Approval Dashboard.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from core.graph import resume_after_hitl, stream_workflow
from core.state import LeadStatus
from tools.crm_tools import export_leads_csv, export_leads_json, leads_to_dataframe
from utils.logger import setup_logging

setup_logging()
settings = get_settings()

st.set_page_config(
    page_title="Agentic-Workflow | Control Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "pipeline_state" not in st.session_state:
    st.session_state.pipeline_state = None
if "hitl_decisions" not in st.session_state:
    st.session_state.hitl_decisions = {}
if "selected_lead_key" not in st.session_state:
    st.session_state.selected_lead_key = None


def _lead_key(lead: dict) -> str:
    return (lead.get("website") or lead.get("company_name") or "").lower()


def _pending_leads(leads: list[dict]) -> list[dict]:
    return [
        lead
        for lead in leads
        if lead.get("email_body")
        and (
            lead.get("status")
            in {
                LeadStatus.DRAFTED.value,
                LeadStatus.PENDING_APPROVAL.value,
            }
            or lead.get("hitl_status") == "pending"
        )
    ]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Agentic-Workflow Control Center")
st.caption(
    "Autonomous Lead Generation · Enrichment · HITL Outreach Approval"
)

# ---------------------------------------------------------------------------
# Sidebar — run inputs
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Targeting")
    industry = st.text_input("Industry", value=settings.default_industry)
    location = st.text_input("Location", value=settings.default_location)
    max_leads = st.slider(
        "Max leads",
        min_value=1,
        max_value=20,
        value=min(settings.max_leads_per_run, 5),
    )
    framework = st.selectbox(
        "Outreach framework",
        options=["PAS", "AIDA"],
        index=0 if settings.outreach_framework == "PAS" else 1,
    )
    dry_run = st.toggle("Dry run (no live send)", value=settings.dry_run)
    auto_approve = st.toggle(
        "Bypass HITL (auto-approve)",
        value=False,
        help="For testing only — skips human review.",
    )
    st.divider()
    st.markdown(f"**Model:** `{settings.openai_model}`")
    st.markdown(f"**Env:** `{settings.app_env}`")
    run_clicked = st.button("Run enrichment pipeline", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
status_col, progress_col = st.columns([2, 1])
status_box = status_col.empty()
progress = progress_col.progress(0, text="Idle")
log_area = st.empty()
table_area = st.empty()


def _step_progress(step: str) -> tuple[float, str]:
    return {
        "start": (0.05, "Starting…"),
        "discovery": (0.2, "Discovering & scraping…"),
        "analysis": (0.4, "Pain-point analysis…"),
        "verification": (0.55, "MX verification & scoring…"),
        "copywriting": (0.7, "Drafting outreach…"),
        "human_approval": (0.85, "Awaiting HITL review…"),
        "dispatch": (0.95, "Dispatching…"),
    }.get(step, (0.5, f"Step: {step}"))


if run_clicked:
    if not industry.strip() or not location.strip():
        st.error("Industry and Location are required.")
    else:
        st.session_state.hitl_decisions = {}
        st.session_state.selected_lead_key = None
        status_box.info("Pipeline running…")
        final_state = None
        try:
            for event in stream_workflow(
                industry=industry.strip(),
                location=location.strip(),
                max_leads=max_leads,
                dry_run=dry_run,
                auto_approve=auto_approve,
                outreach_framework=framework,
            ):
                final_state = event
                step = event.get("step") or "start"
                pct, label = _step_progress(step)
                progress.progress(pct, text=label)
                leads = event.get("leads") or []
                table_area.dataframe(leads_to_dataframe(leads), use_container_width=True)
                msgs = event.get("messages") or []
                log_area.code("\n".join(msgs[-50:]) or "…")

            st.session_state.pipeline_state = final_state
            if final_state and final_state.get("awaiting_human"):
                progress.progress(0.85, text="Awaiting HITL approval")
                status_box.warning(
                    "Drafts ready — review emails below and Approve or Reject before dispatch."
                )
            else:
                progress.progress(1.0, text="Completed")
                status_box.success(
                    f"Pipeline finished — status={final_state.get('status') if final_state else 'n/a'}"
                )
        except Exception as exc:
            progress.progress(0.0, text="Failed")
            status_box.error(f"Pipeline failed: {exc}")
            st.exception(exc)

# ---------------------------------------------------------------------------
# Results + HITL
# ---------------------------------------------------------------------------
state = st.session_state.pipeline_state
if state:
    leads = state.get("leads") or []
    st.subheader("Enriched leads")
    df = leads_to_dataframe(leads)
    table_area.dataframe(df, use_container_width=True)

    export_c1, export_c2, export_c3 = st.columns(3)
    with export_c1:
        if st.button("Export CSV", use_container_width=True):
            path = export_leads_csv(leads)
            st.toast(f"Saved {path}")
    with export_c2:
        if st.button("Export JSON", use_container_width=True):
            path = export_leads_json(leads)
            st.toast(f"Saved {path}")
    with export_c3:
        st.caption(f"{len(leads)} lead(s) · step={state.get('step')} · {state.get('status')}")

    # ---- HITL review cards ----
    pending = _pending_leads(leads)
    # Also show drafted with pending hitl even if status already pending_approval
    reviewable = [
        lead
        for lead in leads
        if lead.get("email_body")
        and lead.get("status")
        in {
            LeadStatus.DRAFTED.value,
            LeadStatus.PENDING_APPROVAL.value,
            LeadStatus.APPROVED.value,
            LeadStatus.REJECTED.value,
        }
    ]

    if reviewable:
        st.subheader("HITL email review")
        st.caption("Preview each draft, then Approve or Reject. Dispatch runs only for approvals.")

        options = {
            f"{lead.get('company_name')} — {lead.get('email_subject') or '(no subject)'}": _lead_key(lead)
            for lead in reviewable
        }
        label = st.selectbox("Select lead", list(options.keys()))
        selected_key = options[label]
        st.session_state.selected_lead_key = selected_key
        lead = next(lead for lead in reviewable if _lead_key(lead) == selected_key)

        preview_left, preview_right = st.columns([2, 1])
        with preview_left:
            st.markdown("#### Email preview")
            st.markdown(f"**To:** `{lead.get('contact_email') or '(missing)'}`")
            st.markdown(f"**Subject:** {lead.get('email_subject')}")
            st.text_area(
                "Body",
                value=lead.get("email_body") or "",
                height=240,
                disabled=True,
                label_visibility="collapsed",
            )
            if lead.get("linkedin_pitch"):
                with st.expander("LinkedIn pitch"):
                    st.write(lead["linkedin_pitch"])

        with preview_right:
            st.markdown("#### Lead intel")
            st.metric("Score", lead.get("qualification_score", "—"))
            st.write(f"**Status:** `{lead.get('status')}`")
            st.write(f"**HITL:** `{lead.get('hitl_status')}`")
            st.write(f"**MX valid:** `{lead.get('email_mx_valid')}`")
            st.write(f"**Framework:** `{lead.get('outreach_framework')}`")
            if lead.get("analysis_summary"):
                st.info(lead["analysis_summary"][:400])

            decision = st.session_state.hitl_decisions.get(selected_key)
            a1, a2 = st.columns(2)
            with a1:
                if st.button("Approve", type="primary", use_container_width=True, key=f"approve_{selected_key}"):
                    st.session_state.hitl_decisions[selected_key] = "approve"
                    st.rerun()
            with a2:
                if st.button("Reject", use_container_width=True, key=f"reject_{selected_key}"):
                    st.session_state.hitl_decisions[selected_key] = "reject"
                    st.rerun()

            if decision:
                st.success(f"Marked: **{decision.upper()}**")

        # Decision summary
        st.markdown("##### Decision queue")
        for lead in reviewable:
            key = _lead_key(lead)
            mark = st.session_state.hitl_decisions.get(key, "—")
            st.write(f"- **{lead.get('company_name')}**: `{mark}`")

        still_open = [
            lead
            for lead in reviewable
            if lead.get("status")
            in {LeadStatus.DRAFTED.value, LeadStatus.PENDING_APPROVAL.value}
            and _lead_key(lead) not in st.session_state.hitl_decisions
        ]

        if st.button(
            "Submit HITL decisions & dispatch",
            type="primary",
            disabled=bool(still_open),
            use_container_width=True,
        ):
            with st.spinner("Applying decisions and dispatching…"):
                updated = resume_after_hitl(state, st.session_state.hitl_decisions)
                st.session_state.pipeline_state = updated
            st.success(f"Done — status={updated.get('status')}")
            st.dataframe(leads_to_dataframe(updated.get("leads") or []), use_container_width=True)
            if still_open:
                st.warning("Some drafts still lack a decision.")
            st.rerun()

        if still_open:
            st.info(f"{len(still_open)} draft(s) still need Approve/Reject.")

    msgs = state.get("messages") or []
    with st.expander("Pipeline log", expanded=False):
        st.code("\n".join(msgs) or "No messages")

else:
    status_box.info("Configure Industry & Location in the sidebar, then run the pipeline.")
    progress.progress(0, text="Idle")
