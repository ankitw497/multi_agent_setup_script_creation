"""Tests for verification/hard/structure.py (plan §9). Deterministic, no LLM.

Two of these tests replay REAL defects found in live A2 runs on
2026-09-10 (project/attention_series/video-01-.../runs/v01, v02) -- proof
this check actually catches what happened, not just synthetic cases.
"""
from planning.models import (
    CTAContract, EndingContract, HookContract, MiniPayoff, ScenePlan, SourceBrief, SourceCoverageDecision,
    StoryBeat, StoryPlan, TitleContract,
)
from verification.hard.structure import (
    check_core_roles_present, check_cta_placement, check_every_beat_has_source_units,
    check_learning_gate, check_promise_chain, check_referential_integrity, check_source_disposition,
    check_structure, check_word_budget_matches_target,
)


def make_source_brief(**overrides) -> SourceBrief:
    base = dict(topic="t", core_question="q", viewer_problem="p", central_insight="a real insight")
    base.update(overrides)
    return SourceBrief(**base)


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_stage="desired_capability")],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=60)],
        source_coverage=[SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x")],
    )
    base.update(overrides)
    return StoryPlan(**base)


# ---- word budget vs target ------------------------------------------------------

def test_real_defect_460_words_against_a_1670_word_target_is_flagged():
    """The exact real numbers from runs/v02 (2026-09-10): 460 words total,
    600s target (~1670 words) -- ratio 0.275, far outside tolerance."""
    plan = make_plan(scene_plan=[ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=77) for i in range(6)])
    issues = check_word_budget_matches_target(plan, target_duration_seconds=600.0)
    assert len(issues) == 1
    assert issues[0].code == "word_budget_mismatch"


def test_word_budget_within_tolerance_passes():
    words_needed = round(600 / 60 * 167)  # ~1670
    scenes = [ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=70) for i in range(words_needed // 70)]
    plan = make_plan(scene_plan=scenes)
    assert check_word_budget_matches_target(plan, target_duration_seconds=600.0) == []


def test_zero_target_duration_is_a_no_op_not_a_crash():
    plan = make_plan()
    assert check_word_budget_matches_target(plan, target_duration_seconds=0) == []


# ---- source_unit_ids and coverage ------------------------------------------------

def test_real_defect_empty_source_unit_ids_on_every_beat_is_flagged():
    """The exact real defect from runs/v02: every beat had source_unit_ids=[]."""
    plan = make_plan(beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=[])])
    issues = check_every_beat_has_source_units(plan)
    assert len(issues) == 1
    assert issues[0].code == "beat_missing_source_units"


def test_units_missing_a_disposition_entirely_are_flagged():
    plan = make_plan(
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
        source_coverage=[SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x")],
        # u2/u3 never classified at all
    )
    issues = check_source_disposition(plan, all_source_unit_ids=["u1", "u2", "u3"])
    codes = {i.code for i in issues}
    assert "source_unit_missing_disposition" in codes
    detail = next(i.detail for i in issues if i.code == "source_unit_missing_disposition")
    assert "u2" in detail and "u3" in detail


def test_a_must_cover_unit_never_referenced_by_any_beat_is_flagged():
    plan = make_plan(
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
        source_coverage=[
            SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x"),
            SourceCoverageDecision(source_unit_id="u2", disposition="MUST_COVER", reason="the core mechanism"),
        ],
    )
    issues = check_source_disposition(plan, all_source_unit_ids=["u1", "u2"])
    codes = {i.code for i in issues}
    assert "required_source_unit_uncovered" in codes
    assert "u2" in next(i.detail for i in issues if i.code == "required_source_unit_uncovered")


def test_a_deferred_unit_never_referenced_by_any_beat_is_clean():
    """The whole point of Phase 11: DEFERRED/REDUNDANT/META_ONLY are legitimate
    outcomes on their own -- they must never force a beat into existing."""
    plan = make_plan(
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
        source_coverage=[
            SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x"),
            SourceCoverageDecision(source_unit_id="u2", disposition="DEFERRED", reason="out of scope for this video"),
        ],
    )
    assert check_source_disposition(plan, all_source_unit_ids=["u1", "u2"]) == []


def test_full_must_cover_coverage_passes():
    plan = make_plan(
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1", "u2"])],
        source_coverage=[
            SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x"),
            SourceCoverageDecision(source_unit_id="u2", disposition="SUPPORTING", reason="y"),
        ],
    )
    assert check_source_disposition(plan, all_source_unit_ids=["u1", "u2"]) == []


# ---- referential integrity --------------------------------------------------------

def test_duplicate_scene_ids_are_flagged():
    plan = make_plan(scene_plan=[
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60),
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60),
    ])
    issues = check_referential_integrity(plan)
    assert any(i.code == "duplicate_scene_ids" for i in issues)


