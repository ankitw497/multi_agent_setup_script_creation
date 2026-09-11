"""Tests for planning/beat_word_budget.py -- the ERR-010/ERR-023 fix.

Deterministic allocation, no LLM -- the actual fix for A2 being unreliable
at summing a word budget across an entire multi-beat plan in one shot.
"""
from planning.beat_word_budget import MIN_BEAT_WORDS, allocate_beat_word_budgets
from planning.models import RetentionDeadline, StoryBeat


def beat(beat_id, source_unit_ids=None, archetype_role="") -> StoryBeat:
    return StoryBeat(beat_id=beat_id, purpose="x", source_unit_ids=source_unit_ids or [], archetype_role=archetype_role)


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


def test_no_retention_deadlines_does_not_change_behavior():
    beats = [beat("B01", ["u1"], archetype_role="central_problem"), beat("B02", ["u2", "u3", "u4"])]
    with_none = allocate_beat_word_budgets(beats, target_duration_seconds=600)
    with_empty = allocate_beat_word_budgets(beats, target_duration_seconds=600, retention_deadlines=[])
    assert with_none == with_empty


def test_retention_deadline_caps_the_matching_beat_and_redistributes_the_rest():
    """STORY_IMPROVEMENT_PLAN.md Phase 7 item #1: the confirmed bug -- a
    hook citing many source units got the same budget as an unrelated
    deep-dive section. A declared deadline must cap the hook beat's own
    cumulative runtime, with the reclaimed words going to other beats, not
    lost from the total."""
    beats = [
        beat("B01", ["u1", "u2", "u3", "u4", "u5"], archetype_role="central_problem"),
        beat("B02", ["u6"]),
    ]
    deadlines = [RetentionDeadline(archetype_role="central_problem", max_seconds=20)]

    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=600, retention_deadlines=deadlines)

    target_words = round(600 / 60 * 167)
    deadline_words = round(20 / 60 * 167)
    assert allocations["B01"] <= deadline_words
    assert sum(allocations.values()) == target_words  # reclaimed words land on B02, total unchanged
    assert allocations["B02"] == target_words - allocations["B01"]  # the only other beat absorbs all of it


def test_retention_deadline_never_caps_below_the_minimum_floor():
    beats = [beat("B01", ["u1"] * 10, archetype_role="central_problem"), beat("B02", ["u2"])]
    deadlines = [RetentionDeadline(archetype_role="central_problem", max_seconds=0.001)]

    allocations = allocate_beat_word_budgets(beats, target_duration_seconds=600, retention_deadlines=deadlines)

    assert allocations["B01"] == MIN_BEAT_WORDS


def test_retention_deadline_with_no_matching_archetype_role_is_a_no_op():
    beats = [beat("B01", ["u1"] * 5), beat("B02", ["u2"])]
    deadlines = [RetentionDeadline(archetype_role="nonexistent_role", max_seconds=10)]

    with_deadline = allocate_beat_word_budgets(beats, target_duration_seconds=600, retention_deadlines=deadlines)
    without = allocate_beat_word_budgets(beats, target_duration_seconds=600)

    assert with_deadline == without


def test_retention_deadline_already_satisfied_does_not_shrink_the_beat():
    beats = [beat("B01", ["u1"], archetype_role="central_problem"), beat("B02", ["u2"] * 5)]
    deadlines = [RetentionDeadline(archetype_role="central_problem", max_seconds=900)]

    with_deadline = allocate_beat_word_budgets(beats, target_duration_seconds=600, retention_deadlines=deadlines)
    without = allocate_beat_word_budgets(beats, target_duration_seconds=600)

    assert with_deadline == without
