"""Dynamic rendering & scraping via Playwright, BeautifulSoup, and Firecrawl."""

from __future__ import annotations

from typing import Optional

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import get_settings
from utils.helpers import normalize_url
from utils.logger import logger


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _is_firecrawl_auth_error(exc: BaseException) -> bool:
    """Detect Firecrawl token / authorization failures."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "unauthorized",
            "invalid token",
            "authentication",
            "forbidden",
            "401",
            "403",
        )
    )


def scrape_with_firecrawl(url: str) -> Optional[str]:
    """
    Scrape via Firecrawl when configured.

    Returns None on skip, auth failure, or any error so callers can fall back.
    """
    settings = get_settings()
    api_key = settings.firecrawl_api_key.get_secret_value()
    if not api_key or api_key.startswith("fc-your-"):
        logger.debug("Firecrawl skipped for {} — no API key configured", url)
        return None

    try:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, formats=["markdown", "html"])

        if isinstance(result, dict):
            if result.get("success") is False:
                error_msg = str(result.get("error") or result.get("message") or result)
                if _is_firecrawl_auth_error(Exception(error_msg)):
                    logger.warning(
                        "Firecrawl unauthorized for {} — falling back to HTML scrape",
                        url,
                    )
                else:
                    logger.warning("Firecrawl error for {}: {}", url, error_msg)
                return None

            markdown = result.get("markdown")
            html = result.get("html") or ""
            content = markdown or (_clean_html(html) if html else "")
            if content.strip():
                return content
            return None

        text = str(result).strip()
        return text or None
    except Exception as exc:
        if _is_firecrawl_auth_error(exc):
            logger.warning(
                "Firecrawl auth failed for {} ({}); falling back to HTML scrape",
                url,
                exc,
            )
        else:
            logger.warning("Firecrawl failed for {}: {}", url, exc)
        return None


def scrape_with_httpx(url: str) -> Optional[str]:
    """Lightweight HTML fetch + BeautifulSoup parse (no browser)."""
    settings = get_settings()
    timeout = settings.scrape_timeout_seconds
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AgenticWorkflow/0.2; +https://localhost)"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
        content = _clean_html(response.text)
        return content if content.strip() else None
    except Exception as exc:
        logger.warning("HTTP scrape failed for {}: {}", url, exc)
        return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
def scrape_with_playwright(url: str) -> str:
    """Load a page with headless Chromium and return cleaned text."""
    settings = get_settings()
    timeout_ms = settings.scrape_timeout_seconds * 1000

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(400)
            html = page.content()
        finally:
            browser.close()
    return _clean_html(html)


def scrape_url(url: str) -> str:
    """
    Scrape a URL with graceful backend fallback.

    Order: Firecrawl → httpx/BeautifulSoup → Playwright

    Raises:
        ValueError: empty URL
        Exception: all backends fail
    """
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("URL is required")

    logger.info("Scraping {}", normalized)

    content = scrape_with_firecrawl(normalized)
    if content:
        logger.debug("Scraped {} via Firecrawl", normalized)
        return content

    content = scrape_with_httpx(normalized)
    if content:
        logger.debug("Scraped {} via httpx/BeautifulSoup", normalized)
        return content

    logger.info("Falling back to Playwright for {}", normalized)
    return scrape_with_playwright(normalized)