def test_scene_referencing_unknown_beat_is_flagged():
    plan = make_plan(scene_plan=[ScenePlan(scene_id="s1", beat_id="NO_SUCH_BEAT", word_budget=60)])
    issues = check_referential_integrity(plan)
    assert any(i.code == "scene_references_unknown_beat" for i in issues)


def test_cta_referencing_unknown_beat_is_flagged():
    plan = make_plan(cta=CTAContract(primary_after_beat="GHOST"))
    issues = check_referential_integrity(plan)
    assert any(i.code == "cta_references_unknown_beat" for i in issues)


def test_mini_payoff_referencing_unknown_beat_is_flagged():
    plan = make_plan(mini_payoffs=[MiniPayoff(after_beat="GHOST", payoff="x")])
    issues = check_referential_integrity(plan)
    assert any(i.code == "mini_payoff_references_unknown_beat" for i in issues)


def test_a_clean_plan_has_no_referential_issues():
    plan = make_plan()
    assert check_referential_integrity(plan) == []


# ---- core roles -------------------------------------------------------------------

def test_missing_core_role_is_flagged():
    """build's core roles include problem_to_solution_pair and assembled_system
    -- a plan with only desired_capability is missing them."""
    plan = make_plan(beats=[StoryBeat(beat_id="B01", purpose="x", archetype_stage="desired_capability")])
    issues = check_core_roles_present(plan)
    assert len(issues) == 1
    assert "problem_to_solution_pair" in issues[0].detail


def test_optional_roles_are_never_required():
    """build's optional role (further_limitation_fix_round) must never
    trigger a missing-core-role failure on its own."""
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", archetype_stage="desired_capability"),
        StoryBeat(beat_id="B02", purpose="x", archetype_stage="problem_to_solution_pair"),
        StoryBeat(beat_id="B03", purpose="x", archetype_stage="assembled_system"),
    ])
    assert check_core_roles_present(plan) == []


# ---- full pass ----------------------------------------------------------------------

def test_check_structure_runs_all_checks_together():
    plan = make_plan(beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=[])])  # missing source units + core roles
    issues = check_structure(plan, target_duration_seconds=600.0, all_source_unit_ids=["u1"])
    codes = {i.code for i in issues}
    assert "beat_missing_source_units" in codes
    assert "word_budget_mismatch" in codes
    assert "core_role_missing" in codes


# ---- promise chain ---------------------------------------------------------

def test_disconnected_title_and_hook_promise_is_flagged():
    plan = make_plan(
        title=TitleContract(chosen="t", promise="why cats always land on their feet"),
        hook=HookContract(viewer_problem="x", tension="y", promise="how neural networks learn to translate language"),
    )
    issues = check_promise_chain(plan)
    codes = {i.code for i in issues}
    assert "title_promise_unrelated_to_hook" in codes


