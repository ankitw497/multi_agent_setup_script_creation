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
from planning.models import SourceBrief, StoryPlan

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


def check_source_disposition(plan: StoryPlan, all_source_unit_ids: list[str]) -> list[StructuralIssue]:
    """STORY_IMPROVEMENT_PLAN.md Phase 11: replaces the old blanket rule ("every source unit
    must be referenced by a beat"), which forced peripheral source content into the video even
    when it should have been deferred -- the confirmed real cause (per an external review of a
    live GPT-5.6-sol run) of a video's actual scope drifting wider than its title. A2 now gives
    every unit an explicit `SourceCoverageDecision`; the hard gate here only requires that (a)
    every unit actually got one (nothing silently dropped without a stated reason) and (b) a
    unit A2 itself marked MUST_COVER or SUPPORTING actually shows up in a beat -- DEFERRED/
    REDUNDANT/META_ONLY are legitimate outcomes that need no beat at all."""
    decided = {d.source_unit_id: d for d in plan.source_coverage}
    issues: list[StructuralIssue] = []

    missing_decision = [uid for uid in all_source_unit_ids if uid not in decided]
    if missing_decision:
        issues.append(StructuralIssue(
            "source_unit_missing_disposition", f"never classified with a disposition: {missing_decision}",
        ))

    covered = {uid for beat in plan.beats for uid in beat.source_unit_ids}
    uncovered_required = [
        d.source_unit_id for d in plan.source_coverage
        if d.disposition in ("MUST_COVER", "SUPPORTING") and d.source_unit_id not in covered
    ]
    if uncovered_required:
        detail = "; ".join(f"{uid} ({decided[uid].disposition}, reason: {decided[uid].reason!r})" for uid in uncovered_required)
        issues.append(StructuralIssue("required_source_unit_uncovered", f"never referenced by any beat: {detail}"))

    return issues


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


def check_learning_gate(plan: StoryPlan, source_brief: SourceBrief) -> list[StructuralIssue]:
    """plan §9 Learning gate, structural part (`IMPLEMENTATION_PLAN.md:669`):
    "no central_insight; a major beat with no learning_objective;
    viewer_can_now not reachable from the beats' objectives." Designed as a
    hard gate from the start; confirmed entirely unbuilt
    (STORY_IMPROVEMENT_PLAN.md Phase 8.3) until now.

    "Major beat" is approximated as any beat with a non-blank
    `archetype_role` -- `story_planner.py`'s own prompt already treats a
    blank `archetype_role` as the rare exception, not the norm, so this
    reuses an existing convention rather than inventing a new one.
    """
    issues: list[StructuralIssue] = []

    if not source_brief.central_insight.strip():
        issues.append(StructuralIssue("no_central_insight", "source_brief.central_insight is empty"))

    major_beats = [b for b in plan.beats if b.archetype_role.strip()]
    missing_objective = [b.beat_id for b in major_beats if not b.learning_objective.strip()]
    if missing_objective:
        issues.append(StructuralIssue(
            "beat_missing_learning_objective",
            f"beat(s) with a real archetype_role have no learning_objective: {missing_objective}",
        ))

    if plan.beats and not any(
        _promise_overlap(plan.ending.viewer_can_now, b.learning_objective) >= PROMISE_OVERLAP_THRESHOLD
        for b in plan.beats if b.learning_objective.strip()
    ):
        issues.append(StructuralIssue(
            "viewer_can_now_unreachable",
            f"ending.viewer_can_now={plan.ending.viewer_can_now!r} shares no real content "
            "with any beat's learning_objective",
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
    source_brief: SourceBrief | None = None,
) -> list[StructuralIssue]:
    """The full V* structural pass -- every hard check, one call.

    `source_brief` is optional (default `None` skips `check_learning_gate`
    entirely) so existing callers/tests that don't have one in scope keep
    working unchanged -- every real caller in `orchestration/pipeline.py`
    does have it and should pass it.
    """
    return (
        check_word_budget_matches_target(plan, target_duration_seconds)
        + check_every_beat_has_source_units(plan)
        + check_source_disposition(plan, all_source_unit_ids)
        + check_referential_integrity(plan)
        + check_core_roles_present(plan)
        + check_promise_chain(plan)
        + check_cta_placement(plan)
        + (check_learning_gate(plan, source_brief) if source_brief is not None else [])
    )
