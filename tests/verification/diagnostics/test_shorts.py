"""Tests for verification/diagnostics/shorts.py -- D* short diagnostics (plan §20.10)."""
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortBridge, ShortNarration, ShortPlan, ShortVisual
from verification.diagnostics.shorts import (
    check_bridge_cta_present, check_setup_length, check_short_diagnostics, check_time_to_hook,
    check_visual_states_present, check_word_count_band,
)


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.5),
        narration=ShortNarration(target_duration_seconds=95.0, word_band=(160, 210)),
    )
    base.update(overrides)
    return ShortPlan(**base)


def sentence(text) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="transition")


def scene(scene_id, n_words, est_seconds=5.0) -> SceneNarration:
    text = " ".join(["word"] * n_words)
    return SceneNarration(scene_id=scene_id, sentences=[sentence(text)], est_seconds=est_seconds)


def test_time_to_hook_reports_the_actual_value():
    result = check_time_to_hook(make_plan(hook=HookEvent(starts_at_seconds=2.5)))
    assert result.band == "GREEN"
    assert result.value == 2.5


def test_setup_within_target_is_green():
    narration = [scene("setup", 20, est_seconds=8.0)]
    assert check_setup_length(narration).band == "GREEN"


def test_setup_far_over_target_is_red():
    narration = [scene("setup", 60, est_seconds=30.0)]
    assert check_setup_length(narration).band == "RED"


def test_missing_setup_segment_is_amber_not_a_crash():
    result = check_setup_length([scene("hook", 5)])
    assert result.band == "AMBER"


def test_a_setup_carrying_its_new_required_arc_beat_is_green_not_amber():
    """2026-09-15: confirmed live -- 4 of 5 real shorts measured 15-17.6s for `setup`
    once it also had to carry the per-micro_arc required beat (narration/
    short_generator.py's own Phase 20 addition), turning this diagnostic into a
    near-constant RED for setup segments doing their job correctly. First recalibration
    (10.0 -> 13.0) made this AMBER; the second (13.0 -> 18.0, see below) now reads this
    same real-world range as the expected GREEN case."""
    narration = [scene("setup", 40, est_seconds=16.0)]
    assert check_setup_length(narration).band == "GREEN"


def test_setup_moderately_over_the_second_recalibration_is_amber_not_red():
    """2026-09-16: a second live round measured 14.8/25.4/30.9/24.5s across 4 different
    micro_arcs -- genuinely long, but not all equally so. 24-25s should still register as
    a real (AMBER) concern, distinguishable from the 30s+ outlier, not lumped into RED."""
    narration = [scene("setup", 60, est_seconds=25.0)]
    assert check_setup_length(narration).band == "AMBER"


def test_word_count_within_band_is_green():
    narration = [scene("hook", 30), scene("setup", 45), scene("mechanism", 90), scene("payoff", 40)]  # 205 words
    result = check_word_count_band(make_plan(), narration)
    assert result.band == "GREEN"
    assert result.value == 205


def test_word_count_far_outside_band_is_red():
    narration = [scene("hook", 5)]  # 5 words vs 160-210 band
    result = check_word_count_band(make_plan(), narration)
    assert result.band == "RED"


def test_empty_visual_states_is_amber_not_a_hard_gate():
    """2026-09-16: confirmed live -- visual.states was empty in 5 of 5 real shorts,
    silently disabling html_synth/vertical_assembler.py's flow diagram this whole
    time with no visibility anywhere. Advisory only -- a short with no diagram still
    functions, so this must never be a hard failure."""
    plan = make_plan(visual=ShortVisual(dominant_object="Attention scores", states=[]))
    result = check_visual_states_present(plan)
    assert result.band == "AMBER"


def test_populated_visual_states_is_green():
    plan = make_plan(visual=ShortVisual(
        dominant_object="Attention scores", states=["raw scores", "scaled scores", "softmax weights"],
    ))
    result = check_visual_states_present(plan)
    assert result.band == "GREEN"


def test_none_or_spoken_bridge_never_needs_a_cta_text():
    assert check_bridge_cta_present(make_plan(bridge=ShortBridge(mode="NONE"))).band == "GREEN"
    assert check_bridge_cta_present(make_plan(bridge=ShortBridge(mode="SPOKEN"))).band == "GREEN"


def test_onscreen_bridge_with_no_cta_text_is_amber_not_a_hard_gate():
    """2026-09-16, found on review: ONSCREEN/PLATFORM_LINK explicitly withhold the
    bridge from spoken narration on the promise it "will render as on-screen text
    elsewhere" (narration/short_generator.py's own prompt) -- but nothing enforced
    `cta_text` was ever filled in, and nothing ever rendered it either. Advisory only,
    since `bridge.mode` is the model's own honest judgement call."""
    plan = make_plan(bridge=ShortBridge(mode="ONSCREEN", cta_text=""))
    result = check_bridge_cta_present(plan)
    assert result.band == "AMBER"


def test_platform_link_bridge_with_cta_text_is_green():
    plan = make_plan(bridge=ShortBridge(mode="PLATFORM_LINK", cta_text="Part 2 next"))
    result = check_bridge_cta_present(plan)
    assert result.band == "GREEN"


def test_check_short_diagnostics_includes_sentence_density():
    """STORY_IMPROVEMENT_PLAN.md Phase 23 item 8: the long-form sentence-density diagnostic
    is generic over any list[SceneNarration] and is reused here as-is (no shorts-specific
    threshold yet -- no live evidence the general one is wrong for shorts)."""
    plan = make_plan()
    narration = [scene("hook", 10)]
    dimensions = {d.dimension for d in check_short_diagnostics(plan, narration)}
    assert "compactness.sentence_density" in dimensions
