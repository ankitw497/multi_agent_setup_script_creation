"""Tests for reporting/emit.py -- R* (plan §8, §16, §17).

V1A's own "done" bar (plan §17) names this explicitly: a rough source
becomes final/narration.json + script.md, and V1A's done includes a
cost_report.json whose totals reconcile to the manifest.
"""
import json

from llm.usage import UsageLedger, UsageRecord
from narration.models import SceneNarration, SentenceNarration
from orchestration.pipeline import PipelineResult
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from reporting.emit import emit_final_deliverables
from review.models import ReviewBundle


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="Attention Explained", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def make_narration() -> list[SceneNarration]:
    return [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="Hello.", sentence_type="transition")])]


def test_emit_writes_every_deliverable(tmp_path):
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=["A2: ok"])
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(UsageRecord(
        run_id="r1", agent="story_lead", pass_id="A2", mode="PLAN", lane="paid_api",
        model_alias="openai_story_strong", model_resolved="gpt-4o", billed_microusd=50_000,
    ))

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    assert (final_dir / "plan.json").exists()
    assert (final_dir / "narration.json").exists()
    assert (final_dir / "script.md").exists()
    assert (final_dir / "review_summary.md").exists()
    assert (final_dir / "quality_report.json").exists()
    assert (final_dir / "cost_report.json").exists()
    assert (final_dir / "run_manifest.json").exists()


def test_a_clean_run_still_gets_a_run_manifest_with_an_empty_list(tmp_path):
    """V1C: absence would be ambiguous (never checked vs checked-and-clean)."""
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    manifest = json.loads((final_dir / "run_manifest.json").read_text())
    assert manifest["run_id"] == "r1"
    assert manifest["degraded_capabilities"] == []


def test_degraded_capabilities_reach_both_the_manifest_and_the_summary(tmp_path):
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS_WARN", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")

    final_dir = emit_final_deliverables(
        result, tmp_path / "run", "r1", ledger,
        degraded_capabilities=["playwright_rendered_checks: playwright not installed"],
    )

    manifest = json.loads((final_dir / "run_manifest.json").read_text())
    assert manifest["degraded_capabilities"] == ["playwright_rendered_checks: playwright not installed"]
    summary = (final_dir / "review_summary.md").read_text()
    assert "playwright_rendered_checks: playwright not installed" in summary


def test_narration_json_round_trips_the_actual_content(tmp_path):
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    data = json.loads((final_dir / "narration.json").read_text())
    assert data[0]["scene_id"] == "s1"
    assert data[0]["sentences"][0]["text"] == "Hello."


def test_script_md_contains_the_title_and_narration_text(tmp_path):
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    script = (final_dir / "script.md").read_text()
    assert "Attention Explained" in script
    assert "Hello." in script


def test_cost_report_reconciles_to_the_usage_ledger(tmp_path):
    """V1A's own done bar (plan §17): cost_report.json totals must reconcile
    to what the ledger actually recorded."""
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    ledger.append(UsageRecord(
        run_id="r1", agent="story_lead", pass_id="A2", mode="PLAN", lane="paid_api",
        model_alias="openai_story_strong", model_resolved="gpt-4o", billed_microusd=150_000,
    ))
    ledger.append(UsageRecord(
        run_id="r1", agent="review_lead", pass_id="C1", mode="STORY_CRITIC", lane="paid_api",
        model_alias="gemini_review_strong", model_resolved="gemini/gemini-3.1-pro-preview", billed_microusd=30_000,
    ))

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    cost = json.loads((final_dir / "cost_report.json").read_text())
    assert cost["billed_usd"] == 0.18
    assert ledger.total_billed_microusd() == 180_000
    review_md = (final_dir / "review_summary.md").read_text()
    assert "$0.1800" in review_md


def test_quality_report_carries_the_resolved_archetype(tmp_path):
    result = PipelineResult(make_plan(), make_narration(), ReviewBundle(run_id="r1"), "PASS", log=[])
    ledger = UsageLedger(tmp_path / "usage.jsonl")

    final_dir = emit_final_deliverables(result, tmp_path / "run", "r1", ledger)

    quality = json.loads((final_dir / "quality_report.json").read_text())
    assert quality["archetype_resolved"] == "build"
    assert quality["final_status"] == "PASS"
