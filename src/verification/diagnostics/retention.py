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
"""
from __future__ import annotations

from planning.archetypes import get_archetype_spec
from planning.models import StoryPlan
from review.models import DiagnosticResult

PLANNING_WPM = 167
PAYOFF_GAP_SECONDS = 90.0  # plan §10.2: "payoff gap > ~75-90s with no state change"
VALLEY_BEAT_COUNT = 2  # plan §10.2: "valley = consecutive beats with [no observable field true]"


def _beat_seconds(plan: StoryPlan) -> dict[str, float]:
    seconds: dict[str, float] = {}
    for scene in plan.scene_plan:
        seconds[scene.beat_id] = seconds.get(scene.beat_id, 0.0) + scene.word_budget / PLANNING_WPM * 60
    return seconds


def _is_state_change(beat) -> bool:
    return beat.new_information or beat.payoff or beat.visual_mode_change or beat.question_progress != "none"


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
        if _is_state_change(beat):
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
                     f"(new_information/payoff/visual_mode_change/question_progress all empty)",
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
        if _is_state_change(beat):
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


def check_retention(plan: StoryPlan) -> list[DiagnosticResult]:
    """The full D* retention pass -- every diagnostic, one call."""
    return [check_driver_coverage(plan), check_valleys(plan), check_payoff_gap(plan)]
