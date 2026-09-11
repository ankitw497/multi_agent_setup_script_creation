"""Narration Lead (Sonnet, subscription lane) -- spoken-language construction (plan §2).

Turns a validated story plan into natural spoken narration. Does not
select or replace the primary archetype. Reduces words, never causality
(plan §11.4's core editing rule) -- especially true during humanize, which
is a mode of this same agent, not a separate identity (plan §2.4).
"""
from __future__ import annotations

from config.loader import resolve_model
from llm.client import LLMClient

from .base import Agent

BASE_SYSTEM_PROMPT = (
    "You turn a validated story plan into natural spoken narration for a "
    "technical YouTube explainer. The story plan is authoritative -- you do "
    "not select or replace the primary archetype, and you do not invent new "
    "architecture. Write for listening, not silent reading: short-to-medium "
    "sentences, varied rhythm, concrete verbs, causal connectors (because, so, "
    "but, which means, that creates a problem, so we need, this solves). Do "
    "not merely read the screen -- narration explains the consequence of a "
    "visual, never restates it. When editing for brevity, reduce words, never "
    "the causal reasoning a mechanism needs to make sense. Respect every "
    "verified numeric value and assumption you are given -- never alter a "
    "number, and never add a technical claim that is not backed by the claims "
    "you were given."
)


def make_narration_lead(client: LLMClient) -> Agent:
    model_resolved, _, _ = resolve_model("subscription_lane", "sonnet")
    return Agent(
        name="narration_lead", lane="subscription", client=client,
        model_alias="sonnet", model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
    )
