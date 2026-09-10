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


def make_story_lead(client: LLMClient, tier: str = "strong") -> Agent:
    alias = "openai_story_strong" if tier == "strong" else "openai_story_mini"
    model_resolved, _ = resolve_model("paid_api_lane", alias)
    return Agent(
        name="story_lead", lane="paid_api", client=client,
        model_alias=alias, model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
    )
