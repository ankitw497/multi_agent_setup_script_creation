"""Review Lead (Gemini, paid lane) -- adversarial critique, verification, grounding (plan §2).

Never rewrites, never defends the existing script. Its whole point is
disagreeing with the writer's family (Sonnet/Claude) from a different one.
"""
from __future__ import annotations

from config.loader import resolve_model
from llm.client import LLMClient

from .base import Agent

BASE_SYSTEM_PROMPT = (
    "You are an adversarial reviewer for a technical YouTube explainer pipeline. "
    "You do not defend the existing script, and you do not rewrite it -- you "
    "diagnose. Find the earliest point where a real viewer becomes confused, "
    "loses the causal thread, receives an unsupported claim, or sees a mismatch "
    "between narration and visual. Judge the script against its resolved primary "
    "archetype, never against a different one. Do not demand fake drama. "
    "Distinguish factual correctness, source fidelity, pedagogical correctness, "
    "and stylistic preference from each other -- never collapse them into one "
    "verdict. When you find a problem, describe it and why it matters and what "
    "must change -- never write replacement prose."
)


def make_review_lead(client: LLMClient, tier: str = "strong") -> Agent:
    alias = "gemini_review_strong" if tier == "strong" else "gemini_review_flash"
    model_resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", alias)
    return Agent(
        name="review_lead", lane="paid_api", client=client,
        model_alias=alias, model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
        default_reasoning_effort=reasoning_effort,
        default_max_tokens=max_tokens,
    )
