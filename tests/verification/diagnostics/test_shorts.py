"""Tests for verification/diagnostics/shorts.py -- D* short diagnostics (plan §20.10)."""
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortNarration, ShortPlan
from verification.diagnostics.shorts import check_setup_length, check_time_to_hook, check_word_count_band


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.5),
        narration=ShortNarration(target_duration_seconds=50.0, word_band=(120, 165)),
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
    narration = [scene("setup", 60, est_seconds=20.0)]
    assert check_setup_length(narration).band == "RED"


def test_missing_setup_segment_is_amber_not_a_crash():
    result = check_setup_length([scene("hook", 5)])
    assert result.band == "AMBER"


def test_word_count_within_band_is_green():
    narration = [scene("hook", 20), scene("setup", 30), scene("mechanism", 60), scene("payoff", 30)]  # 140 words
    result = check_word_count_band(make_plan(), narration)
    assert result.band == "GREEN"
    assert result.value == 140


def test_word_count_far_outside_band_is_red():
    narration = [scene("hook", 5)]  # 5 words vs 120-165 band
    result = check_word_count_band(make_plan(), narration)
    assert result.band == "RED"
