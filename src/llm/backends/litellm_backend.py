"""Paid-api lane: OpenAI + Gemini via LiteLLM, Direct credential topology (plan §3.2-3.3).

Cost is read from LiteLLM's PUBLIC cost interface (`litellm.completion_cost`),
never from `response._hidden_params` (final hygiene review, Appendix G #7) —
`_hidden_params` is an implementation detail LiteLLM does not guarantee.

`reasoning_effort` exists because of a real finding (2026-09-10, config/models.yaml):
Gemini's current flash-tier model reasons by default, and a small `max_tokens`
budget can be consumed almost entirely by hidden reasoning tokens, returning
empty `content` for real money (observed: 95 of 96 output tokens on one
throwaway reply). The cheap cascade tier (C3/C4b/C5) MUST pass
`reasoning_effort="none"`; the strong tier leaves it unset on purpose.
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
    reasoning_tokens: int
    billed_microusd: int
    latency_ms: int


class LiteLLMBackend:
    """lane = paid_api. One call = one CallResult; the caller turns that into a UsageRecord."""

    lane = "paid_api"

    def __init__(self, max_tokens: int = 4096, num_retries: int = 3, timeout_s: float = 300.0):
        # 4096 default (raised from 2048, 2026-09-10): a real A2 call on a
        # source_units-enriched payload returned a truncated ("Unterminated
        # string") response at 2048 -- a full multi-scene StoryPlan (20-30
        # ScenePlan entries plus beats/hook/cta/ending) is structurally the
        # largest output in the system by a wide margin, and even the Haiku
        # repair path can't recover a response that was cut off mid-string.
        # A2 itself additionally overrides this per-call (see story_planner.py).
        self.max_tokens = max_tokens
        # num_retries (2026-09-11, ERR-032): litellm.completion() does NOT
        # retry by default -- a real ~45-minute, ~$0.71 run died on a single
        # transient Gemini 503 ("high demand, try again later") at the very
        # last call before completion, with the whole run lost. Passing
        # num_retries here activates litellm's own tenacity-backed retry
        # classification (backs off and retries RateLimitError/Timeout/
        # ServiceUnavailableError-class failures; never retries a genuine
        # AuthenticationError/BadRequestError, which would just waste the
        # same call three times over).
        self.num_retries = num_retries
        # timeout_s (2026-09-12, real gpt-5.6-sol comparison run): num_retries
        # above only classifies and backs off an ALREADY-RAISED exception --
        # litellm.completion() had no `timeout` at all, so a connection that
        # simply never responds (no error, no retry trigger) blocks forever.
        # A real run hung 6+ hours on exactly this before being killed by
        # hand. 300s is well above every observed real call's latency
        # (longest seen: a 149s gpt-5.6-sol A2 call) but still loud -- a
        # genuinely slow call raises litellm.Timeout, which IS one of the
        # exception classes num_retries backs off and retries.
        self.timeout_s = timeout_s

    def call(
        self,
        model: str,
        system_prompt: str,
        user_payload: str,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        images: list[str] | None = None,
        timeout_s: float | None = None,
    ) -> CallResult:
        start = time.monotonic()
        extra_kwargs = {}
        if reasoning_effort is not None:
            extra_kwargs["reasoning_effort"] = reasoning_effort

        # images (V1C, C3 visual critic): a list of data URIs. When absent,
        # the user message is a plain string -- byte-for-byte the same
        # request shape every existing caller has always sent. When present,
        # it becomes an OpenAI-style multimodal content-block list, which
        # LiteLLM normalizes for Gemini itself -- no provider-specific
        # branching needed here.
        user_content: str | list[dict] = user_payload
        if images:
            user_content = [{"type": "text", "text": user_payload}] + [
                {"type": "image_url", "image_url": {"url": uri}} for uri in images
            ]

        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            num_retries=self.num_retries,
            timeout=timeout_s if timeout_s is not None else self.timeout_s,
            **extra_kwargs,
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
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(details, "reasoning_tokens", None) or 0

        return CallResult(
            content=response.choices[0].message.content or "",
            model_resolved=getattr(response, "model", model),
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            reasoning_tokens=reasoning_tokens,
            billed_microusd=usd_to_microusd(cost_usd),
            latency_ms=latency_ms,
        )
