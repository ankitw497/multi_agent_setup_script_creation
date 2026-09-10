"""Unit tests for llm/usage.py — plan §4.1, Appendix G #8 (microdollars, invariants)."""
import pytest

from llm.usage import UsageLedger, UsageRecord, ReconciliationError, usd_to_microusd, microusd_to_usd


def make_record(**overrides):
    base = dict(
        run_id="r1", agent="story_lead", pass_id="A1", mode="PLAN",
        lane="paid_api", model_alias="openai_story_mini", model_resolved="gpt-4o-mini",
        input_tokens=100, output_tokens=20, billed_microusd=42,
    )
    base.update(overrides)
    return UsageRecord(**base)


def test_usd_to_microusd_and_back_roundtrip():
    assert usd_to_microusd(0.412734) == 412734
    assert microusd_to_usd(412734) == pytest.approx(0.412734)


def test_usd_to_microusd_rounds_to_nearest_micro():
    assert usd_to_microusd(0.0000024) == 2  # rounds 2.4 -> 2


def test_rejects_unknown_agent():
    with pytest.raises(ValueError, match="unknown agent"):
        make_record(agent="not_a_real_agent")


def test_paid_lane_record_cannot_carry_notional_cost():
    with pytest.raises(ValueError, match="paid-lane records must never"):
        make_record(lane="paid_api", billed_microusd=10, notional_microusd=5)


def test_subscription_lane_record_cannot_carry_billed_cost():
    with pytest.raises(ValueError, match="subscription-lane records must never"):
        make_record(lane="subscription", billed_microusd=10, notional_microusd=0)


def test_subscription_lane_record_with_only_notional_cost_is_fine():
    r = make_record(lane="subscription", billed_microusd=0, notional_microusd=99, model_alias="haiku")
    assert r.notional_microusd == 99


def test_record_json_roundtrip():
    r = make_record()
    r2 = UsageRecord.from_json(r.to_json())
    assert r2.run_id == r.run_id
    assert r2.billed_microusd == r.billed_microusd


def test_ledger_append_and_read(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(make_record(billed_microusd=10))
    ledger.append(make_record(billed_microusd=20, agent="review_lead"))
    records = ledger.read_all()
    assert len(records) == 2
    assert ledger.total_billed_microusd() == 30


def test_ledger_by_agent_breakdown(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(make_record(billed_microusd=10, agent="story_lead"))
    ledger.append(make_record(billed_microusd=20, agent="story_lead"))
    ledger.append(make_record(billed_microusd=5, agent="review_lead"))
    breakdown = ledger.by_agent()
    assert breakdown["story_lead"]["billed_microusd"] == 30
    assert breakdown["story_lead"]["calls"] == 2
    assert breakdown["review_lead"]["billed_microusd"] == 5


def test_reconcile_passes_when_totals_match(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(make_record(billed_microusd=10))
    ledger.append(make_record(billed_microusd=20))
    ledger.reconcile(expected_billed_microusd=30)  # must not raise


def test_reconcile_fails_loudly_on_mismatch(tmp_path):
    """The one failure a cost system must never have silently (plan §4.1)."""
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(make_record(billed_microusd=10))
    with pytest.raises(ReconciliationError):
        ledger.reconcile(expected_billed_microusd=999)


def test_empty_ledger_reads_as_empty(tmp_path):
    ledger = UsageLedger(tmp_path / "does_not_exist_yet.jsonl")
    assert ledger.read_all() == []
    assert ledger.total_billed_microusd() == 0
