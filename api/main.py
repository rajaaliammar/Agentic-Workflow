"""
Agentic Workflow — FastAPI REST API

Run:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.graph import run_workflow

# ---------------------------------------------------------------------------
# In-memory job store (thread-safe via lock)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}


def _set_job(job_id: str, data: dict[str, Any]) -> None:
    with _lock:
        JOBS[job_id] = data


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return JOBS.get(job_id)


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
    completed_at: str | None = None
    total_leads: int = 0
    errors: list[str] = []


class LeadOut(BaseModel):
    company_name: str = ""
    website: str = ""
    industry: str = ""
    location: str = ""
    contact_email: str = ""
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
# Background task runner
# ---------------------------------------------------------------------------
def _execute_workflow(job_id: str, req: WorkflowRequest) -> None:
    """Run the LangGraph workflow synchronously in a background thread."""
    try:
        _set_job(job_id, {**(_get_job(job_id) or {}), "status": "running"})

        result = run_workflow(
            industry=req.industry,
            location=req.location,
            max_leads=req.max_leads,
            dry_run=True,
            auto_approve=req.auto_approve,
            outreach_framework=req.framework,
        )

        _set_job(
            job_id,
            {
                **(_get_job(job_id) or {}),
                "status": result.get("status") or "completed",
                "step": result.get("step"),
                "leads": result.get("leads") or [],
                "messages": result.get("messages") or [],
                "errors": result.get("errors") or [],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        _set_job(
            job_id,
            {
                **(_get_job(job_id) or {}),
                "status": "failed",
                "errors": [str(exc)],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/v1/run-workflow", response_model=WorkflowStartResponse)
async def start_workflow(req: WorkflowRequest, background_tasks: BackgroundTasks):
    """Trigger a new workflow run asynchronously."""
    job_id = uuid.uuid4().hex[:12]

    _set_job(
        job_id,
        {
            "status": "processing",
            "step": "queued",
            "leads": [],
            "messages": [],
            "errors": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "request": req.model_dump(),
        },
    )

    background_tasks.add_task(_execute_workflow, job_id, req)
    return WorkflowStartResponse(job_id=job_id, status="processing")


@app.get("/api/v1/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str):
    """Return current execution state of a job."""
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=job_id,
        status=job.get("status") or "unknown",
        step=job.get("step"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
        total_leads=len(job.get("leads") or []),
        errors=job.get("errors") or [],
    )


@app.get("/api/v1/leads/{job_id}", response_model=JobLeadsResponse)
async def get_leads(job_id: str):
    """Return processed leads, scores, and email drafts for a job."""
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    raw_leads = job.get("leads") or []
    leads_out = []
    for lead in raw_leads:
        leads_out.append(
            LeadOut(
                company_name=lead.get("company_name") or "",
                website=lead.get("website") or "",
                industry=lead.get("industry") or "",
                location=lead.get("location") or "",
                contact_email=lead.get("contact_email") or "",
                qualification_score=float(lead.get("qualification_score") or 0),
                email_mx_valid=bool(lead.get("email_mx_valid")),
                status=lead.get("status") or "",
                hitl_status=lead.get("hitl_status") or "",
                email_subject=lead.get("email_subject") or "",
                email_body=lead.get("email_body") or "",
                analysis_summary=lead.get("analysis_summary") or "",
            )
        )

    return JobLeadsResponse(
        job_id=job_id,
        status=job.get("status") or "unknown",
        leads=leads_out,
    )
