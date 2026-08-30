"""Discovery agent — lead discovery & URL extraction."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from core.state import LeadState, LeadStatus
from tools.browser_tools import scrape_url
from utils.helpers import normalize_url, truncate
from utils.logger import logger

# Curated seed set so demos / CI work offline
_DEMO_COMPANIES: list[dict[str, Any]] = [
    {
        "company_name": "Notion",
        "website": "https://www.notion.so",
        "linkedin_url": "https://www.linkedin.com/company/notionhq",
        "industry": "Productivity SaaS",
        "location": "San Francisco, USA",
        "contact_email": "hello@notion.so",
    },
    {
        "company_name": "Linear",
        "website": "https://linear.app",
        "linkedin_url": "https://www.linkedin.com/company/linearapp",
        "industry": "Developer Tools",
        "location": "San Francisco, USA",
        "contact_email": "hi@linear.app",
    },
    {
        "company_name": "Stripe",
        "website": "https://stripe.com",
        "linkedin_url": "https://www.linkedin.com/company/stripe",
        "industry": "Fintech",
        "location": "San Francisco, USA",
        "contact_email": "support@stripe.com",
    },
    {
        "company_name": "Vercel",
        "website": "https://vercel.com",
        "linkedin_url": "https://www.linkedin.com/company/vercel",
        "industry": "Developer Tools",
        "location": "San Francisco, USA",
        "contact_email": "contact@vercel.com",
    },
    {
        "company_name": "HubSpot",
        "website": "https://www.hubspot.com",
        "linkedin_url": "https://www.linkedin.com/company/hubspot",
        "industry": "CRM / Marketing",
        "location": "Cambridge, USA",
        "contact_email": "info@hubspot.com",
    },
    {
        "company_name": "Monzo",
        "website": "https://monzo.com",
        "linkedin_url": "https://www.linkedin.com/company/monzo-bank",
        "industry": "Fintech",
        "location": "London, UK",
        "contact_email": "help@monzo.com",
    },
]


def _filter_demo(industry: str, location: str, limit: int) -> list[dict[str, Any]]:
    tokens = [t.lower() for t in f"{industry} {location}".split() if len(t) > 2]
    scored: list[tuple[int, dict[str, Any]]] = []
    for company in _DEMO_COMPANIES:
        blob = " ".join(
            [
                company.get("company_name", ""),
                company.get("industry", ""),
                company.get("location", ""),
            ]
        ).lower()
        score = sum(1 for t in tokens if t in blob)
        scored.append((score, company))
    scored.sort(key=lambda x: x[0], reverse=True)
    matched = [c for s, c in scored if s > 0]
    return (matched or _DEMO_COMPANIES)[:limit]


def _search_live(industry: str, location: str, limit: int) -> list[dict[str, Any]]:
    query = f"{industry} companies in {location}"
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AgenticWorkflow/0.2)"}
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[dict[str, Any]] = []
        for result in soup.select(".result")[:limit]:
            anchor = result.select_one("a.result__a")
            snippet = result.select_one(".result__snippet")
            if not anchor or not anchor.get("href"):
                continue
            href = normalize_url(anchor["href"])
            title = anchor.get_text(strip=True)
            results.append(
                {
                    "company_name": title.split(" - ")[0].split(" | ")[0][:80],
                    "website": href,
                    "linkedin_url": "",
                    "industry": industry,
                    "location": location,
                    "contact_email": "",
                    "description": snippet.get_text(strip=True) if snippet else "",
                }
            )
        return results
    except Exception as exc:
        logger.warning("Live discovery search failed: {}", exc)
        return []


def run_discovery(state: LeadState) -> dict[str, Any]:
    """
    LangGraph node body: discover candidate companies and scrape landing pages.
    """
    industry = state.get("industry") or "B2B SaaS"
    location = state.get("location") or "United States"
    max_leads = int(state.get("max_leads") or 10)
    messages: list[str] = []
    errors: list[str] = []

    messages.append(f"Discovering leads | industry={industry!r} location={location!r}")
    logger.info("Discovery agent | industry={!r} location={!r} max={}", industry, location, max_leads)

    candidates = _search_live(industry, location, max_leads)
    if not candidates:
        candidates = _filter_demo(industry, location, max_leads)
        messages.append(f"Using {len(candidates)} demo seed lead(s)")
    else:
        messages.append(f"Found {len(candidates)} live candidate(s)")

    leads: list[dict[str, Any]] = []
    for candidate in candidates:
        website = normalize_url(candidate.get("website") or "")
        company = candidate.get("company_name") or "Unknown"
        lead: dict[str, Any] = {
            **candidate,
            "website": website,
            "industry": candidate.get("industry") or industry,
            "location": candidate.get("location") or location,
            "status": LeadStatus.DISCOVERED.value,
            "scraped_content": "",
            "hitl_status": "pending",
        }

        if not website:
            lead["status"] = LeadStatus.FAILED.value
            errors.append(f"No website for {company}")
            leads.append(lead)
            continue

        try:
            content = scrape_url(website)
            lead["scraped_content"] = truncate(content, 50_000)
            messages.append(f"Scraped {company} ({website})")
            logger.info("Scraped {} — {} chars", company, len(content))
        except Exception as exc:
            lead["status"] = LeadStatus.FAILED.value
            errors.append(f"Scrape failed for {website}: {exc}")
            logger.warning("Scrape failed for {}: {}", website, exc)

        leads.append(lead)

    return {
        "leads": leads,
        "messages": messages,
        "errors": errors,
        "step": "discovery",
    }
