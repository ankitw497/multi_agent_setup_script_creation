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

from planning.models import StoryBeat

PLANNING_WPM = 167
MIN_BEAT_WORDS = 30  # ScenePlan's own hard floor (plan §9) -- a beat allocated less than
                      # this can't even produce one valid scene


def allocate_beat_word_budgets(
    beats: list[StoryBeat], target_duration_seconds: float, planning_wpm: int = PLANNING_WPM,
) -> dict[str, int]:
    """beat_id -> target word count, proportional to how much source content
    each beat covers (len(source_unit_ids)), falling back to an even split
    when no beat references any source units. The last beat absorbs any
    rounding remainder so the allocations always sum to exactly the target
    (never drift from it the way an LLM's own aggregate sum would)."""
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

    return allocations
