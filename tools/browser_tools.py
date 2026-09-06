"""Dynamic rendering & scraping via Playwright, BeautifulSoup, and Firecrawl."""

from __future__ import annotations

from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config.settings import get_settings
from utils.helpers import normalize_url
from utils.logger import logger

# Hard cap so discovery never hangs the pipeline
_MAX_SCRAPE_TIMEOUT_SEC = 8


def _scrape_timeout_seconds() -> int:
    settings = get_settings()
    return max(3, min(int(settings.scrape_timeout_seconds or 8), _MAX_SCRAPE_TIMEOUT_SEC))


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _is_firecrawl_auth_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("unauthorized", "invalid token", "authentication", "forbidden", "401", "403")
    )


def scrape_with_firecrawl(url: str) -> Optional[str]:
    """Scrape via Firecrawl when configured. Returns None on skip/failure."""
    settings = get_settings()
    api_key = settings.firecrawl_api_key.get_secret_value()
    if not api_key or api_key.startswith("fc-your-"):
        return None

    try:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, formats=["markdown", "html"])
        if isinstance(result, dict):
            if result.get("success") is False:
                logger.warning("Firecrawl error for {}: {}", url, result.get("error") or result)
                return None
            markdown = result.get("markdown")
            html = result.get("html") or ""
            content = markdown or (_clean_html(html) if html else "")
            return content if content and content.strip() else None
        text = str(result).strip()
        return text or None
    except Exception as exc:
        if _is_firecrawl_auth_error(exc):
            logger.warning("Firecrawl auth failed for {} ({}); falling back", url, exc)
        else:
            logger.warning("Firecrawl failed for {}: {}", url, exc)
        return None


def scrape_with_httpx(url: str) -> Optional[str]:
    """Lightweight HTML fetch + BeautifulSoup (preferred over Playwright)."""
    timeout = _scrape_timeout_seconds()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AgenticWorkflow/0.2; +https://localhost)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
        content = _clean_html(response.text)
        return content if content.strip() else None
    except Exception as exc:
        logger.warning("HTTP scrape failed for {} ({}s timeout): {}", url, timeout, exc)
        return None


def scrape_with_playwright(url: str) -> Optional[str]:
    """
    Load a page with headless Chromium under a hard timeout (max 8s).

    Returns None on timeout/failure so the pipeline can continue.
    """
    timeout_ms = _scrape_timeout_seconds() * 1000
    logger.info("Playwright scrape {} | timeout={}ms", url, timeout_ms)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                html = page.content()
            finally:
                browser.close()
        content = _clean_html(html)
        return content if content.strip() else None
    except Exception as exc:
        logger.warning("Playwright scrape failed/timed out for {}: {}", url, exc)
        return None


def scrape_url(url: str) -> str:
    """
    Scrape a URL with fail-fast backends (max ~8s each).

    Order: Firecrawl → httpx → Playwright (optional last resort)
    Returns empty string if all backends fail (does not hang the graph).
    """
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("URL is required")

    logger.info("Scraping {} (timeout={}s)", normalized, _scrape_timeout_seconds())

    content = scrape_with_firecrawl(normalized)
    if content:
        return content

    content = scrape_with_httpx(normalized)
    if content:
        return content

    content = scrape_with_playwright(normalized)
    if content:
        return content

    logger.warning("All scrape backends failed for {} — continuing with empty content", normalized)
    return ""
