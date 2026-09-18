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


class LiteLLMModelMismatch(RuntimeError):
    """PIPELINE_AUDIT_2026-09-17.md finding #8: the paid lane had no equivalent of
    `claude_cli.py::ModelMismatch` -- "pin the exact model, never trust a moving alias"
    (plan Appendix E #8) was only ever enforced on the subscription lane. A real config
    comment already flags this exact risk (`gemini_review_strong`'s "-preview" in the id
    means Google can retire/rename this one too"). Unlike `ModelMismatch`'s own exact-string
    comparison, this uses a prefix match (see `_same_model_family`'s own docstring) -- a real
    provider routinely echoes back a fully-versioned name (e.g. "gpt-4o-mini-2024-07-18" for
    a request of "gpt-4o-mini"), which is the SAME model, not a substitution."""


def _model_family(model_id: str) -> str:
    """Strip a "provider/" prefix (litellm's own request syntax, e.g. "gemini/gemini-3.1-
    pro-preview") -- the resolved model in a response is not guaranteed to echo it back."""
    return model_id.rsplit("/", 1)[-1]


def _strip_trailing_version_suffix(name: str) -> str:
    """Drop trailing hyphen-separated tokens that are purely numeric (a date like
    "2024-07-18" splits into three such tokens; a build tag like "001" is one) -- these are
    a provider's own versioning, never a distinguishing part of the model name itself.
    "gpt-4o-mini-2024-07-18" -> "gpt-4o-mini"; "gpt-4o-mini" is already bare and unchanged;
    "gpt-4o" is unchanged too since "4o" isn't purely digits."""
    tokens = name.split("-")
    while len(tokens) > 1 and tokens[-1].isdigit():
        tokens.pop()
    return "-".join(tokens)


def _same_model_family(requested: str, resolved: str) -> bool:
    """Compares the two names with any trailing provider version/date suffix stripped, not
    exact equality on the raw strings and not a bare prefix match. Exact equality (this
    project's own `ModelMismatch` precedent on the Claude CLI backend) would false-positive
    on a real, confirmed case: requesting "gpt-4o-mini" can come back resolved as
    "gpt-4o-mini-2024-07-18", the provider's own fully-dated version of the SAME model, not a
    substitution. A bare prefix match (`a.startswith(b)`) over-corrected: it was found on
    review to also treat "gpt-4o" and "gpt-4o-mini" as the same family, since one is a
    literal string-prefix of the other -- yet both are real, distinct, already-configured
    models in config/models.yaml, so a silent substitution between them would pass silently.
    Stripping only a trailing numeric-token suffix (never "mini", never a hyphenated word)
    closes that hole while still absorbing the real dated-suffix case."""
    a = _strip_trailing_version_suffix(_model_family(requested))
    b = _strip_trailing_version_suffix(_model_family(resolved))
    return a == b


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
        # Also set litellm's own global default (2026-09-14): a real Gemini/
        # Vertex call raised "litellm.Timeout: Connection timed out after
        # None seconds" -- our own per-call `timeout=` kwarg is passed
        # correctly (confirmed in litellm's source), but the exact code path
        # that particular call took didn't reflect it in the exception's own
        # message, and litellm's own global default is 6000s if never set.
        # This is belt-and-suspenders, not a confirmed root-cause fix -- a
        # concurrent run against the same source completed cleanly at the
        # same time, so this may simply be transient network/API flakiness
        # rather than a real gap in our own request. Harmless either way.
        litellm.request_timeout = timeout_s

    def call(
        self,
        model: str,
        system_prompt: str,
        user_payload: str,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        images: list[str] | None = None,
        timeout_s: float | None = None,
        enable_web_search: bool = False,
    ) -> CallResult:
        start = time.monotonic()
        extra_kwargs = {}
        if reasoning_effort is not None:
            extra_kwargs["reasoning_effort"] = reasoning_effort
        # enable_web_search (STORY_IMPROVEMENT_PLAN.md Phase 23, 2026-09-16): real, hosted,
        # single-call web search -- litellm.supports_web_search() confirms both Gemini models
        # this pipeline uses (gemini-3.1-pro-preview, gemini-3.6-flash) support it, and the
        # provider does the search-then-answer internally, no multi-turn orchestration needed
        # here. `tools=[{"googleSearch": {}}]` is the real schema litellm's own Gemini tool-
        # transformation layer expects (confirmed by reading
        # litellm/llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py directly, not
        # assumed). Byte-for-byte the same request shape as every existing caller when False
        # (the default) -- no `tools` key at all, matching the same care already taken for
        # `images` above.
        if enable_web_search:
            extra_kwargs["tools"] = [{"googleSearch": {}}]

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

        resolved_model = getattr(response, "model", None)
        if resolved_model and not _same_model_family(model, resolved_model):
            raise LiteLLMModelMismatch(
                f"requested model {model!r} but the provider resolved {resolved_model!r} — "
                "refusing to proceed on an unpinned/moved alias (plan Appendix E #8)"
            )

        return CallResult(
            content=response.choices[0].message.content or "",
            model_resolved=resolved_model or model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            reasoning_tokens=reasoning_tokens,
            billed_microusd=usd_to_microusd(cost_usd),
            latency_ms=latency_ms,
        )
