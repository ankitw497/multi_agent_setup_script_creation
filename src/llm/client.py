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
from .structured import RepairFn, validate_with_repair
from .usage import UsageRecord, UsageLedger

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredCallResult:
    value: BaseModel
    usage_record: UsageRecord


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
    ) -> StructuredCallResult:
        """sonnet | haiku — no budget check (quota, not dollars); still ledgered as notional cost."""
        result = self.subscription_backend.call(model_resolved, system_prompt, user_payload, timeout_s=timeout_s)
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
    ) -> StructuredCallResult:
        """gpt | gemini — hard-gated by a local BudgetCounter (plan §3.2).

        reasoning_effort should be sourced from config/models.yaml per alias
        (e.g. "none" for the cheap cascade tier — see litellm_backend.py for why).
        """
        budget.preflight_check(estimated_usd)

        result = self.paid_backend.call(model, system_prompt, user_payload, reasoning_effort)
        budget.record_spend(result.billed_microusd)  # raises BudgetExceeded past hard_cap

        value = self._validate(result.content, schema)
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
            billed_microusd=result.billed_microusd,
            latency_ms=result.latency_ms,
        )
        self.ledger.append(record)
        return StructuredCallResult(value=value, usage_record=record)

    def _validate(self, raw: str, schema: type[T]) -> T:
        if self._repair_fn is not None:
            return validate_with_repair(raw, schema, self._repair_fn)
        from .structured import validate

        return validate(raw, schema)
