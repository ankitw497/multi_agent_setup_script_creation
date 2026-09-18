"""Tests for verification/diagnostics/visual_variety.py -- PIPELINE_AUDIT_2026-09-17.md
(visual monotony: an external review found a real closing beat rendering 8 near-consecutive
card-style scenes)."""
from html_synth.synthesizer import BeatVisual, SceneVisual
from verification.diagnostics.visual_variety import (
    CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD, check_consecutive_component_repetition,
)


def make_beat(beat_id: str, component_ids: list[str | None]) -> BeatVisual:
    return BeatVisual(beat_id=beat_id, scenes=[
        SceneVisual(scene_id=f"{beat_id}_s{i}", component_id=cid) for i, cid in enumerate(component_ids)
    ])


def test_no_beats_is_green():
    result = check_consecutive_component_repetition([])
    assert result.band == "GREEN"
    assert result.value == 0


def test_varied_components_is_green():
    beats = [make_beat("B01", ["card", "step_list", "diagram_card", "math_block"])]
    result = check_consecutive_component_repetition(beats)
    assert result.band == "GREEN"


def test_a_short_run_below_threshold_is_green():
    beats = [make_beat("B01", ["card", "card", "card", "step_list"])]  # 3 in a row, threshold is 4
    result = check_consecutive_component_repetition(beats)
    assert result.band == "GREEN"


def test_the_real_confirmed_case_is_amber():
    """The real, reported case: 8 near-consecutive card-style scenes in a closing beat."""
    beats = [make_beat("B12", ["card"] * 8)]
    result = check_consecutive_component_repetition(beats)
    assert result.band == "AMBER"
    assert result.value == 8
    assert "'card'" in result.evidence


def test_a_run_spanning_multiple_beats_is_still_counted():
    """The repetition this exists to catch is often exactly a cross-beat pattern -- a run
    doesn't reset just because a new beat starts; only a DIFFERENT (or absent) component
    breaks it."""
    beats = [make_beat("B11", ["card", "card"]), make_beat("B12", ["card", "card", "card"])]
    result = check_consecutive_component_repetition(beats)
    assert result.band == "AMBER"
    assert result.value == 5


def test_none_or_empty_component_id_never_counts_toward_a_run():
    """A scene with no chosen component (prose-only) legitimately varies by its own text --
    it must not extend, or itself be counted as, a repeated-component run."""
    beats = [make_beat("B01", ["card", None, "card", "", "card", "card"])]
    result = check_consecutive_component_repetition(beats)
    # the None/"" entries are skipped entirely, leaving 4 consecutive real "card" picks
    assert result.value == 4
    assert result.band == "AMBER"


def test_never_exceeds_amber_even_at_the_most_extreme_input():
    """Advisory only -- a layout-rhythm judgement call, never a hard gate (matches
    sequence_critique_issues' own established precedent for the same concern)."""
    beats = [make_beat("B01", ["card"] * 50)]
    result = check_consecutive_component_repetition(beats)
    assert result.band == "AMBER"  # never RED -- no such path exists


def test_threshold_boundary_is_exclusive_below_amber():
    below = CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD - 1
    beats = [make_beat("B01", ["card"] * below)]
    assert check_consecutive_component_repetition(beats).band == "GREEN"

    at = CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD
    beats = [make_beat("B01", ["card"] * at)]
    assert check_consecutive_component_repetition(beats).band == "AMBER"
