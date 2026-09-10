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


def test_renders_diagnostics_section():
    from review.models import DiagnosticResult

    bundle = ReviewBundle(run_id="r1", diagnostics=[
        DiagnosticResult(dimension="retention.payoff_gap", band="RED", value=120.0, target="<=90s",
                          evidence="longest stretch with no state change: 120.0s"),
    ])
    result = PipelineResult(make_plan(), [], bundle, "PASS_WARN", log=[])
    md = render_review_summary(result)
    assert "## Diagnostics" in md
    assert "[RED] retention.payoff_gap" in md
    assert "120.0s" in md


def test_no_diagnostics_renders_none():
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS", log=[])
    md = render_review_summary(result)
    assert "## Diagnostics\nNone." in md


def test_renders_cost_table_when_given():
    from llm.usage import AgentCostSummary, CostReport

    cost_report = CostReport(
        run_id="r1", billed_usd=0.25,
        by_agent={"story_lead": AgentCostSummary(billed_microusd=200_000, calls=3),
                  "review_lead": AgentCostSummary(billed_microusd=50_000, calls=2)},
    )
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS", log=[])
    md = render_review_summary(result, cost_report=cost_report)
    assert "## Cost" in md
    assert "$0.2500" in md
    assert "story_lead" in md
    assert "review_lead" in md


def test_no_cost_report_omits_cost_section():
    result = PipelineResult(make_plan(), [], ReviewBundle(run_id="r1"), "PASS", log=[])
    md = render_review_summary(result)
    assert "## Cost" not in md
