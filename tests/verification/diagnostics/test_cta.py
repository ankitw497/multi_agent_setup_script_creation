"""Tests for verification/diagnostics/cta.py -- D* (plan §10.3)."""
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from verification.diagnostics.cta import check_cta_position


def make_plan(cta_beat, beats, scene_plan) -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat=cta_beat),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=beats, scene_plan=scene_plan,
    )


def test_cta_at_thirty_percent_is_green():
    beats = [StoryBeat(beat_id="B01", purpose="x"), StoryBeat(beat_id="B02", purpose="x"), StoryBeat(beat_id="B03", purpose="x")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=30),  # ~30% of total
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=35),
        ScenePlan(scene_id="s3", beat_id="B03", word_budget=35),
    ]
    plan = make_plan("B01", beats, scenes)
    result = check_cta_position(plan)
    assert result.band == "GREEN"


def test_cta_in_the_first_few_percent_is_red():
    beats = [StoryBeat(beat_id="B01", purpose="x"), StoryBeat(beat_id="B02", purpose="x")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=30)]  # ~5% of total
    scenes += [ScenePlan(scene_id=f"s{i}", beat_id="B02", word_budget=95) for i in range(2, 8)]  # 6*95=570
    plan = make_plan("B01", beats, scenes)
    result = check_cta_position(plan)
    assert result.band == "RED"


def test_cta_near_the_very_end_is_red():
    beats = [StoryBeat(beat_id="B01", purpose="x"), StoryBeat(beat_id="B02", purpose="x")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=100),
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=30),
    ]
    plan = make_plan("B02", beats, scenes)
    result = check_cta_position(plan)
    assert result.band == "RED"


def test_unknown_cta_beat_is_red_not_a_crash():
    beats = [StoryBeat(beat_id="B01", purpose="x")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=30)]
    plan = make_plan("B99", beats, scenes)
    result = check_cta_position(plan)
    assert result.band == "RED"
