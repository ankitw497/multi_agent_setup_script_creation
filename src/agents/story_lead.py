"""Story Lead (GPT, paid lane) -- source reasoning, archetype, planning, revision scope (plan §2).

Owns WHAT the story is and WHAT must change. Never writes final prose,
never clears its own unresolved failures (plan Appendix G #16 -- the
policy gate, not this agent, decides pass/fail).
"""
from __future__ import annotations

from config.loader import resolve_model
from llm.client import LLMClient

from .base import Agent

BASE_SYSTEM_PROMPT = (
    "You are the story reasoning lead for a technical YouTube explainer pipeline. "
    "You do not optimize for literary prose -- your job is to make the explanation "
    "logically inevitable. Never invent evidence to force an archetype; only use "
    "what the source material actually supports. A video has exactly one primary "
    "archetype, chosen from: mystery, build, experiment, derivation, foundation, "
    "framework. Local scenes may borrow another archetype's device without "
    "changing that primary arc. Prefer a question -> explanation -> payoff -> "
    "next-question progression. Preserve technical causality. When planning a "
    "revision, decide the minimum necessary repair and describe WHAT must change "
    "-- never write replacement prose yourself."
)


def make_story_lead(client: LLMClient, tier: str = "strong", alias_override: str | None = None) -> Agent:
    """`alias_override` lets a caller pin a specific `paid_api_lane` alias
    directly, overriding even this tier-based default.

    2026-09-16 (explicit user decision, STORY_IMPROVEMENT_PLAN.md Phase 4): the "strong"
    tier now resolves to `openai_story_strong_gpt56` (gpt-5.6-sol) -- previously
    `openai_story_strong` (gpt-4o). This OVERRIDES Phase 4's own completed A2/A2b
    comparison, which found gpt-5.6-sol produced a structurally LESS coherent plan (2
    genuine story-coherence hard failures gpt-4o didn't have) for 65% MORE cost, and
    explicitly recommended against promoting it. The user was shown that finding
    directly and chose to proceed anyway. `openai_story_strong` (gpt-4o) remains a
    live, fully-configured alias in `models.yaml` -- pass
    `alias_override="openai_story_strong"` to roll back to it for any run
    without touching this default."""
    alias = alias_override or ("openai_story_strong_gpt56" if tier == "strong" else "openai_story_mini")
    model_resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", alias)
    return Agent(
        name="story_lead", lane="paid_api", client=client,
        model_alias=alias, model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
        default_reasoning_effort=reasoning_effort,
        default_max_tokens=max_tokens,
    )
