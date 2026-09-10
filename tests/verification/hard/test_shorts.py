"""Tests for verification/hard/shorts.py -- the short-profile hard gates (plan §20.10)."""
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortParent, ShortPlan
from verification.hard.shorts import (
    MAX_SHORT_SECONDS, check_central_insight_present, check_duration_estimate,
    check_grounding_scope, check_parent_reference, check_short_structure,
    check_title_hook_payoff_alignment,
)


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        title="Why attention needs scaling", central_insight="x", micro_arc="problem_fix",
        hook=HookEvent(narration="scores blow up without scaling", starts_at_seconds=1.0),
        payoff_central="scaling by sqrt(d_k) keeps attention scores stable",
    )
    base.update(overrides)
    return ShortPlan(**base)


def sentence(text, grounding_required=False, grounding_refs=None) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="technical_assertion",
                              grounding_required=grounding_required, grounding_refs=grounding_refs or [])


def scene(scene_id, sentences, est_seconds=5.0) -> SceneNarration:
    return SceneNarration(scene_id=scene_id, sentences=sentences, est_seconds=est_seconds)


# ---- central insight -------------------------------------------------------

def test_empty_central_insight_is_flagged():
    plan = make_plan(central_insight="")
    assert check_central_insight_present(plan)[0].code == "no_central_insight"


def test_real_central_insight_is_clean():
    assert check_central_insight_present(make_plan()) == []


# ---- title/hook/payoff alignment -------------------------------------------

def test_disconnected_title_and_hook_is_flagged():
    plan = make_plan(title="Why cats always land on their feet",
                      hook=HookEvent(narration="scores blow up without scaling", starts_at_seconds=1.0))
    codes = {i.code for i in check_title_hook_payoff_alignment(plan)}
    assert "title_hook_mismatch" in codes


def test_disconnected_title_and_payoff_is_flagged():
    plan = make_plan(payoff_central="a completely unrelated statement about cats")
    codes = {i.code for i in check_title_hook_payoff_alignment(plan)}
    assert "title_payoff_mismatch" in codes


def test_aligned_title_hook_payoff_is_clean():
    assert check_title_hook_payoff_alignment(make_plan()) == []


# ---- duration ---------------------------------------------------------------

def test_duration_within_cap_is_clean():
    narration = [scene("hook", [], est_seconds=2.0), scene("payoff", [], est_seconds=40.0)]
    assert check_duration_estimate(narration) == []


def test_duration_over_the_cap_is_flagged():
    narration = [scene("hook", [], est_seconds=30.0), scene("payoff", [], est_seconds=40.0)]
    issues = check_duration_estimate(narration)
    assert len(issues) == 1
    assert issues[0].code == "duration_estimate_exceeds_max"


def test_duration_right_at_the_cap_is_clean():
    narration = [scene("payoff", [], est_seconds=MAX_SHORT_SECONDS)]
    assert check_duration_estimate(narration) == []


# ---- parent reference ---------------------------------------------------------

def test_missing_parent_when_required_is_flagged():
    plan = make_plan(parent=None)
    issues = check_parent_reference(plan, require_parent=True)
    assert issues[0].code == "missing_parent_reference"


def test_missing_parent_when_not_required_is_clean():
    plan = make_plan(parent=None)
    assert check_parent_reference(plan, require_parent=False) == []


# ---- grounding scope ----------------------------------------------------------

def test_claim_outside_allowed_fact_ids_is_flagged():
    plan = make_plan()  # allowed_fact_ids=["C001"]
    narration = [scene("mechanism", [sentence("x", grounding_required=True, grounding_refs=["C999"])])]
    issues = check_grounding_scope(narration, plan)
    assert len(issues) == 1
    assert issues[0].code == "claim_outside_allowed_fact_set"


def test_claim_within_allowed_fact_ids_is_clean():
    plan = make_plan()
    narration = [scene("mechanism", [sentence("x", grounding_required=True, grounding_refs=["C001"])])]
    assert check_grounding_scope(narration, plan) == []


def test_standalone_short_with_no_parent_has_no_scope_boundary():
    plan = make_plan(parent=None)
    narration = [scene("mechanism", [sentence("x", grounding_required=True, grounding_refs=["anything"])])]
    assert check_grounding_scope(narration, plan) == []


def test_check_short_structure_on_a_fully_clean_short_is_empty():
    plan = make_plan()
    narration = [scene("hook", [], est_seconds=2.0), scene("payoff", [sentence("x", True, ["C001"])], est_seconds=40.0)]
    assert check_short_structure(plan, narration) == []
