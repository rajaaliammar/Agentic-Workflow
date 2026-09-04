"""SQLAlchemy ORM models for jobs and leads."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    """A workflow execution job."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    industry: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(64), default="processing", index=True)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    framework: Mapped[str] = mapped_column(String(32), default="PAS")
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    max_leads: Mapped[int] = mapped_column(Integer, default=3)
    errors: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    leads: Mapped[list[Lead]] = relationship(
        "Lead",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Lead(Base):
    """An enriched lead belonging to a job."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(512), default="")
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0)
    email_mx_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), default="")
    hitl_status: Mapped[str] = mapped_column(String(64), default="")
    email_subject: Mapped[str] = mapped_column(String(512), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    analysis_summary: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship("Job", back_populates="leads")
