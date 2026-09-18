"""Tests for llm/client.py's paid-lane usage-record construction.

Narrow, targeted coverage (not the full "LLMClient as a whole" unit test
still tracked as an open item in BUILD_PLAN.md) for one specific real gap:
LiteLLMBackend.CallResult already extracts reasoning_tokens from the
provider's response (see tests/llm/test_litellm_backend.py), but
call_structured_paid() used to silently drop it before building the
UsageRecord it writes to usage.jsonl -- found 2026-09-11 while diagnosing
a real gpt-5.6-sol failure where seeing the reasoning/output split per
call would have mattered.
"""
from pydantic import BaseModel

from llm.backends.litellm_backend import CallResult
from llm.budget import BudgetCounter, DEFAULT_TIERS
from llm.client import LLMClient
from llm.usage import UsageLedger


class Answer(BaseModel):
    text: str = "ok"


class FakePaidBackend:
    def __init__(self, call_result: CallResult):
        self._result = call_result
        self.calls = []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result


def make_client(tmp_path, call_result: CallResult) -> LLMClient:
    ledger = UsageLedger(path=str(tmp_path / "usage.jsonl"))
    return LLMClient(
        run_id="test-run", ledger=ledger,
        paid_backend=FakePaidBackend(call_result),
    )


def test_reasoning_tokens_reach_the_usage_record(tmp_path):
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-5.6-sol",
        input_tokens=100, output_tokens=4000, reasoning_tokens=3800,
        billed_microusd=148552, latency_ms=1000,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    result = client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong_gpt56",
        model="gpt-5.6-sol", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1,
    )

    assert result.usage_record.reasoning_tokens == 3800
    assert result.usage_record.output_tokens == 4000


def test_reasoning_tokens_default_to_zero_for_a_non_reasoning_model(tmp_path):
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-4o",
        input_tokens=100, output_tokens=50, reasoning_tokens=0,
        billed_microusd=500, latency_ms=200,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    result = client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong",
        model="gpt-4o", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1,
    )

    assert result.usage_record.reasoning_tokens == 0


def test_reasoning_tokens_persist_through_a_real_ledger_round_trip(tmp_path):
    """The value must actually survive a write-then-read cycle through
    usage.jsonl, not just live on the in-memory UsageRecord."""
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-5.6-sol",
        input_tokens=100, output_tokens=4000, reasoning_tokens=3800,
        billed_microusd=148552, latency_ms=1000,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong_gpt56",
        model="gpt-5.6-sol", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1,
    )

    records = client.ledger.read_all()
    assert len(records) == 1
    assert records[0].reasoning_tokens == 3800


def test_timeout_s_reaches_the_paid_backend(tmp_path):
    """Real bug found live 2026-09-12: call_structured_paid() had no
    timeout_s parameter at all, so Agent.run()'s timeout_s was silently
    dropped for every paid-lane call -- a hung connection could block
    forever (confirmed: a real gpt-5.6-sol run stalled 6+ hours)."""
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-4o",
        input_tokens=10, output_tokens=10, reasoning_tokens=0,
        billed_microusd=100, latency_ms=100,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong",
        model="gpt-4o", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1, timeout_s=45.0,
    )

    _args, kwargs = client.paid_backend.calls[0]
    assert kwargs["timeout_s"] == 45.0


def test_enable_web_search_reaches_the_paid_backend(tmp_path):
    """STORY_IMPROVEMENT_PLAN.md Phase 23: enable_web_search must reach the paid backend
    untouched, the same forwarding this file already proved for timeout_s."""
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gemini-3.1-pro-preview",
        input_tokens=10, output_tokens=10, reasoning_tokens=0,
        billed_microusd=100, latency_ms=100,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    client.call_structured_paid(
        agent="review_lead", pass_id="C2a", mode="VERIFY_SOURCE_CLAIMS", model_alias="gemini_review_strong",
        model="gemini/gemini-3.1-pro-preview", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1, enable_web_search=True,
    )

    _args, kwargs = client.paid_backend.calls[0]
    assert kwargs["enable_web_search"] is True


def test_enable_web_search_defaults_to_false_at_the_client_level(tmp_path):
    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-4o",
        input_tokens=10, output_tokens=10, reasoning_tokens=0,
        billed_microusd=100, latency_ms=100,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong",
        model="gpt-4o", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.1,
    )

    _args, kwargs = client.paid_backend.calls[0]
    assert kwargs["enable_web_search"] is False


def test_a_call_that_exceeds_the_hard_cap_is_still_logged_to_the_ledger(tmp_path):
    """Real bug found live 2026-09-16 (Phase 17 interrupt-and-resume verification): logging
    used to happen AFTER `budget.record_spend()`, so a call that pushed spend past the hard
    cap raised `BudgetExceeded` before its `UsageRecord` was ever built or appended -- the
    real money spent on that exact call vanished from `usage.jsonl` entirely. Confirmed live:
    a real gpt-5.6-sol A2 call billed $0.266102 and crashed the run, but `usage.jsonl` showed
    only the 3 calls before it. The call really happened and really cost money regardless of
    whether it also broke the budget -- the ledger must record it either way."""
    import pytest

    from llm.budget import BudgetExceeded, BudgetTier

    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-5.6-sol",
        input_tokens=1000, output_tokens=4000, reasoning_tokens=3800,
        billed_microusd=266_102, latency_ms=1000,
    )
    client = make_client(tmp_path, call_result)
    budget = BudgetCounter(tier=BudgetTier(target_usd=0.05, warning_usd=0.10, hard_cap_usd=0.15))

    with pytest.raises(BudgetExceeded):
        client.call_structured_paid(
            agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong_gpt56",
            model="gpt-5.6-sol", system_prompt="x", user_payload="y", schema=Answer,
            budget=budget, estimated_usd=0.1,
        )

    logged = client.ledger.read_all()
    assert len(logged) == 1
    assert logged[0].billed_microusd == 266_102
    assert logged[0].pass_id == "A2"


def test_repair_path_passes_a_warn_fn_for_the_content_fidelity_check(tmp_path, monkeypatch):
    """PIPELINE_AUDIT_2026-09-17.md finding #10: `_validate` must actually wire a `warn_fn`
    into `validate_with_repair` when a repair_fn is configured -- otherwise the new
    content-fidelity check (tests/llm/test_structured.py) never fires from the real
    pipeline, only in its own isolated unit tests."""
    import llm.client as client_module

    call_result = CallResult(
        content='{"text": "ok"}', model_resolved="gpt-4o",
        input_tokens=10, output_tokens=5, reasoning_tokens=0,
        billed_microusd=100, latency_ms=10,
    )
    client = LLMClient(
        run_id="test-run", ledger=UsageLedger(path=str(tmp_path / "usage.jsonl")),
        paid_backend=FakePaidBackend(call_result), repair_fn=lambda raw, err, schema: raw,
    )

    seen_kwargs = {}

    def fake_validate_with_repair(raw, schema, repair_fn, **kwargs):
        seen_kwargs.update(kwargs)
        return Answer()

    monkeypatch.setattr(client_module, "validate_with_repair", fake_validate_with_repair)
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    client.call_structured_paid(
        agent="story_lead", pass_id="A2", mode="PLAN", model_alias="openai_story_strong",
        model="gpt-4o", system_prompt="x", user_payload="y", schema=Answer,
        budget=budget, estimated_usd=0.01,
    )

    assert seen_kwargs.get("warn_fn") is print
