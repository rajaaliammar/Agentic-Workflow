"""LLM prompt templates for analysis and outreach."""

from prompts.analyzer_prompts import ANALYZER_SYSTEM_PROMPT, build_analyzer_user_prompt
from prompts.outreach_prompts import OUTREACH_SYSTEM_PROMPT, build_outreach_user_prompt

__all__ = [
    "ANALYZER_SYSTEM_PROMPT",
    "build_analyzer_user_prompt",
    "OUTREACH_SYSTEM_PROMPT",
    "build_outreach_user_prompt",
]
