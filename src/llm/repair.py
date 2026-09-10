"""Builds the real Haiku-backed repair_fn (plan §3.4): repair always runs on
the free subscription lane, never on a paid model.

This exists because leaving callers to wire call_structured_paid/subscription
without a repair_fn is exactly the kind of thing that gets forgotten in
practice -- a real run hit this: a malformed JSON response from a paid call
raised immediately instead of being repaired, because no repair_fn had been
supplied. See llm/client.py::make_llm_client, which makes this the default
rather than an opt-in.
"""
from __future__ import annotations

from .backends.claude_cli import ClaudeCliBackend
from .structured import RepairFn

REPAIR_SYSTEM_PROMPT = (
    "You repair malformed JSON so it becomes valid and matches a given schema. "
    "Return ONLY the corrected JSON -- no prose, no markdown fences. Preserve "
    "every value from the original as faithfully as possible; only fix what is "
    "structurally broken (syntax errors, missing quotes/commas/brackets, a "
    "field that doesn't match the schema's type)."
)


def make_haiku_repair_fn(
    subscription_backend: ClaudeCliBackend | None = None, model_id: str = "claude-haiku-4-5-20251001",
) -> RepairFn:
    backend = subscription_backend or ClaudeCliBackend()

    def repair_fn(raw: str, error: str, json_schema: str) -> str:
        payload = (
            f"Broken output:\n{raw}\n\nValidation error:\n{error}\n\nTarget JSON Schema:\n{json_schema}"
        )
        result = backend.call(model_id, REPAIR_SYSTEM_PROMPT, payload, timeout_s=120)
        return result.content

    return repair_fn
