"""Gmail API authentication, draft creation, and dispatch."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from config.settings import get_settings
from utils.logger import logger

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]


def _build_raw_message(to: str, subject: str, body: str, sender: str) -> dict[str, str]:
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def _get_gmail_service() -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    settings = get_settings()
    creds_path = Path(settings.gmail_credentials_path)
    token_path = Path(settings.gmail_token_path)

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found at {creds_path}. "
            "Download OAuth client JSON from Google Cloud Console."
        )

    creds: Optional[Credentials] = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def create_draft(
    to: str,
    subject: str,
    body: str,
    sender: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """Create a Gmail draft (or simulate in dry_run)."""
    settings = get_settings()
    if dry_run is None:
        dry_run = settings.dry_run

    if dry_run:
        logger.info("DRY_RUN: would create draft to={} subject={!r}", to, subject)
        return {"id": "dry-run-draft", "message": {"id": "dry-run"}}

    from_addr = sender or settings.gmail_sender_email
    if not from_addr:
        raise ValueError("GMAIL_SENDER_EMAIL is not configured")

    service = _get_gmail_service()
    raw = _build_raw_message(to=to, subject=subject, body=body, sender=from_addr)
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": raw})
        .execute()
    )
    logger.info("Gmail draft created | id={} to={}", draft.get("id"), to)
    return draft


def send_email(
    to: str,
    subject: str,
    body: str,
    sender: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """Send an email via Gmail API (or simulate in dry_run)."""
    settings = get_settings()
    if dry_run is None:
        dry_run = settings.dry_run

    if dry_run:
        logger.info("DRY_RUN: would send email to={} subject={!r}", to, subject)
        return {"id": "dry-run", "labelIds": ["DRY_RUN"]}

    from_addr = sender or settings.gmail_sender_email
    if not from_addr:
        raise ValueError("GMAIL_SENDER_EMAIL is not configured")

    service = _get_gmail_service()
    payload = _build_raw_message(to=to, subject=subject, body=body, sender=from_addr)
    result = service.users().messages().send(userId="me", body=payload).execute()
    logger.info("Email sent | to={} id={}", to, result.get("id"))
    return result
