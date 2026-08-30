"""Export leads to CSV/JSON & lightweight CRM-style persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config.settings import get_settings
from utils.logger import logger

_EXPORT_COLUMNS = [
    "company_name",
    "website",
    "linkedin_url",
    "industry",
    "location",
    "contact_name",
    "contact_email",
    "contact_title",
    "qualification_score",
    "email_valid",
    "email_mx_valid",
    "status",
    "hitl_status",
    "email_subject",
    "analysis_summary",
]


def _ensure_data_dir(path: Optional[Path] = None) -> Path:
    settings = get_settings()
    base = path or (settings.data_dir / "exports")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def leads_to_dataframe(leads: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize lead dicts into a tabular DataFrame for UI / export."""
    if not leads:
        return pd.DataFrame(columns=_EXPORT_COLUMNS)
    rows = []
    for lead in leads:
        row = {col: lead.get(col, "") for col in _EXPORT_COLUMNS}
        rows.append(row)
    return pd.DataFrame(rows)


def export_leads_csv(
    leads: list[dict[str, Any]],
    filename: Optional[str] = None,
    directory: Optional[Path] = None,
) -> Path:
    """Persist leads as CSV. Returns written path."""
    out_dir = _ensure_data_dir(directory)
    path = out_dir / (filename or f"leads_{_timestamp()}.csv")
    df = leads_to_dataframe(leads)
    df.to_csv(path, index=False)
    logger.info("Exported {} lead(s) to CSV {}", len(leads), path)
    return path


def export_leads_json(
    leads: list[dict[str, Any]],
    filename: Optional[str] = None,
    directory: Optional[Path] = None,
) -> Path:
    """Persist leads as JSON. Returns written path."""
    out_dir = _ensure_data_dir(directory)
    path = out_dir / (filename or f"leads_{_timestamp()}.json")
    path.write_text(json.dumps(leads, indent=2, default=str), encoding="utf-8")
    logger.info("Exported {} lead(s) to JSON {}", len(leads), path)
    return path


def sync_leads_snapshot(leads: list[dict[str, Any]], run_id: Optional[str] = None) -> Path:
    """
    Lightweight 'CRM sync' — write a dated snapshot under data/crm/.

    Replace with HubSpot/Salesforce connectors in production.
    """
    settings = get_settings()
    crm_dir = settings.data_dir / "crm"
    crm_dir.mkdir(parents=True, exist_ok=True)
    rid = run_id or _timestamp()
    path = crm_dir / f"snapshot_{rid}.json"
    payload = {
        "run_id": rid,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(leads),
        "leads": leads,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("CRM snapshot written | {} leads → {}", len(leads), path)
    return path
