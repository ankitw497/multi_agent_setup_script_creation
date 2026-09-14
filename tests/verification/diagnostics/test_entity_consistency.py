"""Tests for verification/diagnostics/entity_consistency.py -- Phase 6 item #20
(cross-artifact entity consistency)."""
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, SceneVisual
from planning.models import (
    CTAContract, EndingContract, HookContract, RunningExample, ScenePlan, StoryBeat, StoryPlan,
    TitleContract,
)
from verification.diagnostics.entity_consistency import check_running_example_entity_consistency


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01")],
    )
    base.update(overrides)
    return StoryPlan(**base)


def make_beat_visual(scenes: list[SceneVisual]) -> list[BeatVisual]:
    return [BeatVisual(beat_id="B01", scenes=scenes)]


def test_no_running_example_is_a_clean_no_op():
    plan = make_plan()
    beat_visuals = make_beat_visual([SceneVisual(scene_id="s1", screen_prose="anything 'dog' here")])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "GREEN"


def test_a_scene_reusing_the_locked_example_is_clean():
    plan = make_plan(running_example=RunningExample(label="cat/stairs", values={"cat": "9.6", "stairs": "2.4"}))
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id="s1", screen_prose="the 'cat' scores higher than 'stairs' here"),
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "GREEN"


def test_an_invented_entity_not_in_the_locked_example_is_flagged():
    """The confirmed live bug: score_s02/score_s03 invented 'dog'/'park'/
    'bone' instead of reusing the locked cat/stairs example."""
    plan = make_plan(running_example=RunningExample(label="cat/stairs", values={"cat": "9.6", "stairs": "2.4"}))
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id="s1", screen_prose="here 'dog' matches against 'park' and 'bone'"),
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "AMBER"
    assert "s1" in result.evidence


def test_an_entity_from_the_beats_own_claims_is_not_flagged():
    """A scene may legitimately quote an entity that's backed by a real
    claim for that beat, even if it's not the locked running_example --
    only entities matching NEITHER pool are candidate invented content."""
    plan = make_plan(running_example=RunningExample(label="cat/stairs", values={"cat": "9.6"}))
    claims = [Claim(claim_id="C1", source_unit="u1", claim="the word 'bank' has two meanings", type="mechanism")]
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id="s1", screen_prose="consider the word 'bank' in context"),
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, claims)
    assert result.band == "GREEN"


def test_no_quoted_entities_at_all_is_clean():
    plan = make_plan(running_example=RunningExample(label="cat/stairs", values={"cat": "9.6"}))
    beat_visuals = make_beat_visual([SceneVisual(scene_id="s1", screen_prose="plain prose with no quotes")])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "GREEN"


def test_component_data_is_scanned_not_just_screen_prose():
    plan = make_plan(running_example=RunningExample(label="cat/stairs", values={"cat": "9.6"}))
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id="s1", screen_prose="see the card", component_data={"content": "'dog' -> 'bone'"}),
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "AMBER"


def test_label_words_count_as_locked_entities_even_without_a_matching_values_key():
    """running_example.label is often "a/b" shorthand -- its own words
    should count as locked even if `values` uses different key names."""
    plan = make_plan(running_example=RunningExample(label="trophy/suitcase", values={"item_a": "9.6"}))
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id="s1", screen_prose="the 'trophy' and the 'suitcase' example"),
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band == "GREEN"


def test_never_bands_red():
    """AMBER-banded diagnostic signal, never a hard failure -- per the
    plan's own explicit design (entity extraction from prose isn't
    reliable enough to promote to a hard gate)."""
    plan = make_plan(running_example=RunningExample(label="cat", values={"cat": "9.6"}))
    beat_visuals = make_beat_visual([
        SceneVisual(scene_id=f"s{i}", screen_prose=f"'invented{i}' appears here") for i in range(10)
    ])
    result = check_running_example_entity_consistency(plan, beat_visuals, [])
    assert result.band in ("GREEN", "AMBER")
