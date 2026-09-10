"""Tests for planning/short_planner.py -- A2s (plan §20.6)."""
from facts.models import Claim
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract,
)
from planning.short_planner import ShortPlanSelection, plan_shorts
from planning.shorts_models import ShortsCandidate


class FakeStoryLead:
    def __init__(self, response: ShortPlanSelection):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"]),
        ],
    )


def make_candidates() -> list[ShortsCandidate]:
    return [ShortsCandidate(beat_ids=["B01"], insight="x")]


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["short"])


def make_draft(**overrides) -> dict:
    base = dict(
        title="t", goal="DISCOVERY", central_insight="x", micro_arc="problem_fix",
        hook={"starts_at_seconds": 1.0}, source_beat_ids=["B01"],
    )
    base.update(overrides)
    return base


def test_no_candidates_short_circuits_with_no_call():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[]))
    plans = plan_shorts([], make_plan(), [], story_lead, make_budget(), run_id="r1")
    assert plans == []
    assert story_lead.calls == []


def test_builds_parent_linkage_from_source_beat_ids():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft()]))
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]

    plans = plan_shorts(make_candidates(), make_plan(), claims, story_lead, make_budget(), run_id="r1")

    assert len(plans) == 1
    assert plans[0].parent.run_id == "r1"
    assert plans[0].parent.source_beat_ids == ["B01"]
    assert plans[0].parent.allowed_fact_ids == ["C001"]
    assert plans[0].parent.final_plan_hash.startswith("sha256:")


def test_only_claims_from_the_selected_beats_source_units_are_allowed():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(source_beat_ids=["B01"])]))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    plans = plan_shorts(make_candidates(), make_plan(), claims, story_lead, make_budget(), run_id="r1")
    assert plans[0].parent.allowed_fact_ids == ["C001"]


def test_a_draft_naming_an_unknown_beat_id_is_dropped():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(source_beat_ids=["B99"])]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1")
    assert plans == []


def test_never_returns_more_than_shorts_count():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(), make_draft(), make_draft()]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1", shorts_count=2)
    assert len(plans) == 2


def test_fewer_than_the_count_is_valid_never_padded():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft()]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1", shorts_count=3)
    assert len(plans) == 1


def test_uses_pass_id_a2s_and_short_planner_mode():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[]))
    plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1")
    call = story_lead.calls[0]
    assert call["pass_id"] == "A2s"
    assert call["mode"] == "SHORT_PLANNER"
