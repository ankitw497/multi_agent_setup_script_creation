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
