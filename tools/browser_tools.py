"""Dynamic rendering & scraping via Playwright, BeautifulSoup, and Firecrawl."""

from __future__ import annotations

from typing import Optional

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


def scrape_with_firecrawl(url: str) -> Optional[str]:
    """Scrape via Firecrawl when configured. Returns None on skip/failure."""
    settings = get_settings()
    api_key = settings.firecrawl_api_key.get_secret_value()
    if not api_key:
        return None
    try:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, params={"formats": ["markdown", "html"]})
        if isinstance(result, dict):
            return result.get("markdown") or _clean_html(result.get("html") or "")
        return str(result)
    except Exception as exc:
        logger.warning("Firecrawl failed for {}: {}", url, exc)
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
    Scrape a URL — prefer Firecrawl when keyed, otherwise Playwright.

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
        return content
    return scrape_with_playwright(normalized)
