"""D* retention diagnostics (plan §10.2). Deterministic -- computed directly
from StoryBeat's observable fields (new_information/payoff/
visual_mode_change/question_progress) and ScenePlan word budgets, no model
judgment and no voice corpus needed (unlike the voice diagnostic, which
does need a fitted corpus -- deferred to V1D per BUILD_PLAN.md).

Band thresholds here are the plan's own stated targets (payoff gap
~75-90s, a valley = 2+ consecutive dead beats), not yet corpus-calibrated
against real audience data -- consistent with the plan's own "bands
tighten against the channel's own data" (V1D). They are real, meaningful
thresholds regardless (the plan states them explicitly), just not yet
fitted the way voice bands eventually will be.

BUG-3 fix (STORY_IMPROVEMENT_PLAN.md Phase 8.4, 2026-09-11): `new_information`
is a boolean A2 sets about its own plan, so a plan that dutifully fills it
in passes by construction -- confirmed live: a real run returned GREEN on
every diagnostic here while a human review scored retention as that run's
weakest dimension. `_is_state_change()` now treats `ScenePlan.new_concepts`
(Phase 1's concept ledger, populated per-SCENE during A2b) as the primary
signal for "did this beat actually introduce something new" -- a concrete
list of concept labels is harder to satisfy by rote than one checkbox.
`payoff`/`visual_mode_change`/`question_progress` are kept as-is; nothing
scene-level captures those dimensions yet. The boolean is not discarded --
`check_new_information_disagreement()` turns a beat that claims
`new_information=True` with zero `new_concepts` into its own diagnostic
finding, per this phase's "keep it as a secondary signal" design.
"""
from __future__ import annotations

from planning.archetypes import get_archetype_spec
from planning.models import SourceBrief, StoryPlan
from review.models import DiagnosticResult
from verification.hard.text_overlap import overlap as _content_overlap

PLANNING_WPM = 167
PAYOFF_GAP_SECONDS = 90.0  # plan §10.2: "payoff gap > ~75-90s with no state change"
VALLEY_BEAT_COUNT = 2  # plan §10.2: "valley = consecutive beats with [no observable field true]"
# Deliberately soft (AMBER, not a hard gate) -- novelty is a judgment call and a
# word-overlap heuristic shouldn't block a run on its own (STORY_IMPROVEMENT_PLAN.md
# Phase 8.3). Reuses the same threshold check_promise_chain already uses for the same reason.
NOVELTY_OVERLAP_THRESHOLD = 0.15


def _beat_seconds(plan: StoryPlan) -> dict[str, float]:
    seconds: dict[str, float] = {}
    for scene in plan.scene_plan:
        seconds[scene.beat_id] = seconds.get(scene.beat_id, 0.0) + scene.word_budget / PLANNING_WPM * 60
    return seconds


def _beat_scenes(plan: StoryPlan, beat_id: str) -> list:
    return [s for s in plan.scene_plan if s.beat_id == beat_id]


def _introduces_new_concept(plan: StoryPlan, beat) -> bool:
    """Primary signal for "new information" (see module docstring, BUG-3
    fix): did any of this beat's own scenes carry a real `new_concepts`
    entry. Falls back to the self-reported `new_information` boolean only
    when the beat has zero scenes in `plan.scene_plan` at all -- a
    malformed plan, not the normal case -- so this never silently
    degrades to "always False" for a plan referential-integrity already
    flags elsewhere."""
    scenes = _beat_scenes(plan, beat.beat_id)
    if not scenes:
        return beat.new_information
    return any(s.new_concepts for s in scenes)


def _is_state_change(plan: StoryPlan, beat) -> bool:
    return _introduces_new_concept(plan, beat) or beat.payoff or beat.visual_mode_change or beat.question_progress != "none"


def check_driver_coverage(plan: StoryPlan) -> DiagnosticResult:
    """plan §10.2: "driver present in every beat" -- forward_driver stated non-blank."""
    if not plan.beats:
        return DiagnosticResult(dimension="retention.driver_coverage", band="RED", evidence="plan has no beats")
    with_driver = sum(1 for b in plan.beats if b.forward_driver.strip())
    ratio = with_driver / len(plan.beats)
    band = "GREEN" if ratio >= 0.9 else "AMBER" if ratio >= 0.7 else "RED"
    return DiagnosticResult(
        dimension="retention.driver_coverage", band=band, value=round(ratio, 2), target=">=0.90",
        evidence=f"{with_driver}/{len(plan.beats)} beats state a forward_driver toward "
                 f"the {plan.archetype!r} archetype's driver ({get_archetype_spec(plan.archetype).driver!r})",
    )


def check_valleys(plan: StoryPlan) -> DiagnosticResult:
    """plan §10.2: a "valley" is VALLEY_BEAT_COUNT+ consecutive beats that
    advance nothing observable."""
    run = 0
    worst_run = 0
    worst_start: str | None = None
    cur_start: str | None = None
    for beat in plan.beats:
        if _is_state_change(plan, beat):
            run = 0
            cur_start = None
            continue
        if run == 0:
            cur_start = beat.beat_id
        run += 1
        if run > worst_run:
            worst_run = run
            worst_start = cur_start

    if worst_run >= VALLEY_BEAT_COUNT:
        return DiagnosticResult(
            dimension="retention.valley", band="RED", value=worst_run, target=f"<{VALLEY_BEAT_COUNT}",
            evidence=f"{worst_run} consecutive beats starting at {worst_start!r} advance nothing observable "
                     f"(no scene introduces a new_concept, and payoff/visual_mode_change/question_progress all empty)",
        )
    return DiagnosticResult(
        dimension="retention.valley", band="GREEN", value=worst_run, target=f"<{VALLEY_BEAT_COUNT}",
        evidence="no valley found",
    )


