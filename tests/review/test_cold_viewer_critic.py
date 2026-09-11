"""Tests for review/cold_viewer_critic.py -- C4c (IMPLEMENTATION_PLAN.md
§8/§10.2; STORY_IMPROVEMENT_PLAN.md Phase 8.2).

Same cascade discipline as C4s/C4a (tests/review/test_cold_hook_critic.py):
a clean, confident Haiku pass costs nothing further; a flagged or
uncertain one escalates to Gemini for an independent second opinion.
"""
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from review.cold_viewer_critic import (
    ColdViewerCritique, ColdViewerVerdict, critique_cold_viewer, select_cold_viewer_checkpoints,
)


class FakeWorker:
    def __init__(self, response: ColdViewerVerdict):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeReviewAgent:
    def __init__(self, response: ColdViewerCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def make_plan(n_middle_scenes=1) -> StoryPlan:
    beats = [
        StoryBeat(beat_id="B01", purpose="hook", source_unit_ids=["u1"]),
        StoryBeat(beat_id="B02", purpose="middle", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="ending", source_unit_ids=["u3"]),
    ]
    scene_plan = [ScenePlan(scene_id="s1", beat_id="B01")]
    scene_plan += [ScenePlan(scene_id=f"m{i}", beat_id="B02") for i in range(n_middle_scenes)]
    scene_plan += [ScenePlan(scene_id="s3", beat_id="B03")]
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="My Video", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=beats, scene_plan=scene_plan,
    )


# ---- select_cold_viewer_checkpoints ---------------------------------------

def test_excludes_first_and_last_beats_scenes():
    plan = make_plan()
    checkpoints = select_cold_viewer_checkpoints(plan)
    assert checkpoints == ["m0"]
    assert "s1" not in checkpoints
    assert "s3" not in checkpoints


def test_fewer_than_three_beats_returns_no_checkpoints():
    plan = make_plan()
    plan.beats = plan.beats[:2]
    assert select_cold_viewer_checkpoints(plan) == []


def test_checkpoints_are_capped_and_evenly_spaced():
    plan = make_plan(n_middle_scenes=20)
    checkpoints = select_cold_viewer_checkpoints(plan, max_checkpoints=3)
    assert len(checkpoints) <= 3


# ---- critique_cold_viewer ---------------------------------------------------

def test_clean_confident_verdict_never_escalates():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(understands_why=True, still_interested=True, confidence="high", flagged=False))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[]))

    issues = critique_cold_viewer(plan, {"m0": "text"}, worker, review_agent, make_budget())

    assert issues == []
    assert review_agent.calls == []


def test_flagged_verdict_escalates_to_gemini():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(understands_why=False, flagged=True, confidence="high"))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[{
        "issue_id": "I1", "severity": "major", "category": "cognitive_load", "layer": "STORY",
        "scene_ids": ["m0"], "problem": "lost context", "why_it_matters": "x",
        "recommended_intent": "re-orient", "repair_owner": "story_lead",
    }]))

    issues = critique_cold_viewer(plan, {"m0": "text"}, worker, review_agent, make_budget())

    assert len(review_agent.calls) == 1
    assert len(issues) == 1
    assert issues[0].category == "cognitive_load"


def test_low_confidence_escalates_even_if_not_flagged():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(flagged=False, confidence="low"))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[]))

    critique_cold_viewer(plan, {"m0": "text"}, worker, review_agent, make_budget())

    assert len(review_agent.calls) == 1


def test_no_review_agent_falls_back_to_haiku_only_issue():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(understands_why=False, flagged=True))
    issues = critique_cold_viewer(plan, {"m0": "text"}, worker)
    assert len(issues) == 1
    assert issues[0].scene_ids == ["m0"]


def test_no_checkpoints_means_no_calls_at_all():
    plan = make_plan()
    plan.beats = plan.beats[:2]
    worker = FakeWorker(ColdViewerVerdict())
    issues = critique_cold_viewer(plan, {}, worker)
    assert issues == []
    assert worker.calls == []


def test_multiple_checkpoints_each_judged_independently():
    plan = make_plan(n_middle_scenes=3)
    worker = FakeWorker(ColdViewerVerdict(flagged=False, confidence="high"))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[]))

    critique_cold_viewer(plan, {"m0": "a", "m1": "b", "m2": "c"}, worker, review_agent, make_budget())

    assert len(worker.calls) == 3


def test_understands_why_false_maps_to_cognitive_load_category():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(understands_why=False, still_interested=True, flagged=True))
    issues = critique_cold_viewer(plan, {"m0": "text"}, worker)
    assert issues[0].category == "cognitive_load"


def test_still_interested_false_maps_to_pacing_category():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(understands_why=True, still_interested=False, flagged=True))
    issues = critique_cold_viewer(plan, {"m0": "text"}, worker)
    assert issues[0].category == "pacing"


def test_escalation_payload_carries_the_title_and_snippet():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(flagged=True))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[]))
    critique_cold_viewer(plan, {"m0": "the narration text"}, worker, review_agent, make_budget())
    payload = review_agent.calls[0]["payload"]
    assert payload["title"] == "My Video"
    assert payload["narration_snippet"] == "the narration text"
    assert "first_pass_verdict" in payload


def test_uses_pass_id_c4c_for_both_stages_by_default():
    plan = make_plan()
    worker = FakeWorker(ColdViewerVerdict(flagged=True))
    review_agent = FakeReviewAgent(ColdViewerCritique(issues=[]))
    critique_cold_viewer(plan, {"m0": "x"}, worker, review_agent, make_budget())
    assert worker.calls[0]["pass_id"] == "C4c"
    assert review_agent.calls[0]["pass_id"] == "C4c"
