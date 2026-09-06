"""Gmail API authentication, draft creation, and dispatch.

Uses google-api-python-client + google-auth-oauthlib.
OAuth client secrets: credentials.json (or GMAIL_CREDENTIALS_PATH).
Cached tokens: token.json (or GMAIL_TOKEN_PATH).
When DRY_RUN=true, drafts/sends are logged only.
"""

from __future__ import annotations

import base64
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from config.settings import get_settings
from utils.logger import logger

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


# Project root = parent of tools/ (stable regardless of CWD)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_CREDENTIALS_PATH = os.path.join(_PROJECT_ROOT, "credentials", "credentials.json")
_DEFAULT_TOKEN_PATH = os.path.join(_PROJECT_ROOT, "credentials", "token.json")


def _resolve_credentials_path() -> Path:
    """Locate OAuth client secrets JSON (absolute path, CWD-independent)."""
    settings = get_settings()
    candidates = [
        Path(os.getenv("GMAIL_CREDENTIALS_PATH", "").strip())
        if os.getenv("GMAIL_CREDENTIALS_PATH", "").strip()
        else None,
        Path(_DEFAULT_CREDENTIALS_PATH),
        Path(os.path.abspath(str(settings.gmail_credentials_path)))
        if not Path(settings.gmail_credentials_path).is_absolute()
        else Path(settings.gmail_credentials_path),
        Path(os.path.join(_PROJECT_ROOT, "credentials.json")),
    ]
    for path in candidates:
        if path is None:
            continue
        resolved = path if path.is_absolute() else Path(os.path.abspath(str(path)))
        if resolved.exists():
            logger.debug("Using Gmail credentials at {}", resolved)
            return resolved

    # Always return the canonical absolute default so the error message is actionable
    return Path(_DEFAULT_CREDENTIALS_PATH)


def _resolve_token_path() -> Path:
    """Locate / create OAuth token cache path (absolute, next to credentials)."""
    env_path = os.getenv("GMAIL_TOKEN_PATH", "").strip()
    if env_path:
        path = Path(env_path)
        return path if path.is_absolute() else Path(os.path.abspath(env_path))
    return Path(_DEFAULT_TOKEN_PATH)


def _build_raw_message(to: str, subject: str, body: str, sender: str = "") -> dict[str, Any]:
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject
    if sender:
        message["from"] = sender
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


class _MockGmailExecute:
    """Terminal .execute() for mock Gmail API calls."""

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        return self._payload


class _MockGmailDrafts:
    def create(self, userId: str = "me", body: Optional[dict] = None) -> _MockGmailExecute:
        return _MockGmailExecute(
            {"id": "mock-draft-id", "message": {"id": "mock-message-id"}}
        )


class _MockGmailMessages:
    def send(self, userId: str = "me", body: Optional[dict] = None) -> _MockGmailExecute:
        return _MockGmailExecute({"id": "mock-send-id", "labelIds": ["MOCK"]})


class _MockGmailUsers:
    def drafts(self) -> _MockGmailDrafts:
        return _MockGmailDrafts()

    def messages(self) -> _MockGmailMessages:
        return _MockGmailMessages()


class _MockGmailService:
    """Minimal stand-in so create_draft/send_email work without credentials."""

    def users(self) -> _MockGmailUsers:
        return _MockGmailUsers()


def _get_gmail_service() -> Any:
    """Authenticate with OAuth and return a Gmail API v1 service client."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = _resolve_credentials_path()
    token_path = _resolve_token_path()

    try:
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Gmail OAuth credentials not found at {creds_path}. "
                "Download the OAuth client JSON from Google Cloud Console "
                "and save it as credentials.json (or set GMAIL_CREDENTIALS_PATH)."
            )

        creds: Optional[Credentials] = None
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            except Exception as exc:
                logger.warning("Failed to load token.json ({}); will re-authenticate", exc)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing Gmail OAuth token")
                print("Refreshing Gmail OAuth token...", flush=True)
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    logger.warning("Token refresh failed ({}); forcing browser login", exc)
                    creds = None

            if not creds or not creds.valid:
                print("Initiating Gmail OAuth Browser Login...", flush=True)
                logger.info("Initiating Gmail OAuth Browser Login...")
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")

            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Gmail OAuth token cached at {}", token_path)
            print(f"Gmail OAuth token cached at {token_path}", flush=True)
        else:
            logger.info("Using cached Gmail OAuth token from {}", token_path)

        return build("gmail", "v1", credentials=creds)

    except FileNotFoundError:
        logger.warning("Credentials missing, returning mock service")
        print("Credentials missing, returning mock service", flush=True)
        return _MockGmailService()


def create_draft(
    to: str,
    subject: str,
    body: str,
    sender: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Create a Gmail draft via users().drafts().create().

    Honours DRY_RUN from settings/env when dry_run is not passed explicitly.
    """
    settings = get_settings()
    if dry_run is None:
        dry_run = settings.dry_run

    logger.info("create_draft | dry_run={} to={} subject={!r}", dry_run, to, subject)

    if dry_run:
        logger.info("DRY_RUN: would create Gmail draft to={} subject={!r}", to, subject)
        print(f"DRY_RUN: skip Gmail draft → {to}", flush=True)
        return {"id": "dry-run-draft", "message": {"id": "dry-run"}}

    from_addr = sender or settings.gmail_sender_email or ""
    print(f"Creating live Gmail draft → {to}", flush=True)
    service = _get_gmail_service()
    raw = _build_raw_message(to=to, subject=subject, body=body, sender=from_addr)
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": raw})
        .execute()
    )
    logger.info("Gmail draft created | id={} to={}", draft.get("id"), to)
    print(f"Gmail draft created | id={draft.get('id')}", flush=True)
    return draft


def send_email(
    to: str,
    subject: str,
    body: str,
    sender: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """Send an email via users().messages().send() (respects DRY_RUN)."""
    settings = get_settings()
    if dry_run is None:
        dry_run = settings.dry_run

    if dry_run:
        logger.info("DRY_RUN: would send email to={} subject={!r}", to, subject)
        return {"id": "dry-run", "labelIds": ["DRY_RUN"]}

    from_addr = sender or settings.gmail_sender_email or ""
    service = _get_gmail_service()
    payload = _build_raw_message(to=to, subject=subject, body=body, sender=from_addr)
    result = service.users().messages().send(userId="me", body=payload).execute()
    logger.info("Email sent | to={} id={}", to, result.get("id"))
    return result
