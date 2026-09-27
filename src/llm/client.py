"""llm.call_structured(...) — the one interface story logic ever calls (plan §3).

Ties the two backends' raw CallResult/CliCallResult into: a validated
pydantic object, a UsageRecord (for the ledger), and the budget check that
must run before the call is allowed to happen at all.

This module deliberately does NOT know what an "agent" or a "pass" means
beyond the plain strings it's given — that vocabulary belongs to
orchestration/ and agents/, which call this.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from .backends.claude_cli import ClaudeCliBackend
from .backends.litellm_backend import LiteLLMBackend
from .budget import BudgetCounter
from .repair import make_haiku_repair_fn
from .structured import RepairFn, validate_with_repair
from .usage import UsageRecord, UsageLedger

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredCallResult:
    value: BaseModel
    usage_record: UsageRecord


def make_llm_client(run_id: str, ledger: UsageLedger, cwd: str | None = None) -> "LLMClient":
    """The one correct way to build an LLMClient for a real run -- ALWAYS
    wires in the Haiku repair_fn (plan §3.4), so a malformed paid-lane
    response is repaired for free instead of raising immediately. A real
    run hit exactly this gap when constructed by hand without one."""
    subscription_backend = ClaudeCliBackend(cwd=cwd)
    return LLMClient(
        run_id=run_id, ledger=ledger, subscription_backend=subscription_backend,
        repair_fn=make_haiku_repair_fn(subscription_backend),
    )


class LLMClient:
    """Wires budget -> backend -> structured validation -> usage record, for one run."""

    def __init__(
        self,
        run_id: str,
        ledger: UsageLedger,
        subscription_backend: ClaudeCliBackend | None = None,
        paid_backend: LiteLLMBackend | None = None,
        repair_fn: RepairFn | None = None,
    ):
        self.run_id = run_id
        self.ledger = ledger
        self.subscription_backend = subscription_backend or ClaudeCliBackend()
        self.paid_backend = paid_backend or LiteLLMBackend()
        self._repair_fn = repair_fn  # bound to a Haiku call by the caller in practice

    def call_structured_subscription(
        self,
        *,
        agent: str,
        pass_id: str,
        mode: str,
        model_alias: str,
        model_resolved: str,
        system_prompt: str,
        user_payload: str,
        schema: type[T],
        revision_cycle: int = 0,
        timeout_s: int | None = None,
        reasoning_effort: str | None = None,
    ) -> StructuredCallResult:
        """sonnet | haiku | opus — no budget check (quota, not dollars); still ledgered as
        notional cost. `reasoning_effort` maps to the CLI's own `--effort` flag (2026-09-24,
        confirmed live against claude-opus-5-5) -- None (sonnet/haiku's own config) omits
        the flag entirely, same "unset means provider default" rule the paid lane uses."""
        result = self.subscription_backend.call(
            model_resolved, system_prompt, user_payload,
            timeout_s=timeout_s, reasoning_effort=reasoning_effort,
        )
        value = self._validate(result.content, schema)
        record = UsageRecord(
            run_id=self.run_id,
            agent=agent,
            pass_id=pass_id,
            mode=mode,
            lane="subscription",
            model_alias=model_alias,
            model_resolved=result.model_resolved,
            revision_cycle=revision_cycle,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            notional_microusd=result.notional_microusd,
            latency_ms=result.latency_ms,
        )
        self.ledger.append(record)
        return StructuredCallResult(value=value, usage_record=record)

    def call_structured_paid(
        self,
        *,
        agent: str,
        pass_id: str,
        mode: str,
        model_alias: str,
        model: str,
        system_prompt: str,
        user_payload: str,
        schema: type[T],
        budget: BudgetCounter,
        estimated_usd: float,
        revision_cycle: int = 0,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        images: list[str] | None = None,
        timeout_s: float | None = None,
        enable_web_search: bool = False,
    ) -> StructuredCallResult:
        """gpt | gemini — hard-gated by a local BudgetCounter (plan §3.2).

        reasoning_effort should be sourced from config/models.yaml per alias
        (e.g. "none" for the cheap cascade tier — see litellm_backend.py for why).
        max_tokens overrides the backend's default for passes with a
        structurally large output (A2's full StoryPlan) — see
        litellm_backend.py's default-bump comment for the real failure this fixes.
        images (V1C, C3 visual critic) are base64 data URIs, forwarded as-is —
        this client has no opinion on image content, only on wiring it through.
        enable_web_search (STORY_IMPROVEMENT_PLAN.md Phase 23): real, hosted Gemini web
        search for the exact call it's set on -- see litellm_backend.py for the real schema
        and cost implications. Forwarded as-is; this client has no opinion on when it's used,
        only on wiring it through (C2a's own claim-verification call sets it, nothing else
        does today).
        """
        budget.preflight_check(estimated_usd)

        result = self.paid_backend.call(
            model, system_prompt, user_payload, reasoning_effort,
            max_tokens=max_tokens, images=images, timeout_s=timeout_s,
            enable_web_search=enable_web_search,
        )
        # 2026-09-16, found live (Phase 17 interrupt-and-resume verification): logging used to
        # happen AFTER `budget.record_spend()`, so a call that pushed spend past the hard cap
        # raised `BudgetExceeded` before its `UsageRecord` was ever built or appended -- the
        # real money spent on that exact call vanished from `usage.jsonl` with no record
        # anywhere except the exception's own message text. Confirmed live: a real gpt-5.6-sol
        # A2 call billed $0.266102 and crashed the run, but `usage.jsonl` showed only the 3
        # calls before it ($0.1656 total) -- the single most expensive call of the run was the
        # one silently missing from its own cost audit trail. Log unconditionally, the moment
        # real cost is known, before any budget-cap check gets a chance to raise and lose it.
        record = UsageRecord(
            run_id=self.run_id,
            agent=agent,
            pass_id=pass_id,
            mode=mode,
            lane="paid_api",
            model_alias=model_alias,
            model_resolved=result.model_resolved,
            revision_cycle=revision_cycle,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            reasoning_tokens=result.reasoning_tokens,
            billed_microusd=result.billed_microusd,
            latency_ms=result.latency_ms,
        )
        self.ledger.append(record)
        budget.record_spend(result.billed_microusd)  # raises BudgetExceeded past hard_cap

        value = self._validate(result.content, schema)
        return StructuredCallResult(value=value, usage_record=record)

    def _validate(self, raw: str, schema: type[T]) -> T:
        if self._repair_fn is not None:
            # warn_fn=print (PIPELINE_AUDIT_2026-09-17.md finding #10): this layer has no
            # `log` callback threaded down from run_pipeline.py (and adding one here would
            # touch every call site between here and there) -- `print` reaches the same
            # console output `log=print`'s own default already writes to, the cheapest way
            # to make a real repair-fidelity warning actually visible without new plumbing.
            return validate_with_repair(raw, schema, self._repair_fn, warn_fn=print)
        from .structured import validate

        return validate(raw, schema)
