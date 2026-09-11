"""D* hook-tension pacing diagnostic (plan §10.2: "tension reached inside
~30 s"), V2 narrative-continuity fix (STORY_IMPROVEMENT_PLAN.md Phase 2).

Fully deterministic, no LLM -- mirrors `verification/diagnostics/{retention,cta}.py`'s
pattern exactly (word_budget/167wpm as a duration proxy, banded not
pass/fail). `retention.py` already implements `check_driver_coverage`/
`check_valleys`/`check_payoff_gap` from this same plan §10.2 list, but
"tension reached inside ~30s" was never wired up -- a real, confirmed gap,
not a new requirement invented for this fix.

Real finding this addresses (`multi_agent_script_and_model_feedback.md`
§2.1): a live generated script spent roughly 180s establishing the central
problem before the real mechanism began. This measures the hook's own
on-screen time directly.
"""
from __future__ import annotations

import statistics

from facts.models import Claim
from planning.models import StoryPlan
from review.models import DiagnosticResult

PLANNING_WPM = 167
HOOK_TENSION_TARGET_SECONDS = 30.0  # plan §10.2: "tension reached inside ~30 s"
HOOK_TENSION_AMBER_MARGIN_SECONDS = 30.0  # up to ~60s still counts as AMBER, not RED
AIRTIME_OUTLIER_RATIO = 2.0  # a beat using >2x or <0.5x the plan's own median words-per-claim


def _hook_scene_seconds(plan: StoryPlan) -> float:
    """Scoped to the plan's FIRST beat only -- the first-positioned beat IS
    the opening by construction. Within that beat, prefers scenes
    explicitly tagged `narrative_beat="hook"`; falls back to every scene
    in the beat when none are tagged that way (a real data-quality gap,
    not something to silently treat as zero seconds).

    BUG-2 fix (STORY_IMPROVEMENT_PLAN.md Phase 2, 2026-09-11): this used to
    scan the WHOLE plan for `narrative_beat="hook"` scenes, but A2b tags
    "hook" onto the first scene of many different beats as a per-section
    rhetorical device, not exclusively the video's true opening -- a real
    plan had it on 7 different beats, inflating a genuine 64s hook into a
    measured 143s by summing scenes scattered near the end of the video
    too. Restricting the tag-scan to the first beat's own scenes fixes
    this without losing the tag-preference behavior within that beat."""
    if not plan.beats:
        return 0.0
    first_beat_id = plan.beats[0].beat_id
    first_beat_scenes = [s for s in plan.scene_plan if s.beat_id == first_beat_id]

    hook_scenes = [s for s in first_beat_scenes if s.narrative_beat == "hook"]
    scenes = hook_scenes if hook_scenes else first_beat_scenes
    return sum(s.word_budget for s in scenes) / PLANNING_WPM * 60


def check_hook_tension_pacing(plan: StoryPlan) -> DiagnosticResult:
    hook_seconds = _hook_scene_seconds(plan)
    if hook_seconds <= 0:
        return DiagnosticResult(
            dimension="pacing.hook_tension", band="RED",
            evidence="no hook-tagged scene and no beats at all -- cannot confirm tension is ever reached",
        )

    target = HOOK_TENSION_TARGET_SECONDS
    if hook_seconds <= target:
        band = "GREEN"
    elif hook_seconds <= target + HOOK_TENSION_AMBER_MARGIN_SECONDS:
        band = "AMBER"
    else:
        band = "RED"

    return DiagnosticResult(
        dimension="pacing.hook_tension", band=band, value=round(hook_seconds, 1),
        target=f"<= {target:.0f}s",
        evidence=f"hook scenes take {hook_seconds:.0f}s of narration before the central tension is established",
    )


def check_beat_airtime_outliers(plan: StoryPlan, claims: list[Claim]) -> DiagnosticResult:
    """STORY_IMPROVEMENT_PLAN.md Phase 7 item #1: the plan's aggregate word
    budget can match its target exactly while an individual beat is still
    a real outlier -- confirmed live (`gpt-5.6-sol` tuned run): masking and
    heads sections ran 30-50% over what their own content needed while the
    overall video had slack elsewhere. `check_word_budget_matches_target`
    (hard gate) only ever checks the sum; this checks the DISTRIBUTION,
    using each beat's own content density (claims actually available to
    it) as the yardstick rather than a fixed word-count band that would
    have to be re-tuned per video length."""
    claims_per_unit: dict[str, int] = {}
    for claim in claims:
        claims_per_unit[claim.source_unit] = claims_per_unit.get(claim.source_unit, 0) + 1

    ratios: dict[str, float] = {}
    for beat in plan.beats:
        claim_count = sum(claims_per_unit.get(u, 0) for u in beat.source_unit_ids)
        if claim_count == 0:
            continue
        allocated_words = sum(s.word_budget for s in plan.scene_plan if s.beat_id == beat.beat_id)
        if allocated_words == 0:
            continue
        ratios[beat.beat_id] = allocated_words / claim_count

    if len(ratios) < 3:
        return DiagnosticResult(
            dimension="pacing.beat_airtime_outliers", band="GREEN",
            evidence=f"only {len(ratios)} beat(s) have both claims and an allocated word budget -- "
                     "not enough to assess a distribution",
        )

    median_ratio = statistics.median(ratios.values())
    outliers = [
        f"{beat_id} ({ratio / median_ratio:.1f}x median)"
        for beat_id, ratio in ratios.items()
        if median_ratio > 0 and (ratio > median_ratio * AIRTIME_OUTLIER_RATIO or ratio < median_ratio / AIRTIME_OUTLIER_RATIO)
    ]

    if not outliers:
        return DiagnosticResult(
            dimension="pacing.beat_airtime_outliers", band="GREEN",
            value=round(median_ratio, 1), target=f"within {AIRTIME_OUTLIER_RATIO:.0f}x median words-per-claim",
            evidence=f"every beat's words-per-claim stays within {AIRTIME_OUTLIER_RATIO:.0f}x the "
                     f"plan's own median ({median_ratio:.1f})",
        )

    return DiagnosticResult(
        dimension="pacing.beat_airtime_outliers", band="AMBER",
        value=round(median_ratio, 1), target=f"within {AIRTIME_OUTLIER_RATIO:.0f}x median words-per-claim",
        evidence=f"beat(s) allocated a disproportionate airtime relative to their own content "
                 f"density (median words/claim={median_ratio:.1f}): {', '.join(outliers)}",
    )
