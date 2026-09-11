"""Structural hard checks on a StoryPlan (plan §9). Deterministic, no LLM.

A StoryPlan's internal referential integrity and its calibration against
its own stated target must never be model-voted -- exactly the same
principle the plan applies to arithmetic (design doc: "arithmetic is
deterministic, not model-voted"), extended to structural counting, which
LLMs are demonstrably unreliable at (see the real findings this locks in
as regression tests: an empty source_unit_ids on every beat, and a scene
plan totalling 460 words against a 1,670-word target).
"""
from __future__ import annotations

from dataclasses import dataclass

from planning.archetypes import get_archetype_spec
from planning.models import StoryPlan

from .text_overlap import DEFAULT_OVERLAP_THRESHOLD
from .text_overlap import overlap as _promise_overlap

PLANNING_WPM = 167
WORD_BUDGET_TOLERANCE = 0.30  # generous -- LLMs are unreliable at exact aggregate sums; see module docstring

# plan §9's promise-chain gate is genuinely about semantic relatedness, which
# a hard (mechanical) gate can only approximate -- a word-overlap ratio, not
# real judgement. Set low deliberately: this exists to catch a promise chain
# that is truly disconnected (a title about one thing, a hook about another),
# not to penalize a hook/ending that pays off the same promise in different
# words. False negatives here are fine (C1 can still judge this); false
# positives on legitimate paraphrase would be worse than not having the gate.
PROMISE_OVERLAP_THRESHOLD = DEFAULT_OVERLAP_THRESHOLD


@dataclass
class StructuralIssue:
    code: str
    detail: str


def check_word_budget_matches_target(plan: StoryPlan, target_duration_seconds: float) -> list[StructuralIssue]:
    if target_duration_seconds <= 0:
        return []
    total_words = sum(s.word_budget for s in plan.scene_plan)
    target_words = target_duration_seconds / 60 * PLANNING_WPM
    ratio = total_words / target_words if target_words else 0
    if abs(ratio - 1.0) > WORD_BUDGET_TOLERANCE:
        return [StructuralIssue(
            "word_budget_mismatch",
            f"scene_plan totals {total_words} words but target is ~{target_words:.0f} words "
            f"for {target_duration_seconds:.0f}s at {PLANNING_WPM}wpm (ratio {ratio:.2f})",
        )]
    return []


def check_every_beat_has_source_units(plan: StoryPlan) -> list[StructuralIssue]:
    return [
        StructuralIssue("beat_missing_source_units", f"beat {b.beat_id} has no source_unit_ids")
        for b in plan.beats if not b.source_unit_ids
    ]


def check_source_coverage(plan: StoryPlan, all_source_unit_ids: list[str]) -> list[StructuralIssue]:
    covered = {uid for beat in plan.beats for uid in beat.source_unit_ids}
    missing = [uid for uid in all_source_unit_ids if uid not in covered]
    if missing:
        return [StructuralIssue("source_units_uncovered", f"never referenced by any beat: {missing}")]
    return []


def check_referential_integrity(plan: StoryPlan) -> list[StructuralIssue]:
    issues: list[StructuralIssue] = []
    beat_ids = {b.beat_id for b in plan.beats}
    scene_ids = [s.scene_id for s in plan.scene_plan]

    dupes = {sid for sid in scene_ids if scene_ids.count(sid) > 1}
    if dupes:
        issues.append(StructuralIssue("duplicate_scene_ids", f"duplicate scene ids: {dupes}"))

    for scene in plan.scene_plan:
        if scene.beat_id not in beat_ids:
            issues.append(StructuralIssue(
                "scene_references_unknown_beat", f"scene {scene.scene_id} references unknown beat {scene.beat_id}",
            ))

    if plan.cta.primary_after_beat not in beat_ids:
        issues.append(StructuralIssue(
            "cta_references_unknown_beat", f"cta.primary_after_beat={plan.cta.primary_after_beat!r} is not a real beat",
        ))

    for mp in plan.mini_payoffs:
        if mp.after_beat not in beat_ids:
            issues.append(StructuralIssue(
                "mini_payoff_references_unknown_beat", f"mini_payoff after_beat={mp.after_beat!r} is not a real beat",
            ))

    return issues


