"""Paid-api lane: OpenAI + Gemini via LiteLLM, Direct credential topology (plan §3.2-3.3).

Cost is read from LiteLLM's PUBLIC cost interface (`litellm.completion_cost`),
never from `response._hidden_params` (final hygiene review, Appendix G #7) —
`_hidden_params` is an implementation detail LiteLLM does not guarantee.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import litellm

from ..usage import usd_to_microusd


@dataclass
class CallResult:
    content: str
    model_resolved: str
    input_tokens: int
    output_tokens: int
    billed_microusd: int
    latency_ms: int


class LiteLLMBackend:
    """lane = paid_api. One call = one CallResult; the caller turns that into a UsageRecord."""

    lane = "paid_api"

    def __init__(self, max_tokens: int = 2048):
        self.max_tokens = max_tokens

    def call(self, model: str, system_prompt: str, user_payload: str) -> CallResult:
        start = time.monotonic()
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            max_tokens=self.max_tokens,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        try:
            cost_usd = litellm.completion_cost(completion_response=response)
        except Exception:
            # LiteLLM doesn't have pricing for every model; the caller's budget
            # policy still runs off whatever this returns (0.0 in the worst case),
            # and the pre-flight estimate is the real backstop, not this figure.
            cost_usd = 0.0

        usage = response.usage
        return CallResult(
            content=response.choices[0].message.content or "",
            model_resolved=getattr(response, "model", model),
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            billed_microusd=usd_to_microusd(cost_usd),
            latency_ms=latency_ms,
        )