def check_payoff_gap(plan: StoryPlan) -> DiagnosticResult:
    """plan §10.2: the longest continuous stretch of story time with no
    state-change beat, measured via each beat's scenes' word budgets."""
    beat_seconds = _beat_seconds(plan)
    run_seconds = 0.0
    worst = 0.0
    worst_start: str | None = None
    cur_start: str | None = None
    for beat in plan.beats:
        if _is_state_change(plan, beat):
            run_seconds = 0.0
            cur_start = None
            continue
        if cur_start is None:
            cur_start = beat.beat_id
        run_seconds += beat_seconds.get(beat.beat_id, 0.0)
        if run_seconds > worst:
            worst = run_seconds
            worst_start = cur_start

    band = "GREEN" if worst <= PAYOFF_GAP_SECONDS else "AMBER" if worst <= PAYOFF_GAP_SECONDS * 1.3 else "RED"
    return DiagnosticResult(
        dimension="retention.payoff_gap", band=band, value=round(worst, 1), target=f"<={PAYOFF_GAP_SECONDS:.0f}s",
        evidence=(f"longest stretch with no state change: {worst:.1f}s starting at beat {worst_start!r}"
                  if worst > 0 else "no gap -- every beat advances something observable"),
    )


def check_new_information_disagreement(plan: StoryPlan) -> DiagnosticResult:
    """BUG-3 fix, secondary signal (STORY_IMPROVEMENT_PLAN.md Phase 8.4): a
    beat that claims `new_information=True` but whose scenes introduce zero
    `new_concepts` is not necessarily wrong -- but the disagreement between
    the planner's own boolean and what A2b actually scoped for that beat is
    itself a real, useful finding (e.g. A2 marked a beat as introducing
    something new, then A2b's per-beat expansion decided every one of its
    scenes was a derivation/recap of prior material). Banded AMBER, never a
    hard failure -- this is a signal for a human/critic to look at, not
    proof of a defect."""
    # A beat with zero scenes at all has nothing to disagree WITH -- same
    # "trust the boolean" fallback _introduces_new_concept() itself uses,
    # not a disagreement (a malformed plan is reported by referential-
    # integrity checks elsewhere, not by this one).
    disagreeing = [
        b.beat_id for b in plan.beats
        if b.new_information and _beat_scenes(plan, b.beat_id)
        and not any(s.new_concepts for s in _beat_scenes(plan, b.beat_id))
    ]
    if disagreeing:
        return DiagnosticResult(
            dimension="retention.new_information_disagreement", band="AMBER",
            value=len(disagreeing),
            evidence=f"beat(s) claim new_information=True but no scene lists a new_concepts entry: {disagreeing}",
        )
    return DiagnosticResult(
        dimension="retention.new_information_disagreement", band="GREEN",
        evidence="every beat claiming new_information=True has at least one scene with a real new_concepts entry",
    )


def check_novelty_coverage(plan: StoryPlan, source_brief: SourceBrief) -> DiagnosticResult:
    """plan §9 Learning gate, soft part (STORY_IMPROVEMENT_PLAN.md Phase 8.3):
    `SourceBrief.novelty_statement` ("what this audience doesn't already
    know") was collected by A1, explicitly requested in its own prompt, and
    then never read by anything downstream -- confirmed via a full grep of
    the codebase. This is the first thing that actually reads it, banded as
    a diagnostic (never a hard gate) since "does the plan actually teach
    the stated novelty" is a judgment call a word-overlap heuristic can
    only approximate."""
    if not source_brief.novelty_statement.strip():
        return DiagnosticResult(
            dimension="retention.novelty_coverage", band="GREEN",
            evidence="no novelty_statement given -- nothing to check coverage against",
        )
    covered = any(
        _content_overlap(source_brief.novelty_statement, b.learning_objective) >= NOVELTY_OVERLAP_THRESHOLD
        for b in plan.beats if b.learning_objective.strip()
    )
    band = "GREEN" if covered else "AMBER"
    return DiagnosticResult(
        dimension="retention.novelty_coverage", band=band,
        evidence=(
            f"novelty_statement={source_brief.novelty_statement!r} is reflected in at least one "
            "beat's learning_objective" if covered else
            f"no beat's learning_objective shares real content with novelty_statement="
            f"{source_brief.novelty_statement!r} -- the plan may not actually teach the stated novelty"
        ),
    )


def check_retention(plan: StoryPlan) -> list[DiagnosticResult]:
    """The full D* retention pass -- every diagnostic, one call."""
    return [
        check_driver_coverage(plan), check_valleys(plan), check_payoff_gap(plan),
        check_new_information_disagreement(plan),
    ]
