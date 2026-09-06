# Agentic-Workflow

Enterprise **Autonomous Lead Generation, Enrichment & Outreach Agent**.

A modular LangGraph system that discovers business leads, performs deep website pain-point analysis, validates emails via MX records, generates customized outreach (PAS / AIDA), and routes drafts through a **Human-in-the-Loop (HITL)** Streamlit review UI before Gmail dispatch.

    
## Pipeline


```
Discovery → Analysis → Verification → Copywriting → HITL Approval → Dispatch
   │            │            │             │              │            │
 URLs /      Pain points   MX + score   Cold email    Approve /     Gmail
 companies   & tech audit  qualify      + LinkedIn    Reject        API
```

Conditional edges skip dispatch when leads fail verification or when a human rejects drafts.

## Tech Stack

| Layer | Libraries |
|-------|-----------|
| Orchestration | LangGraph, LangChain OpenAI |
| Scraping | Playwright, BeautifulSoup4, Firecrawl |
| Validation | dnspython (MX), Pydantic |
| Outreach | Gmail API (`google-api-python-client`) |
| HITL UI | Streamlit, pandas |
| Config / Logs | pydantic-settings, python-dotenv, loguru |

## Quick Start

```bash
cd Agentic-Workflow
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Set OPENAI_API_KEY, optional FIRECRAWL_API_KEY, Gmail OAuth paths
```

### Streamlit Control Center (HITL)

```bash
streamlit run app.py
```

Use the sidebar for **Industry** and **Location**, run the pipeline, review leads in the data table, preview drafted emails, then **Approve** or **Reject** before send.

### CLI batch run

```bash
python main.py --industry "Fintech" --location "London" --max-leads 5
python main.py --industry "DevTools" --auto-approve   # skip HITL (testing only)
```

## Project Structure

```
Agentic-Workflow/
├── app.py                      # Streamlit HITL Control Center
├── main.py                     # CLI batch runner
├── config/settings.py          # Pydantic Settings
├── core/
│   ├── state.py                # LeadState & graph memory
│   ├── nodes.py                # LangGraph execution nodes
│   └── graph.py                # Workflow + HITL conditional edges
├── agents/                     # Discovery, analyzer, verification, copywriter
├── tools/                      # Browser, MX validator, Gmail, CRM export
├── prompts/                    # Analyzer & outreach (PAS/AIDA) prompts
└── utils/                      # loguru logger + helpers
```

## Safety & Compliance

- `DRY_RUN=true` and `REQUIRE_HUMAN_APPROVAL=true` by default.
- Never commit `.env`, OAuth tokens, or `credentials/`.
- Respect robots.txt / ToS when scraping; keep send volumes within Gmail quotas and local regulations (CAN-SPAM / GDPR).

## License

MIT
