"""Tests for verification/hard/shorts.py -- the short-profile hard gates (plan §20.10)."""
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortParent, ShortPlan
from verification.hard.shorts import (
    MAX_MEASURED_SHORT_SECONDS, MAX_SHORT_SECONDS, check_central_insight_present,
    check_duration_estimate, check_grounding_scope, check_measured_duration,
    check_parent_reference, check_segment_completeness, check_short_structure,
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


def test_a_visual_only_hook_falls_back_to_matching_central_insight_not_just_the_diagram_description():
    """2026-09-15: confirmed live -- a visual-only hook (hook.narration empty, plan
    §20.4's own "a visual can carry it" design) used to compare the title against
    hook.visual ALONE -- a diagram-description sentence in a totally different
    vocabulary domain from a title. A title that matches central_insight instead must
    not be flagged just because it doesn't also match the diagram description."""
    plan = make_plan(
        title="Scaling keeps softmax stable", central_insight="scaling keeps softmax stable under d_k growth",
        hook=HookEvent(visual="Query-key matrix visualization expanding from 4x4 to 8x8 grid", starts_at_seconds=1.0),
    )
    codes = {i.code for i in check_title_hook_payoff_alignment(plan)}
    assert "title_hook_mismatch" not in codes


def test_a_title_matching_neither_hook_nor_central_insight_is_still_flagged():
    """The fallback must widen what counts as a match, not disable the check entirely --
    a genuinely disconnected title still fails against every available anchor."""
    plan = make_plan(
        title="Why cats always land on their feet", central_insight="scaling keeps softmax stable",
        hook=HookEvent(visual="Query-key matrix visualization expanding from 4x4 to 8x8 grid", starts_at_seconds=1.0),
    )
    codes = {i.code for i in check_title_hook_payoff_alignment(plan)}
    assert "title_hook_mismatch" in codes


def test_payoff_mismatch_also_falls_back_to_central_insight():
    plan = make_plan(
        title="Scaling keeps softmax stable", central_insight="scaling keeps softmax stable under d_k growth",
        payoff_central="a completely unrelated statement about cats",
    )
    codes = {i.code for i in check_title_hook_payoff_alignment(plan)}
    assert "title_payoff_mismatch" not in codes


# ---- duration ---------------------------------------------------------------

def test_duration_within_cap_is_clean():
    narration = [scene("hook", [], est_seconds=2.0), scene("payoff", [], est_seconds=40.0)]
    assert check_duration_estimate(narration) == []


def test_duration_over_the_cap_is_flagged():
    narration = [scene("hook", [], est_seconds=70.0), scene("payoff", [], est_seconds=60.0)]
    issues = check_duration_estimate(narration)
    assert len(issues) == 1
    assert issues[0].code == "duration_estimate_exceeds_max"


def test_duration_right_at_the_cap_is_clean():
    narration = [scene("payoff", [], est_seconds=MAX_SHORT_SECONDS)]
    assert check_duration_estimate(narration) == []


# ---- measured duration (V1C: real TTS, replaces the estimate) --------------

def test_measured_duration_within_cap_is_clean():
    assert check_measured_duration(45.0) == []


def test_measured_duration_over_the_cap_is_flagged():
    issues = check_measured_duration(125.0)
    assert len(issues) == 1
    assert issues[0].code == "measured_duration_exceeds_max"


def test_measured_duration_right_at_the_cap_is_clean():
    assert check_measured_duration(MAX_MEASURED_SHORT_SECONDS) == []


def test_measured_duration_has_no_slack_unlike_the_estimate_cap():
    """The estimate cap (MAX_SHORT_SECONDS) has +2s slack for its own
    margin of error; a real measurement doesn't need that buffer."""
    assert MAX_MEASURED_SHORT_SECONDS < MAX_SHORT_SECONDS


def test_short_structure_uses_the_measured_duration_when_given_not_the_estimate():
    """A short whose ESTIMATE would fail but whose REAL measured duration
    passes must come back clean -- the measurement replaces the estimate,
    it doesn't get checked in addition to it."""
    plan = make_plan()
    narration = [scene("hook", [], est_seconds=70.0), scene("payoff", [], est_seconds=60.0)]  # estimate: 130s, over cap

    issues = check_short_structure(plan, narration, measured_duration_seconds=90.0)

    assert not any(i.code in ("duration_estimate_exceeds_max", "measured_duration_exceeds_max") for i in issues)


def test_short_structure_falls_back_to_the_estimate_when_no_measurement_given():
    """measured_duration_seconds=None (TTS unavailable, a recorded
    degradation upstream) -- the honest fallback, not silently clean."""
    plan = make_plan()
    narration = [scene("hook", [], est_seconds=70.0), scene("payoff", [], est_seconds=60.0)]

    issues = check_short_structure(plan, narration, measured_duration_seconds=None)

    assert any(i.code == "duration_estimate_exceeds_max" for i in issues)


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
    narration = [
        scene("hook", [], est_seconds=2.0), scene("setup", [], est_seconds=8.0),
        scene("mechanism", [], est_seconds=20.0), scene("payoff", [sentence("x", True, ["C001"])], est_seconds=40.0),
    ]
    assert check_short_structure(plan, narration) == []


# ---- check_segment_completeness (PIPELINE_AUDIT_2026-09-17.md) ---------------------------

def test_all_four_segments_present_once_each_is_clean():
    narration = [scene(sid, []) for sid in ("hook", "setup", "mechanism", "payoff")]
    assert check_segment_completeness(narration) == []


def test_a_missing_segment_is_flagged():
    narration = [scene(sid, []) for sid in ("hook", "setup", "mechanism")]  # no payoff at all
    issues = check_segment_completeness(narration)
    assert len(issues) == 1
    assert "payoff" in issues[0].detail


def test_a_duplicate_segment_replacing_a_required_one_is_flagged():
    """A response with two "hook" entries and no "payoff" is schema-valid -- the real bug
    this check exists for: nothing downstream ever noticed a segment was simply absent."""
    narration = [scene("hook", []), scene("hook", []), scene("setup", []), scene("mechanism", [])]
    issues = check_segment_completeness(narration)
    assert len(issues) == 1
    assert "payoff" in issues[0].detail  # missing
    assert "hook" in issues[0].detail  # duplicated


def test_empty_narration_is_flagged_as_all_segments_missing():
    assert check_segment_completeness([]) != []
