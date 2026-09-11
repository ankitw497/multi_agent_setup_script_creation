"""Worker (Haiku, subscription lane) -- mechanical/lint work only (plan §2.1).

Never the deciding reviewer on story quality, technical correctness, voice,
or the final gate -- it shares a family with the Narration Lead, and the
whole point of multiple families is avoiding self-confirmation.
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
