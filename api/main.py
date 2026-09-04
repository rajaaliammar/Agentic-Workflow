"""
Agentic Workflow — FastAPI REST API (SQLite-backed)

Run:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.graph import run_workflow
from db.database import SessionLocal, init_db
from db.models import Job, Lead

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Agentic Workflow API",
    description="REST API for the Autonomous Lead Generation, Enrichment & Outreach Agent",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """Ensure SQLite tables exist."""
    init_db()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class WorkflowRequest(BaseModel):
    industry: str = Field(default="Real Estate", examples=["Fintech"])
    location: str = Field(default="Dubai", examples=["London"])
    max_leads: int = Field(default=3, ge=1, le=20)
    framework: str = Field(default="PAS", examples=["PAS", "AIDA", "BAB"])
    auto_approve: bool = Field(default=False)


class WorkflowStartResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    step: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    total_leads: int = 0
    errors: list[str] = []


class LeadOut(BaseModel):
    id: int | None = None
    company_name: str = ""
    website: str = ""
    qualification_score: float = 0.0
    email_mx_valid: bool = False
    status: str = ""
    hitl_status: str = ""
    email_subject: str = ""
    email_body: str = ""
    analysis_summary: str = ""


class JobLeadsResponse(BaseModel):
    job_id: str
    status: str
    leads: list[LeadOut]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _update_job_status(
    db: Session,
    job_id: str,
    *,
    status: str,
    step: str | None = None,
    errors: str | None = None,
) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    job.status = status
    if step is not None:
        job.step = step
    if errors is not None:
        job.errors = errors
    job.updated_at = _utcnow()
    db.commit()
    db.refresh(job)
    return job


def _persist_leads(db: Session, job_id: str, leads: list[dict[str, Any]]) -> None:
    """Replace all leads for a job with the latest workflow results."""
    job = db.get(Job, job_id)
    if job is None:
        return

    job.leads.clear()
    db.flush()

    for lead in leads:
        job.leads.append(
            Lead(
                job_id=job_id,
                company_name=lead.get("company_name") or "",
                website=lead.get("website") or "",
                qualification_score=float(lead.get("qualification_score") or 0),
                email_mx_valid=bool(lead.get("email_mx_valid")),
                status=lead.get("status") or "",
                hitl_status=lead.get("hitl_status") or "",
                email_subject=lead.get("email_subject") or "",
                email_body=lead.get("email_body") or "",
                analysis_summary=lead.get("analysis_summary") or "",
            )
        )
    job.updated_at = _utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Background task runner
# ---------------------------------------------------------------------------
def _execute_workflow(job_id: str, req: WorkflowRequest) -> None:
    """Run the LangGraph workflow and persist results to SQLite."""
    db = SessionLocal()
    try:
        _update_job_status(db, job_id, status="running", step="discovery")

        result = run_workflow(
            industry=req.industry,
            location=req.location,
            max_leads=req.max_leads,
            dry_run=True,
            auto_approve=req.auto_approve,
            outreach_framework=req.framework,
        )

        leads = result.get("leads") or []
        errors = result.get("errors") or []
        final_status = result.get("status") or "completed"
        step = result.get("step")

        _persist_leads(db, job_id, leads)
        _update_job_status(
            db,
            job_id,
            status=final_status,
            step=step,
            errors="\n".join(errors) if errors else "",
        )
    except Exception as exc:
        _update_job_status(
            db,
            job_id,
            status="failed",
            step="error",
            errors=str(exc),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/v1/run-workflow", response_model=WorkflowStartResponse)
async def start_workflow(req: WorkflowRequest, background_tasks: BackgroundTasks):
    """Create a job row and trigger workflow execution asynchronously."""
    job_id = uuid.uuid4().hex[:12]
    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            industry=req.industry,
            location=req.location,
            status="processing",
            step="queued",
            framework=req.framework,
            auto_approve=req.auto_approve,
            max_leads=req.max_leads,
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    background_tasks.add_task(_execute_workflow, job_id, req)
    return WorkflowStartResponse(job_id=job_id, status="processing")


@app.get("/api/v1/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str):
    """Return current execution state of a job from SQLite."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        error_list = [e for e in (job.errors or "").split("\n") if e.strip()]
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            step=job.step,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
            total_leads=len(job.leads),
            errors=error_list,
        )
    finally:
        db.close()


@app.get("/api/v1/leads/{job_id}", response_model=JobLeadsResponse)
async def get_leads(job_id: str):
    """Return processed leads, scores, and email drafts from SQLite."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        leads_out = [
            LeadOut(
                id=lead.id,
                company_name=lead.company_name,
                website=lead.website,
                qualification_score=lead.qualification_score,
                email_mx_valid=lead.email_mx_valid,
                status=lead.status,
                hitl_status=lead.hitl_status,
                email_subject=lead.email_subject,
                email_body=lead.email_body,
                analysis_summary=lead.analysis_summary,
            )
            for lead in job.leads
        ]
        return JobLeadsResponse(job_id=job.id, status=job.status, leads=leads_out)
    finally:
        db.close()
