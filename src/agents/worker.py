"""Worker (Haiku, subscription lane) -- mechanical/lint work only (plan §2.1).

Never the deciding reviewer on story quality, technical correctness, voice,
or the final gate -- it shares a family with the Narration Lead, and the
whole point of multiple families is avoiding self-confirmation.

One nuance (STORY_IMPROVEMENT_PLAN.md Phase 13, resolving an external review's
pushback): the C4a/C4c/C4d cold-hook/cold-viewer/continuing-viewer cascades
(`review/cold_hook_critic.py`, `review/cold_viewer_critic.py`) DO ask worker
for a subjective judgement ("would this stop a scroll?", "does this feel
caused by what came before?"). This is not a violation of the rule above --
worker's verdict there is never the deciding one. It's a cheap, sampled FIRST
PASS that only ever escalates to an independent Gemini opinion when flagged
or low-confidence; worker never gets the final say on any of these checks,
the same "producer != validator" independence the rule above protects, just
applied as a cost-saving cascade rather than a single call. Keep this
cascade shape (cheap screen -> escalate) rather than routing cold-hook/
cold-viewer judgement straight to Gemini -- it's the same pattern C3/C4b
already use for the same reason, and channel volume here doesn't justify
giving up the cost discipline for a marginal cleanliness gain.
"""
from __future__ import annotations

from config.loader import resolve_model
from llm.client import LLMClient

from .base import Agent

BASE_SYSTEM_PROMPT = (
    "You are a mechanical worker for a YouTube script pipeline. You extract, "
    "classify, and lint -- you never judge story quality, technical correctness, "
    "voice quality, or whether a script is ready to publish. Follow the task "
    "instructions exactly and return only the requested structured output."
)


def make_worker(client: LLMClient) -> Agent:
    model_resolved, _, _ = resolve_model("subscription_lane", "haiku")
    return Agent(
        name="worker", lane="subscription", client=client,
        model_alias="haiku", model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
    )
