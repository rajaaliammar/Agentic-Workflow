"""Data cleaning, string manipulation, and shared LLM utilities."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from groq import Groq
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq

from config.settings import get_settings
from utils.logger import logger

# Emergency fallback only when client.models.list() fails
_GROQ_EMERGENCY_MODELS = ["llama3-70b-8192", "llama3-8b-8192"]


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
    """Extract a JSON object from model output, tolerating markdown fences."""
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


def get_active_groq_models(client: Groq) -> list[str]:
    """Fetch live available model IDs from the Groq API."""
    try:
        response = client.models.list()
        return [m.id for m in response.data if m.id]
    except Exception as exc:
        logger.warning("Groq models.list() failed ({}); using emergency fallback", exc)
        return list(_GROQ_EMERGENCY_MODELS)


def get_llm(*, temperature: float | None = None, fast: bool = False) -> BaseChatModel:
    """
    Return a chat model based on `LLM_PROVIDER` in settings.

    - groq  → ChatGroq (first available model from API, or configured default)
    - other → ChatOpenAI
    """
    settings = get_settings()
    temp = 0.3 if temperature is None else temperature

    if settings.llm_provider.lower() == "groq":
        api_key = settings.groq_api_key.get_secret_value() or None
        client = Groq(api_key=api_key)
        models = get_active_groq_models(client)
        preferred = settings.groq_model_fast if fast else settings.groq_model
        model_name = preferred if preferred in models else (models[0] if models else preferred)
        return ChatGroq(
            groq_api_key=api_key,
            model_name=model_name,
            temperature=temp,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature if temperature is None else temperature,
        api_key=settings.openai_api_key.get_secret_value() or None,
    )


def invoke_llm(
    messages: list[BaseMessage],
    *,
    temperature: float | None = None,
    fast: bool = False,
) -> Any:
    """
    Invoke the configured LLM.

    For Groq: fetches active models via client.models.list(), then tries each
    until one succeeds. Falls back to emergency static models if the list call fails.
    """
    settings = get_settings()
    if settings.llm_provider.lower() != "groq":
        return get_llm(temperature=temperature, fast=fast).invoke(messages)

    api_key = settings.groq_api_key.get_secret_value()
    client = Groq(api_key=api_key)
    available_models = get_active_groq_models(client)

    # Prefer configured model first when set
    preferred = settings.groq_model_fast if fast else settings.groq_model
    if preferred and preferred not in available_models:
        available_models = [preferred, *available_models]
    elif preferred and available_models and available_models[0] != preferred:
        available_models = [preferred, *[m for m in available_models if m != preferred]]

    temp = 0.3 if temperature is None else temperature
    last_exception: BaseException | None = None

    for model_name in available_models:
        try:
            llm = ChatGroq(
                groq_api_key=api_key,
                model_name=model_name,
                temperature=temp,
            )
            return llm.invoke(messages)
        except Exception as e:
            last_exception = e
            continue

    if last_exception is not None:
        raise last_exception
    raise RuntimeError("No Groq models available")
