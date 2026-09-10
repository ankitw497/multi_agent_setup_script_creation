"""Tests for planning/beat_word_budget.py -- the ERR-010/ERR-023 fix.

Deterministic allocation, no LLM -- the actual fix for A2 being unreliable
at summing a word budget across an entire multi-beat plan in one shot.
"""
from planning.beat_word_budget import MIN_BEAT_WORDS, allocate_beat_word_budgets
from planning.models import StoryBeat


def beat(beat_id, source_unit_ids=None) -> StoryBeat:
    return StoryBeat(beat_id=beat_id, purpose="x", source_unit_ids=source_unit_ids or [])


def test_no_beats_returns_empty():
    assert allocate_beat_word_budgets([], target_duration_seconds=600) == {}


def test_allocations_sum_to_exactly_the_target():
    """The whole point: Python's sum is exact by construction, unlike an
    LLM's own aggregate sum (the real defect this fixes)."""
    beats = [beat("B01", ["u1"]), beat("B02", ["u2", "u3"]), beat("B03", ["u4"])]
    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=600)
    target_words = round(600 / 60 * 167)
    assert sum(allocations.values()) == target_words


def test_allocation_is_proportional_to_source_depth():
    """A beat covering more source units gets a proportionally larger
    share of the target."""
    beats = [beat("B01", ["u1"]), beat("B02", ["u2", "u3", "u4"])]
    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=600)
    assert allocations["B02"] > allocations["B01"]


def test_beats_with_no_source_units_still_get_an_even_share():
    beats = [beat("B01"), beat("B02"), beat("B03")]
    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=600)
    target_words = round(600 / 60 * 167)
    # even split, off by at most rounding across 3 beats
    assert all(abs(v - target_words / 3) <= 2 for v in allocations.values())


def test_every_beat_gets_at_least_the_minimum_floor():
    """A beat's allocation should never fall below the point where it can
    produce even one valid scene (ScenePlan's own 30-word hard floor)."""
    beats = [beat(f"B{i:02d}") for i in range(20)]  # many beats, short target
    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=60)
    assert all(v >= MIN_BEAT_WORDS for v in allocations.values())


def test_zero_duration_still_returns_the_floor_not_a_crash():
    beats = [beat("B01"), beat("B02")]
    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=0)
    assert allocations["B01"] >= MIN_BEAT_WORDS
    assert allocations["B02"] >= MIN_BEAT_WORDS
