"""SQLite engine and session factory for Agentic-Workflow."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "agentic_workflow.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


def init_db() -> None:
    """Create all tables if they do not exist; patch missing SQLite columns."""
    from sqlalchemy import text

    from db import models  # noqa: F401 — register models on Base.metadata

    Base.metadata.create_all(bind=engine)

    # Lightweight migration for newly added columns
    with engine.begin() as conn:
        cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(jobs)")).fetchall()
        }
        if "logs" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN logs TEXT DEFAULT ''"))


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
