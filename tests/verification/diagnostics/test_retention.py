"""Tests for verification/diagnostics/retention.py -- D* (plan §10.2)."""
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, SourceBrief, StoryBeat, StoryPlan, TitleContract,
)
from verification.diagnostics.retention import (
    PAYOFF_GAP_SECONDS, VALLEY_BEAT_COUNT, check_driver_coverage, check_new_information_disagreement,
    check_novelty_coverage, check_payoff_gap, check_retention, check_valleys,
)


def make_source_brief(**overrides) -> SourceBrief:
    base = dict(topic="t", core_question="q", viewer_problem="p", central_insight="i")
    base.update(overrides)
    return SourceBrief(**base)


def make_plan(beats, scene_plan=None) -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat=beats[0].beat_id),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=beats, scene_plan=scene_plan or [],
    )


def beat(beat_id, **kwargs) -> StoryBeat:
    return StoryBeat(beat_id=beat_id, purpose="x", **kwargs)


# ---- driver coverage ---------------------------------------------------------

def test_all_beats_with_a_driver_is_green():
    plan = make_plan([beat("B01", forward_driver="x"), beat("B02", forward_driver="y")])
    result = check_driver_coverage(plan)
    assert result.band == "GREEN"
    assert result.value == 1.0


def test_no_beats_with_a_driver_is_red():
    plan = make_plan([beat("B01"), beat("B02")])
    result = check_driver_coverage(plan)
    assert result.band == "RED"
    assert result.value == 0.0


def test_partial_driver_coverage_is_amber():
    plan = make_plan([
        beat("B01", forward_driver="x"), beat("B02", forward_driver="y"),
        beat("B03", forward_driver="z"), beat("B04"),
    ])  # 3/4 = 0.75, in the [0.7, 0.9) AMBER band
    result = check_driver_coverage(plan)
    assert result.band == "AMBER"


# ---- valleys ------------------------------------------------------------------

def test_no_valley_when_every_beat_advances_something():
    plan = make_plan([beat("B01", new_information=True), beat("B02", payoff=True)])
    result = check_valleys(plan)
    assert result.band == "GREEN"
    assert result.value == 0


def test_valley_of_two_dead_beats_is_flagged():
    plan = make_plan([
        beat("B01", new_information=True), beat("B02"), beat("B03"),
        beat("B04", payoff=True),
    ])
    result = check_valleys(plan)
    assert result.band == "RED"
    assert result.value >= VALLEY_BEAT_COUNT


def test_a_single_dead_beat_is_not_a_valley():
    plan = make_plan([beat("B01", new_information=True), beat("B02"), beat("B03", payoff=True)])
    result = check_valleys(plan)
    assert result.band == "GREEN"


def test_question_progress_partial_answer_counts_as_state_change():
    plan = make_plan([beat("B01", question_progress="partial_answer"), beat("B02", question_progress="partial_answer")])
    result = check_valleys(plan)
    assert result.band == "GREEN"


# ---- payoff gap -----------------------------------------------------------

def test_payoff_gap_within_target_is_green():
    plan = make_plan(
        [beat("B01", payoff=True), beat("B02"), beat("B03", payoff=True)],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B02", word_budget=30)],  # ~11s -- well under target
    )
    result = check_payoff_gap(plan)
    assert result.band == "GREEN"


def test_payoff_gap_far_beyond_target_is_red():
    long_scenes = [ScenePlan(scene_id=f"s{i}", beat_id="B02", word_budget=100) for i in range(20)]  # ~718s
    plan = make_plan([beat("B01", payoff=True), beat("B02"), beat("B03", payoff=True)], scene_plan=long_scenes)
    result = check_payoff_gap(plan)
    assert result.band == "RED"
    assert result.value > PAYOFF_GAP_SECONDS


def test_check_retention_returns_all_four_diagnostics():
    plan = make_plan([beat("B01", forward_driver="x", payoff=True)])
    results = check_retention(plan)
    dimensions = {r.dimension for r in results}
    assert dimensions == {
        "retention.driver_coverage", "retention.valley", "retention.payoff_gap",
        "retention.new_information_disagreement",
    }


# ---- novelty coverage (plan §9, STORY_IMPROVEMENT_PLAN.md Phase 8.3) --------------------------

