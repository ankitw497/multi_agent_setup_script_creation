"""Tests for verification/diagnostics/pacing.py -- D* (plan §10.2, V2 Phase 2)."""
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from verification.diagnostics.pacing import check_hook_tension_pacing


def make_plan(beats, scene_plan) -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat=beats[0].beat_id if beats else "B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=beats, scene_plan=scene_plan,
    )


def test_hook_tagged_scenes_under_30s_is_green():
    beats = [StoryBeat(beat_id="B01", purpose="hook"), StoryBeat(beat_id="B02", purpose="teach")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=60),  # ~21.6s
        ScenePlan(scene_id="s2", beat_id="B02", narrative_beat="teaching", word_budget=100),
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "GREEN"


def test_hook_tagged_scenes_around_45s_is_amber():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=100),  # ~35.9s
        ScenePlan(scene_id="s2", beat_id="B01", narrative_beat="hook", word_budget=30),   # +10.8s -> ~46.7s
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "AMBER"


def test_hook_tagged_scenes_well_over_60s_is_red():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=100) for _ in range(3)]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "RED"


def test_falls_back_to_the_first_beats_scenes_when_nothing_is_tagged_hook():
    """Real data-quality case: A2b never tagged any scene narrative_beat='hook'.
    The first-positioned beat IS the opening by construction -- must not be
    silently treated as zero seconds."""
    beats = [StoryBeat(beat_id="B01", purpose="opening"), StoryBeat(beat_id="B02", purpose="teach")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="teaching", word_budget=60),
        ScenePlan(scene_id="s2", beat_id="B02", narrative_beat="teaching", word_budget=100),
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "GREEN"
    assert result.value == 21.6


def test_no_beats_and_no_hook_scenes_is_red_not_a_crash():
    result = check_hook_tension_pacing(make_plan([], []))
    assert result.band == "RED"


def test_evidence_names_the_measured_seconds():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=60)]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert "22s" in result.evidence  # 60/167*60 = 21.56... -> "22s" at .0f precision
    assert result.value == 21.6  # the raw value field keeps 1 decimal of precision
    assert result.target == "<= 30s"
