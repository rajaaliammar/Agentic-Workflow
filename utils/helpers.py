"""Data cleaning & string manipulation utilities."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Ensure http(s) scheme and strip fragments / trailing junk."""
    if not url or not str(url).strip():
        return ""
    value = str(url).strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned).rstrip("/")


def truncate(text: str, max_len: int = 1000, suffix: str = "…") -> str:
    """Truncate text to max_len characters."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - len(suffix))] + suffix


def extract_json_block(text: str) -> Optional[dict[str, Any]]:
    """
    Extract a JSON object from model output, tolerating markdown fences.
    """
    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def format_pain_points(pain_points: list[Any]) -> str:
    """Render pain points as a bullet list for LLM prompts."""
    if not pain_points:
        return ""
    lines: list[str] = []
    for item in pain_points:
        if isinstance(item, dict):
            title = item.get("title") or "Pain point"
            severity = item.get("severity") or "medium"
            desc = item.get("description") or ""
            lines.append(f"- [{severity}] {title}: {desc}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def slugify(value: str) -> str:
    """Simple slug for filenames / lead keys."""
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "lead"