def test_hook_promise_unpaid_by_ending_is_flagged():
    plan = make_plan(
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand attention"),
        ending=EndingContract(resolve_hook="a completely unrelated closing statement about cats",
                               compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )
    issues = check_promise_chain(plan)
    codes = {i.code for i in issues}
    assert "hook_promise_unpaid_by_ending" in codes


def test_related_promise_chain_in_different_words_is_not_flagged():
    """A real promise chain restated in different words must not trip a
    false positive -- PROMISE_OVERLAP_THRESHOLD is deliberately generous."""
    plan = make_plan(
        title=TitleContract(chosen="t", promise="understand how attention retrieves context"),
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand how attention retrieves context for a token"),
        ending=EndingContract(resolve_hook="now you understand how attention retrieves context end to end",
                               compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )
    assert check_promise_chain(plan) == []


# ---- CTA placement -----------------------------------------------------------

def test_cta_in_the_first_beat_is_flagged():
    plan = make_plan(
        cta=CTAContract(primary_after_beat="B01"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
    )
    issues = check_cta_placement(plan)
    codes = {i.code for i in issues}
    assert "cta_in_hook" in codes


def test_cta_before_the_first_payoff_beat_is_flagged():
    plan = make_plan(
        cta=CTAContract(primary_after_beat="B02"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
            StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"], payoff=True),
        ],
    )
    issues = check_cta_placement(plan)
    codes = {i.code for i in issues}
    assert "cta_before_first_payoff" in codes


def test_cta_after_the_first_payoff_beat_is_clean():
    plan = make_plan(
        cta=CTAContract(primary_after_beat="B03"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"], payoff=True),
            StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"]),
        ],
    )
    assert check_cta_placement(plan) == []


def test_check_structure_on_a_fully_clean_plan_is_empty():
    plan = make_plan(
        title=TitleContract(chosen="t", promise="understand how attention retrieves context"),
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand how attention retrieves context"),
        ending=EndingContract(
            resolve_hook="now you understand how attention retrieves context end to end",
            compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x",
        ),
        cta=CTAContract(primary_after_beat="B03"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_stage="desired_capability"),
            StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"], archetype_stage="problem_to_solution_pair", payoff=True),
            StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"], archetype_stage="assembled_system"),
        ],
        scene_plan=[ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=70) for i in range(24)],  # ~1680 words
        source_coverage=[
            SourceCoverageDecision(source_unit_id="u1", disposition="MUST_COVER", reason="x"),
            SourceCoverageDecision(source_unit_id="u2", disposition="MUST_COVER", reason="y"),
            SourceCoverageDecision(source_unit_id="u3", disposition="SUPPORTING", reason="z"),
        ],
    )
    assert check_structure(plan, target_duration_seconds=600.0, all_source_unit_ids=["u1", "u2", "u3"]) == []


# ---- learning gate (plan §9, STORY_IMPROVEMENT_PLAN.md Phase 8.3) -----------------------------

def test_empty_central_insight_is_flagged():
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism",
                  learning_objective="explain the mechanism"),
    ])
    issues = check_learning_gate(plan, make_source_brief(central_insight=""))
    codes = {i.code for i in issues}
    assert "no_central_insight" in codes


def test_a_beat_with_a_real_archetype_role_and_no_learning_objective_is_flagged():
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism"),
    ])
    issues = check_learning_gate(plan, make_source_brief())
    codes = {i.code for i in issues}
    assert "beat_missing_learning_objective" in codes


def test_a_beat_with_no_archetype_role_is_never_required_to_have_one():
    """A blank archetype_role is a valid, real state (plan §14) -- not
    every scene has to instantiate a named archetype stage, so a beat with
    no role at all should not be held to the learning-objective
    requirement the way a "major" beat is."""
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role=""),
    ], ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"))
    issues = check_learning_gate(plan, make_source_brief())
    codes = {i.code for i in issues}
    assert "beat_missing_learning_objective" not in codes


def test_viewer_can_now_unreachable_from_any_beats_learning_objective_is_flagged():
    plan = make_plan(
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z",
                               viewer_can_now="explain how attention retrieves context"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism",
                          learning_objective="a completely unrelated statement about cats")],
    )
    issues = check_learning_gate(plan, make_source_brief())
    codes = {i.code for i in issues}
    assert "viewer_can_now_unreachable" in codes


def test_viewer_can_now_reachable_in_different_words_is_not_flagged():
    plan = make_plan(
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z",
                               viewer_can_now="explain how attention retrieves context instead of a fixed summary"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism",
                          learning_objective="explain how attention retrieves context for a token")],
    )
    issues = check_learning_gate(plan, make_source_brief())
    codes = {i.code for i in issues}
    assert "viewer_can_now_unreachable" not in codes


def test_a_fully_clean_plan_passes_the_learning_gate():
    plan = make_plan(
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z",
                               viewer_can_now="explain how attention retrieves context"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism",
                          learning_objective="explain how attention retrieves context")],
    )
    assert check_learning_gate(plan, make_source_brief()) == []


def test_no_beats_at_all_does_not_crash_the_learning_gate():
    plan = make_plan(beats=[])
    assert check_learning_gate(plan, make_source_brief()) == []


def test_check_structure_skips_the_learning_gate_when_no_source_brief_is_given():
    """Backward compatible: existing callers/tests with no SourceBrief in
    scope keep working unchanged."""
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism"),
    ])
    issues = check_structure(plan, target_duration_seconds=600.0, all_source_unit_ids=["u1"])
    assert "beat_missing_learning_objective" not in {i.code for i in issues}


def test_check_structure_includes_the_learning_gate_when_a_source_brief_is_given():
    plan = make_plan(beats=[
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism"),
    ])
    issues = check_structure(
        plan, target_duration_seconds=600.0, all_source_unit_ids=["u1"], source_brief=make_source_brief(),
    )
    assert "beat_missing_learning_objective" in {i.code for i in issues}
