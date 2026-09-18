"""Tests for reporting/cost_report.py."""
from llm.usage import CostReport, UsageLedger, UsageRecord
from reporting.cost_report import build_cost_report


def test_build_cost_report_delegates_to_from_ledger(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(UsageRecord(
        run_id="r1", agent="story_lead", pass_id="A2", mode="PLAN", lane="paid_api",
        model_alias="openai_story_strong", model_resolved="gpt-4o",
        input_tokens=100, output_tokens=50, billed_microusd=15_000,
    ))
    report = build_cost_report("r1", ledger)
    assert isinstance(report, CostReport)
    assert report.run_id == "r1"
    assert report.billed_usd == 0.015
    assert report.by_agent["story_lead"].calls == 1


def test_carried_over_microusd_defaults_to_zero(tmp_path):
    """PIPELINE_AUDIT_2026-09-17.md finding #5: a run that was never resumed must report
    zero carried-over cost, never a stale or fabricated value."""
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    report = build_cost_report("r1", ledger)
    assert report.carried_over_usd == 0.0


def test_carried_over_microusd_is_kept_separate_from_billed_usd(tmp_path):
    """A resumed run's earlier-attempt spend must be visible, but must never be folded
    into `billed_usd` itself -- that field's own reconciliation invariant (this run's
    ledger, and only this run's ledger) must stay intact."""
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(UsageRecord(
        run_id="r1", agent="story_lead", pass_id="A2", mode="PLAN", lane="paid_api",
        model_alias="openai_story_strong", model_resolved="gpt-4o",
        input_tokens=100, output_tokens=50, billed_microusd=15_000,
    ))
    report = build_cost_report("r1", ledger, carried_over_microusd=300_000)
    assert report.billed_usd == 0.015  # unchanged -- still exactly this run's own ledger
    assert report.carried_over_usd == 0.3
    assert round(report.billed_usd + report.carried_over_usd, 3) == 0.315  # the TRUE total
