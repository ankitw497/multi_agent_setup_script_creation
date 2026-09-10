"""Tests for reporting/quality_report.py (plan §14)."""
from orchestration.pipeline import PipelineResult
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from reporting.quality_report import build_quality_report
from review.models import DiagnosticResult, ReviewBundle


def make_plan(archetype="build") -> StoryPlan:
    return StoryPlan(
        archetype=archetype, selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def test_builds_a_valid_report_from_a_clean_result():
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS")
    report = build_quality_report("r1", result)
    assert report.final_status == "PASS"
    assert report.archetype_resolved == "build"
    assert report.hard_gate_failures == []
    assert report.revisions == 0


def test_counts_ambers_and_reds_from_diagnostics():
    bundle = ReviewBundle(run_id="r1", diagnostics=[
        DiagnosticResult(dimension="a", band="AMBER", evidence="e"),
        DiagnosticResult(dimension="b", band="AMBER", evidence="e"),
        DiagnosticResult(dimension="c", band="RED", evidence="e"),
    ])
    result = PipelineResult(make_plan(), [], bundle, "PASS_WARN")
    report = build_quality_report("r1", result)
    assert report.amber_count == 2
    assert report.red_count == 1


def test_revisions_sums_replans_and_targeted_rewrites():
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS",
                             story_replans_used=1, major_revisions_used=2)
    report = build_quality_report("r1", result)
    assert report.revisions == 3


def test_hard_gate_failures_are_carried_through_verbatim():
    bundle = ReviewBundle(run_id="r1", hard_failures=["word_budget_mismatch: too short"])
    result = PipelineResult(make_plan(), [], bundle, "FAIL")
    report = build_quality_report("r1", result)
    assert report.hard_gate_failures == ["word_budget_mismatch: too short"]