def check_core_roles_present(plan: StoryPlan) -> list[StructuralIssue]:
    """The actual plan §9 hard gate: a CORE role of the resolved archetype
    must be represented among the beats. Optional roles are diagnostics
    only (plan §9's core-vs-optional table) -- never checked here."""
    spec = get_archetype_spec(plan.archetype)
    present_stages = {b.archetype_stage for b in plan.beats if b.archetype_stage}
    missing_core = [role for role in spec.core_roles if role not in present_stages]
    if missing_core:
        return [StructuralIssue(
            "core_role_missing", f"archetype {plan.archetype!r} core role(s) not represented: {missing_core}",
        )]
    return []


def check_promise_chain(plan: StoryPlan) -> list[StructuralIssue]:
    """plan §9 Structural story gate: "title promise unrelated to the hook
    or the hook promise unpaid by the ending". See PROMISE_OVERLAP_THRESHOLD
    for why this is a deliberately generous word-overlap proxy, not real
    semantic judgement -- C1 remains the actual judge of a subtle mismatch."""
    issues = []
    if _promise_overlap(plan.title.promise, plan.hook.promise) < PROMISE_OVERLAP_THRESHOLD:
        issues.append(StructuralIssue(
            "title_promise_unrelated_to_hook",
            f"title.promise={plan.title.promise!r} shares almost no content with hook.promise={plan.hook.promise!r}",
        ))
    if _promise_overlap(plan.hook.promise, plan.ending.resolve_hook) < PROMISE_OVERLAP_THRESHOLD:
        issues.append(StructuralIssue(
            "hook_promise_unpaid_by_ending",
            f"hook.promise={plan.hook.promise!r} is not reflected in ending.resolve_hook={plan.ending.resolve_hook!r}",
        ))
    return issues


def check_cta_placement(plan: StoryPlan) -> list[StructuralIssue]:
    """plan §9 CTA hard gate (partial -- `max_ctas<=2` is already enforced
    at the model level by CTAContract's own Field bound, so it can never
    even reach this check): the CTA must not sit in the hook (the very
    first beat) and must come no earlier than the first beat that actually
    earns a payoff."""
    if not plan.beats:
        return []
    beat_ids = [b.beat_id for b in plan.beats]
    if plan.cta.primary_after_beat not in beat_ids:
        return []  # already reported by check_referential_integrity
    cta_index = beat_ids.index(plan.cta.primary_after_beat)

    issues = []
    if cta_index == 0:
        issues.append(StructuralIssue(
            "cta_in_hook",
            f"cta.primary_after_beat={plan.cta.primary_after_beat!r} is the first beat -- no payoff has been earned yet",
        ))
    first_payoff_index = next((i for i, b in enumerate(plan.beats) if b.payoff), None)
    if first_payoff_index is not None and cta_index < first_payoff_index:
        issues.append(StructuralIssue(
            "cta_before_first_payoff",
            f"cta.primary_after_beat={plan.cta.primary_after_beat!r} (beat {cta_index}) comes before "
            f"the first payoff beat ({plan.beats[first_payoff_index].beat_id}, beat {first_payoff_index})",
        ))
    return issues


def check_structure(
    plan: StoryPlan, target_duration_seconds: float, all_source_unit_ids: list[str],
) -> list[StructuralIssue]:
    """The full V* structural pass -- every hard check, one call."""
    return (
        check_word_budget_matches_target(plan, target_duration_seconds)
        + check_every_beat_has_source_units(plan)
        + check_source_coverage(plan, all_source_unit_ids)
        + check_referential_integrity(plan)
        + check_core_roles_present(plan)
        + check_promise_chain(plan)
        + check_cta_placement(plan)
    )
