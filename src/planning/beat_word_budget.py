"""Deterministic per-beat word-budget allocation (plan §9). No LLM.

The actual fix for ERR-010/ERR-023: asking A2 to correctly sum a word
budget across an entire multi-beat plan in one shot is a task LLMs are
reliably unreliable at (a live run returned 5 scenes / ~525 words against
a ~1670-word target, even with explicit calibration instructions). The
arithmetic itself is trivial -- it's exactly the kind of aggregate sum
that must be deterministic, not model-voted (the same principle
verification/hard/structure.py's own docstring states for word-budget
checking, applied here one step earlier, at allocation time instead of
only at verification time).
"""
from __future__ import annotations

from planning.models import RetentionDeadline, StoryBeat

PLANNING_WPM = 167
MIN_BEAT_WORDS = 30  # ScenePlan's own hard floor (plan §9) -- a beat allocated less than
                      # this can't even produce one valid scene


def allocate_beat_word_budgets(
    beats: list[StoryBeat], target_duration_seconds: float, planning_wpm: int = PLANNING_WPM,
    retention_deadlines: list[RetentionDeadline] | None = None,
) -> dict[str, int]:
    """beat_id -> target word count, proportional to how much source content
    each beat covers (len(source_unit_ids)), falling back to an even split
    when no beat references any source units. The last beat absorbs any
    rounding remainder so the allocations always sum to exactly the target
    (never drift from it the way an LLM's own aggregate sum would).

    STORY_IMPROVEMENT_PLAN.md Phase 7 item #1: proportional-by-citation-
    count alone let a beat's airtime be driven entirely by how much source
    material it cites, not its narrative/retention importance -- a
    confirmed live bug where the hook received the same budget as an
    unrelated deep-dive section. `retention_deadlines` (optional, empty by
    default -- no behavior change for a plan that doesn't set any) caps a
    named `archetype_role`'s beat so the CUMULATIVE runtime up to and
    including it never exceeds its declared `max_seconds`; the reclaimed
    words are redistributed proportionally across every other beat, so the
    total still sums to exactly `target_words`."""
    if not beats:
        return {}

    target_words = round(target_duration_seconds / 60 * planning_wpm)
    weights = [max(1, len(b.source_unit_ids)) for b in beats]
    total_weight = sum(weights)

    allocations: dict[str, int] = {}
    allocated_so_far = 0
    for i, (beat, weight) in enumerate(zip(beats, weights)):
        if i == len(beats) - 1:
            words = target_words - allocated_so_far  # remainder -- keeps the sum exact
        else:
            words = round(target_words * weight / total_weight)
        allocations[beat.beat_id] = max(words, MIN_BEAT_WORDS)
        allocated_so_far += words

    if retention_deadlines:
        allocations = _apply_retention_deadlines(beats, allocations, retention_deadlines, planning_wpm)

    return allocations


def _apply_retention_deadlines(
    beats: list[StoryBeat], allocations: dict[str, int],
    retention_deadlines: list[RetentionDeadline], planning_wpm: int,
) -> dict[str, int]:
    deadline_by_role = {d.archetype_role: d.max_seconds for d in retention_deadlines}
    cumulative_words = 0
    for beat in beats:
        cumulative_words += allocations[beat.beat_id]
        max_seconds = deadline_by_role.get(beat.archetype_role)
        if max_seconds is None:
            continue
        deadline_words = round(max_seconds / 60 * planning_wpm)
        overshoot = cumulative_words - deadline_words
        if overshoot <= 0:
            continue
        capped_words = max(MIN_BEAT_WORDS, allocations[beat.beat_id] - overshoot)
        actual_reclaimed = allocations[beat.beat_id] - capped_words
        if actual_reclaimed <= 0:
            continue
        allocations[beat.beat_id] = capped_words
        cumulative_words -= actual_reclaimed
        _redistribute(beats, allocations, exclude_beat_id=beat.beat_id, extra_words=actual_reclaimed)
    return allocations


def _redistribute(
    beats: list[StoryBeat], allocations: dict[str, int], exclude_beat_id: str, extra_words: int,
) -> None:
    recipients = [b for b in beats if b.beat_id != exclude_beat_id]
    if not recipients:
        return
    weights = [max(1, len(b.source_unit_ids)) for b in recipients]
    total_weight = sum(weights)
    distributed = 0
    for i, (beat, weight) in enumerate(zip(recipients, weights)):
        if i == len(recipients) - 1:
            share = extra_words - distributed  # remainder -- keeps the total exact
        else:
            share = round(extra_words * weight / total_weight)
        allocations[beat.beat_id] += share
        distributed += share
