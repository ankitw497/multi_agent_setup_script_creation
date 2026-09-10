"""Round-trip tests for CostReport/AgentCostSummary in llm/usage.py (plan §4.1)."""
from llm.usage import AgentCostSummary, CostReport, UsageLedger, UsageRecord

from tests.conftest import roundtrip, roundtrip_fixture


def test_agent_cost_summary_roundtrips():
    roundtrip(AgentCostSummary, {"billed_microusd": 100, "notional_microusd": 0, "calls": 2,
                                  "cache_saved_microusd": 10})


def test_cost_report_roundtrips_full_breakdown():
    report = roundtrip_fixture(CostReport, "llm", "CostReport")
    assert report.by_agent["story_lead"].calls == 3
    assert report.by_agent["narration_lead"].billed_microusd == 0  # subscription lane
    assert report.by_revision_cycle[0] == 360000


def test_cost_report_from_ledger_matches_the_ledger_totals(tmp_path):
    """CostReport.from_ledger is the ONE deterministic path from records to a
    report — this confirms it actually reconciles with the ledger it read."""
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(UsageRecord(
        run_id="r1", agent="story_lead", pass_id="A1", mode="PLAN",
        lane="paid_api", model_alias="openai_story_mini", model_resolved="gpt-4o-mini",
        billed_microusd=42,
    ))
    ledger.append(UsageRecord(
        run_id="r1", agent="narration_lead", pass_id="B1", mode="FIRST_DRAFT",
        lane="subscription", model_alias="sonnet", model_resolved="claude-sonnet-5",
        notional_microusd=1000,
    ))

    report = CostReport.from_ledger("r1", ledger)

    assert report.by_agent["story_lead"].billed_microusd == 42
    assert report.by_agent["narration_lead"].notional_microusd == 1000
    assert report.billed_usd == 42 / 1_000_000
    ledger.reconcile(expected_billed_microusd=42)  # must not raise
