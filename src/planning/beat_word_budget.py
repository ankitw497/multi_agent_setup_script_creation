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

from planning.models import RetentionDeadline, ScenePlan, StoryBeat

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


def redistribute_rebudgeted_words(
    beat_word_budgets: dict[str, int], scene_plan: list[ScenePlan],
) -> list[ScenePlan]:
    """STORY_IMPROVEMENT_PLAN.md Phase 12: A2b may set `ScenePlan.needs_rebudget=True` on a
    beat's scenes when that beat's real content genuinely didn't support its allocated
    `target_words` without padding -- a legitimate outcome, not a defect. The words it left on
    the table are redistributed here, deterministically, to scenes in beats that did NOT flag
    it (real remaining depth), each scene capped at its own 30-100 hard bound
    (`ScenePlan.word_budget`'s own `Field` constraint) -- never forced back onto the
    under-budget beat as filler, and never a second LLM call.

    A no-op (returns `scene_plan` unchanged) when nothing flagged `needs_rebudget`, or when
    every other scene is already at its own 100-word ceiling."""
    scenes_by_beat: dict[str, list[ScenePlan]] = {}
    for scene in scene_plan:
        scenes_by_beat.setdefault(scene.beat_id, []).append(scene)

    flagged_beat_ids = {
        beat_id for beat_id, scenes in scenes_by_beat.items() if any(s.needs_rebudget for s in scenes)
    }
    if not flagged_beat_ids:
        return scene_plan

    deficit = sum(
        max(0, beat_word_budgets.get(beat_id, 0) - sum(s.word_budget for s in scenes))
        for beat_id, scenes in scenes_by_beat.items() if beat_id in flagged_beat_ids
    )
    if deficit <= 0:
        return scene_plan

    eligible_ids = [
        s.scene_id for s in scene_plan if s.beat_id not in flagged_beat_ids and s.word_budget < 100
    ]
    if not eligible_ids:
        return scene_plan  # nothing left with headroom -- fine, the target is a soft band anyway

    current = {s.scene_id: s.word_budget for s in scene_plan}
    remaining = deficit
    pool = list(eligible_ids)
    while remaining > 0 and pool:
        share = max(1, remaining // len(pool))
        next_pool = []
        for scene_id in pool:
            headroom = 100 - current[scene_id]
            if headroom <= 0:
                continue
            add = min(share, headroom, remaining)
            current[scene_id] += add
            remaining -= add
            if current[scene_id] < 100:
                next_pool.append(scene_id)
            if remaining <= 0:
                break
        pool = next_pool

    return [
        s.model_copy(update={"word_budget": current[s.scene_id]}) if current[s.scene_id] != s.word_budget else s
        for s in scene_plan
    ]
