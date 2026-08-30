"""
CLI runner for local batch execution & testing of Agentic-Workflow.

Examples:
    python main.py
    python main.py --industry "Fintech" --location "London" --max-leads 5
    python main.py --industry "DevTools" --auto-approve --framework AIDA
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from config.settings import get_settings
from core.graph import run_workflow
from tools.crm_tools import export_leads_csv, export_leads_json, sync_leads_snapshot
from utils.logger import logger, setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="agentic-workflow",
        description="Enterprise Lead Generation, Enrichment & Outreach Agent (CLI)",
    )
    parser.add_argument("--industry", "-i", default=settings.default_industry)
    parser.add_argument("--location", "-l", default=settings.default_location)
    parser.add_argument("--max-leads", "-n", type=int, default=settings.max_leads_per_run)
    parser.add_argument(
        "--framework",
        choices=["PAS", "AIDA"],
        default=settings.outreach_framework,
        help="Cold outreach copy framework",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=settings.dry_run,
        help="Draft only — do not send via Gmail",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Bypass HITL approval (testing / batch only)",
    )
    parser.add_argument("--export-csv", action="store_true", help="Write CSV export under data/exports")
    parser.add_argument("--export-json", action="store_true", help="Write JSON export under data/exports")
    parser.add_argument("--crm-sync", action="store_true", help="Write CRM snapshot under data/crm")
    parser.add_argument("--json", action="store_true", help="Print final state as JSON")
    return parser.parse_args(argv)


def _summarize(state: dict[str, Any]) -> str:
    leads = state.get("leads") or []
    lines = [
        f"Status:   {state.get('status')}",
        f"Step:     {state.get('step')}",
        f"Industry: {state.get('industry')}",
        f"Location: {state.get('location')}",
        f"Leads:    {len(leads)}",
        "",
    ]
    for i, lead in enumerate(leads, start=1):
        lines.append(
            f"{i}. {lead.get('company_name')} | "
            f"score={lead.get('qualification_score')} | "
            f"mx={lead.get('email_mx_valid')} | "
            f"status={lead.get('status')} | "
            f"hitl={lead.get('hitl_status')} | "
            f"{lead.get('website')}"
        )
        if lead.get("email_subject"):
            lines.append(f"   Subject: {lead.get('email_subject')}")
    errors = state.get("errors") or []
    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  - {e}" for e in errors)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info(
        "CLI start | industry={!r} location={!r} max={} auto_approve={} framework={}",
        args.industry,
        args.location,
        args.max_leads,
        args.auto_approve,
        args.framework,
    )

    try:
        final_state = run_workflow(
            industry=args.industry,
            location=args.location,
            max_leads=args.max_leads,
            dry_run=args.dry_run,
            auto_approve=args.auto_approve,
            outreach_framework=args.framework,
        )
    except Exception:
        logger.exception("Workflow failed")
        return 1

    leads = final_state.get("leads") or []
    if args.export_csv:
        export_leads_csv(leads)
    if args.export_json:
        export_leads_json(leads)
    if args.crm_sync:
        sync_leads_snapshot(leads)

    if args.json:
        print(json.dumps(final_state, indent=2, default=str))
    else:
        print(_summarize(final_state))
        if final_state.get("awaiting_human"):
            print(
                "\n[HITL] Pipeline paused for human approval. "
                "Use `streamlit run app.py` to Approve/Reject drafts."
            )

    return 0 if final_state.get("status") != "failed" else 2


if __name__ == "__main__":
    sys.exit(main())
