"""Tests for reporting/review_summary.py (design doc §73)."""
from orchestration.pipeline import PipelineResult
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from reporting.review_summary import render_review_summary
from review.models import CritiqueIssue, ReviewBundle


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def test_renders_status_and_no_failures_cleanly():
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS", log=["A2: ok"])
    md = render_review_summary(result)
    assert "**Final status:** PASS" in md
    assert "## Hard failures\nNone." in md
    assert "A2: ok" in md


def test_renders_hard_failures_and_grouped_issues():
    bundle = ReviewBundle(
        run_id="r1", hard_failures=["word_budget_mismatch: too short"],
        issues=[
            CritiqueIssue(issue_id="I1", severity="critical", category="archetype", layer="STORY",
                          problem="wrong archetype", why_it_matters="breaks causal flow",
                          recommended_intent="replan as build", repair_owner="story_lead"),
            CritiqueIssue(issue_id="I2", severity="minor", category="repetition", layer="NARRATION",
                          problem="repeats scene 3", why_it_matters="slows pacing",
                          recommended_intent="compress", repair_owner="narration_lead"),
        ],
    )
    result = PipelineResult(make_plan(), [], bundle, "FAIL", log=[])
    md = render_review_summary(result)
    assert "word_budget_mismatch: too short" in md
    assert "wrong archetype" in md
    assert "repeats scene 3" in md
    assert md.index("wrong archetype") < md.index("repeats scene 3")  # critical before minor
