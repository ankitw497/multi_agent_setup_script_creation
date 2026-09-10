"""Tests for editing/revision_planner.py -- A3 (design doc §36, plan §15)."""
from editing.models import RevisionPlan
from editing.revision_planner import plan_revision
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract,
)
from review.models import CritiqueIssue
from verification.hard.grounding import GroundingViolation
from verification.hard.structure import StructuralIssue


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="foundation", selection_reason="dependency-driven concepts", story_promise="x",
        central_question="x", source_evidence=["no violated expectation found", "no problem/fix chain found"],
        rejected_archetypes={"build": "no problem/fix chain found", "mystery": "no violated expectation"},
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x")],
    )
    base.update(overrides)
    return StoryPlan(**base)


class FakeStoryLead:
    def __init__(self, response: RevisionPlan):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_real_scenario_word_budget_and_coverage_defects_route_to_replan():
    """Replays the real 2026-09-10 finding: a word-budget mismatch plus
    uncovered source units. A3 should be ABLE to set story_replan_required
    -- this test proves the plumbing carries that decision through."""
    story_lead = FakeStoryLead(RevisionPlan(
        run_id="r1", revision_level="replan", story_replan_required=True,
        preserve=["hook", "ending"],
    ))
    structural = [
        StructuralIssue("word_budget_mismatch", "320 words vs target 1670"),
        StructuralIssue("source_units_uncovered", "9 of 11 units never used"),
    ]
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan = plan_revision(make_plan(), structural, [], [], story_lead,
                          BudgetCounter(tier=DEFAULT_TIERS["longform"]))

    assert plan.story_replan_required is True
    payload = story_lead.calls[0]["payload"]
    codes = {i["code"] for i in payload["structural_issues"]}
    assert codes == {"word_budget_mismatch", "source_units_uncovered"}


def test_a_single_minor_issue_does_not_have_to_trigger_a_replan():
    story_lead = FakeStoryLead(RevisionPlan(
        run_id="r1", revision_level="targeted", story_replan_required=False,
        rewrite_beats=[{"beat_id": "B01", "reason": "weak transition", "intent": "add a causal bridge"}],
    ))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan = plan_revision(make_plan(), [], [], [], story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert plan.story_replan_required is False
    assert plan.rewrite_beats[0].beat_id == "B01"


def test_grounding_violations_are_passed_through_by_scene():
    story_lead = FakeStoryLead(RevisionPlan(run_id="r1"))
    violations = [GroundingViolation("s1", 0, "grounding_policy_violation", "claim REJECTED")]
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan_revision(make_plan(), [], violations, [], story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    payload = story_lead.calls[0]["payload"]
    assert payload["grounding_violations"][0]["scene_id"] == "s1"


def test_passes_the_plans_own_reasoning_so_a3_can_weigh_a_critique_against_it():
    """Real gap found 2026-09-10 (ERR-025): A3 never saw WHY A2 chose the
    resolved archetype, so it had no way to judge whether a critic's
    dispute was actually new evidence or something A2 already considered
    and ruled out."""
    story_lead = FakeStoryLead(RevisionPlan(run_id="r1"))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan_revision(make_plan(), [], [], [], story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    payload = story_lead.calls[0]["payload"]
    assert payload["selection_reason"] == "dependency-driven concepts"
    assert payload["rejected_archetypes"]["build"] == "no problem/fix chain found"
    assert "no problem/fix chain found" in payload["source_evidence"]


def test_critique_payload_includes_issue_id_for_later_dismissal_tracking():
    story_lead = FakeStoryLead(RevisionPlan(run_id="r1"))
    critique = [CritiqueIssue(
        issue_id="I1", severity="critical", category="archetype", layer="STORY",
        problem="x", why_it_matters="y", recommended_intent="z", repair_owner="story_lead",
    )]
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan_revision(make_plan(), [], [], critique, story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert story_lead.calls[0]["payload"]["critique_issues"][0]["issue_id"] == "I1"


def test_prompt_instructs_narrow_dismissal_not_blanket_disagreement():
    from editing.revision_planner import TASK_PROMPT

    assert "dismissed_issues" in TASK_PROMPT
    assert "rejected_archetypes" in TASK_PROMPT


def test_uses_pass_id_a3_and_revision_planner_mode():
    story_lead = FakeStoryLead(RevisionPlan(run_id="r1"))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    plan_revision(make_plan(), [], [], [], story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    call = story_lead.calls[0]
    assert call["pass_id"] == "A3"
    assert call["mode"] == "REVISION_PLANNER"
