"""Tests for verification/hard/formula_consistency.py -- STORY_IMPROVEMENT_PLAN.md
Phase 6 item 7 (typed formula/numeric-state validators)."""
from html_synth.synthesizer import BeatVisual, SceneVisual
from planning.models import (
    CTAContract, EndingContract, FormulaStage, HookContract, ScenePlan, StoryPlan, TitleContract,
)
from verification.hard.formula_consistency import check_formula_stage_consistency


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )
    base.update(overrides)
    return StoryPlan(**base)


def make_scene(scene_id: str, beat_id: str, formula_stage_id: str = "") -> ScenePlan:
    return ScenePlan(scene_id=scene_id, beat_id=beat_id, formula_stage_id=formula_stage_id)


def make_beat_visual(beat_id: str, scenes: list[SceneVisual]) -> BeatVisual:
    return BeatVisual(beat_id=beat_id, scenes=scenes)


def test_empty_formula_stages_is_a_no_op():
    plan = make_plan(scene_plan=[make_scene("s1", "B01", "raw_score")])
    assert check_formula_stage_consistency(plan, []) == []


def test_scene_with_no_formula_stage_id_is_ignored():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="raw_score", expression="QK^T")],
        scene_plan=[make_scene("s1", "B01")],
    )
    beat_visuals = [make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="no formula here")])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_a_scene_that_correctly_shows_its_registered_stage_is_clean():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="raw_score", expression="QK^T")],
        scene_plan=[make_scene("s1", "B01", "raw_score")],
    )
    beat_visuals = [make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="the score is QK^T here")])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_a_regression_to_an_earlier_stages_form_is_caught():
    """The confirmed live bug: B7 derives the scaled form, but B8's own
    equation card regresses to the pre-scaling form one beat later."""
    plan = make_plan(
        formula_stages=[
            FormulaStage(stage_id="raw_score", expression="QK^T"),
            FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)"),
        ],
        scene_plan=[
            make_scene("s1", "B07", "scaled_score"),
            make_scene("s2", "B08", "raw_score"),
        ],
    )
    beat_visuals = [
        make_beat_visual("B07", [SceneVisual(scene_id="s1", screen_prose="softmax(QK^T / sqrt(d_k))")]),
        make_beat_visual("B08", [SceneVisual(scene_id="s2", screen_prose="softmax(QK^T)_row")]),
    ]

    issues = check_formula_stage_consistency(plan, beat_visuals)

    assert any(i.code == "formula_stage_regression" and i.scene_id == "s2" for i in issues)


def test_a_consistent_stage_progression_is_not_flagged():
    plan = make_plan(
        formula_stages=[
            FormulaStage(stage_id="raw_score", expression="QK^T"),
            FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)"),
        ],
        scene_plan=[
            make_scene("s1", "B01", "raw_score"),
            make_scene("s2", "B02", "scaled_score"),
            make_scene("s3", "B03", "scaled_score"),
        ],
    )
    beat_visuals = [
        make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="QK^T")]),
        make_beat_visual("B02", [SceneVisual(scene_id="s2", screen_prose="QK^T / sqrt(d_k)")]),
        make_beat_visual("B03", [SceneVisual(scene_id="s3", screen_prose="softmax(QK^T / sqrt(d_k))")]),
    ]

    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_expression_match_is_whitespace_insensitive():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)")],
        scene_plan=[make_scene("s1", "B01", "scaled_score")],
    )
    beat_visuals = [make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="softmax( QK^T/sqrt(d_k) )")])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_expression_is_matched_in_component_data_not_just_screen_prose():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="raw_score", expression="QK^T")],
        scene_plan=[make_scene("s1", "B01", "raw_score")],
    )
    beat_visuals = [make_beat_visual("B01", [
        SceneVisual(scene_id="s1", screen_prose="see the card", component_data={"content": "QK^T -> score"}),
    ])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_missing_registered_values_are_flagged():
    """The raw-vs-scaled confusion bug: a scene claims 'scaled scores' but
    shows the exact same numbers as the raw stage -- the scaled stage's own
    registered numbers never actually appear."""
    plan = make_plan(
        formula_stages=[
            FormulaStage(stage_id="raw_score", expression="QK^T", values={"item_a": "4.8"}),
            FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)", values={"item_a": "1.7"}),
        ],
        scene_plan=[
            make_scene("s1", "B01", "raw_score"),
            make_scene("s2", "B02", "scaled_score"),
        ],
    )
    beat_visuals = [
        make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="QK^T gives item_a scoring 4.8")]),
        make_beat_visual("B02", [SceneVisual(scene_id="s2", screen_prose="scaled: QK^T / sqrt(d_k), item_a is 4.8")]),
    ]

    issues = check_formula_stage_consistency(plan, beat_visuals)

    assert any(i.code == "formula_stage_values_missing" and i.scene_id == "s2" for i in issues)


def test_present_registered_values_are_not_flagged():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)", values={"item_a": "1.7"})],
        scene_plan=[make_scene("s1", "B01", "scaled_score")],
    )
    beat_visuals = [make_beat_visual("B01", [
        SceneVisual(scene_id="s1", screen_prose="scaled: QK^T / sqrt(d_k), item_a is now 1.7"),
    ])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []


def test_an_unregistered_formula_stage_id_is_ignored_not_a_crash():
    plan = make_plan(
        formula_stages=[FormulaStage(stage_id="raw_score", expression="QK^T")],
        scene_plan=[make_scene("s1", "B01", "typo_stage_id")],
    )
    beat_visuals = [make_beat_visual("B01", [SceneVisual(scene_id="s1", screen_prose="anything")])]
    assert check_formula_stage_consistency(plan, beat_visuals) == []