def test_no_novelty_statement_given_is_green_not_a_crash():
    plan = make_plan([beat("B01", learning_objective="explain attention")])
    result = check_novelty_coverage(plan, make_source_brief(novelty_statement=""))
    assert result.band == "GREEN"


def test_novelty_reflected_in_a_beats_learning_objective_is_green():
    plan = make_plan([beat("B01", learning_objective="explain how attention retrieves context")])
    result = check_novelty_coverage(
        plan, make_source_brief(novelty_statement="most viewers don't know attention retrieves context on demand"),
    )
    assert result.band == "GREEN"


def test_novelty_unreflected_in_any_beats_learning_objective_is_amber_not_a_hard_failure():
    """Deliberately soft -- novelty is a judgment call, this must never
    block a run on its own (STORY_IMPROVEMENT_PLAN.md Phase 8.3)."""
    plan = make_plan([beat("B01", learning_objective="a completely unrelated statement about cats")])
    result = check_novelty_coverage(
        plan, make_source_brief(novelty_statement="most viewers don't know attention retrieves context on demand"),
    )
    assert result.band == "AMBER"


def test_no_beat_has_any_learning_objective_is_amber():
    plan = make_plan([beat("B01")])
    result = check_novelty_coverage(plan, make_source_brief(novelty_statement="a real novelty claim about retrieval"))
    assert result.band == "AMBER"


# ---- BUG-3 fix: new_concepts (not the self-reported boolean) drives state-change ---------------

def test_new_information_true_with_no_new_concepts_is_not_treated_as_a_state_change():
    """The core BUG-3 fix: a beat that dutifully sets new_information=True
    but whose scenes introduce nothing in new_concepts must NOT count as
    real progress -- this is exactly the self-report the diagnostic used
    to trust unconditionally."""
    plan = make_plan(
        [beat("B01", new_information=True), beat("B02", new_information=True), beat("B03", payoff=True)],
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, new_concepts=[]),
            ScenePlan(scene_id="s2", beat_id="B02", word_budget=40, new_concepts=[]),
        ],
    )
    result = check_valleys(plan)
    assert result.band == "RED"  # B01+B02 form a 2-beat valley despite both claiming new_information=True


def test_new_concepts_present_counts_as_a_state_change_even_if_the_boolean_is_false():
    """The reverse direction: a scene with a real new_concepts entry counts
    as progress even if A2 never set the beat's own new_information flag."""
    plan = make_plan(
        [beat("B01", new_information=False), beat("B02", payoff=True)],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, new_concepts=["scaling"])],
    )
    result = check_valleys(plan)
    assert result.band == "GREEN"


def test_a_beat_with_no_scenes_at_all_falls_back_to_the_self_reported_boolean():
    """A malformed plan (no scenes for a beat) shouldn't silently zero out
    -- fall back to the old signal rather than always reporting no state
    change for a beat referential-integrity checks already flag elsewhere."""
    plan = make_plan([beat("B01", new_information=True), beat("B02", payoff=True)], scene_plan=[])
    result = check_valleys(plan)
    assert result.band == "GREEN"  # B01 counted via fallback, no valley


# ---- new_information disagreement (secondary signal) ----------------------------------------

def test_no_disagreement_is_green():
    plan = make_plan(
        [beat("B01", new_information=True)],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, new_concepts=["x"])],
    )
    result = check_new_information_disagreement(plan)
    assert result.band == "GREEN"


def test_new_information_true_but_zero_new_concepts_is_flagged_as_a_disagreement():
    plan = make_plan(
        [beat("B01", new_information=True)],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, new_concepts=[])],
    )
    result = check_new_information_disagreement(plan)
    assert result.band == "AMBER"
    assert "B01" in result.evidence


def test_a_beat_with_zero_scenes_is_never_a_disagreement():
    """Consistent with _introduces_new_concept()'s own "trust the boolean"
    fallback for a beat with no scenes at all -- nothing to disagree with."""
    plan = make_plan([beat("B01", new_information=True)], scene_plan=[])
    result = check_new_information_disagreement(plan)
    assert result.band == "GREEN"


def test_new_information_false_is_never_a_disagreement_regardless_of_new_concepts():
    """Only new_information=True claims are checked -- a beat that never
    claimed to introduce anything has nothing to disagree about."""
    plan = make_plan(
        [beat("B01", new_information=False)],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, new_concepts=[])],
    )
    result = check_new_information_disagreement(plan)
    assert result.band == "GREEN"
