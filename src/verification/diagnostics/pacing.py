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
# STORY_IMPROVEMENT_PLAN.md Phase 23 item "First full payoff...lands ~5:00 into an 11-minute
# video": that real example measured 45.5% of runtime, flagged as too late -- the CTA can only
# sit AFTER the first payoff beat (verification/hard/structure.py::check_cta_placement) and
# Phase 23's own CTA-position fix targets 20-40% of runtime, so a payoff landing past that band
# leaves no real room for the CTA to sit comfortably after it.
PRIMARY_PAYOFF_TARGET_FRACTION = 0.35
PRIMARY_PAYOFF_AMBER_FRACTION = 0.50


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
    # STORY_IMPROVEMENT_PLAN.md Phase 23 item "B1 (hook) measured at 0.5x median airtime":
    # investigated against plan §10.2's own design intent ("the interesting event happens
    # immediately") -- a hook using FEWER words per available claim than a teaching beat is
    # the deliberate shape of a hook (brief, high-tension, not a proportional tour of every
    # claim it touches), not a defect. Same recalibration precedent as shorts'
    # SETUP_LENGTH_TARGET_SECONDS (ERR-068): the general per-beat proportionality target is
    # wrong for a beat serving a structurally different narrative function, so the FIRST beat
    # (the hook, by construction -- mirrors `_hook_scene_seconds`'s own first-beat-is-the-
    # opening rule) is excluded from the distribution entirely, never just exempted from being
    # flagged -- leaving it in would still skew the median every other beat is compared against.
    hook_beat_id = plan.beats[0].beat_id if plan.beats else None

    claims_per_unit: dict[str, int] = {}
    for claim in claims:
        claims_per_unit[claim.source_unit] = claims_per_unit.get(claim.source_unit, 0) + 1

    ratios: dict[str, float] = {}
    for beat in plan.beats:
        if beat.beat_id == hook_beat_id:
            continue
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


def check_time_to_primary_payoff(plan: StoryPlan, target_duration_seconds: float) -> DiagnosticResult:
    """STORY_IMPROVEMENT_PLAN.md Phase 23 item: `check_beat_airtime_outliers` only ever
    measures per-beat proportionality, never "how long until the video's own biggest payoff
    actually lands" -- confirmed live as a real gap on a script whose ending beat ran 2x its
    fair share while the first full payoff didn't land until ~45.5% of the way through.

    Reuses `StoryBeat.payoff` (the same marker `verification/hard/structure.py::
    check_cta_placement` already treats as "the first beat that actually earns a payoff") --
    the FIRST beat with `payoff=True`, mirroring `_hook_scene_seconds`'s own
    first-occurrence-by-construction pattern. Measures cumulative narration time through the
    END of that beat (when the payoff has actually landed for the viewer), not just up to its
    start."""
    if not plan.beats:
        return DiagnosticResult(
            dimension="pacing.time_to_primary_payoff", band="RED", evidence="plan has no beats",
        )

    payoff_beat_id = next((b.beat_id for b in plan.beats if b.payoff), None)
    if payoff_beat_id is None:
        return DiagnosticResult(
            dimension="pacing.time_to_primary_payoff", band="RED",
            evidence="no beat is marked payoff=True -- cannot confirm when (or whether) the primary payoff lands",
        )

    beat_ids_through_payoff = []
    for beat in plan.beats:
        beat_ids_through_payoff.append(beat.beat_id)
        if beat.beat_id == payoff_beat_id:
            break

    payoff_seconds = sum(
        s.word_budget for s in plan.scene_plan if s.beat_id in beat_ids_through_payoff
    ) / PLANNING_WPM * 60

    if target_duration_seconds <= 0:
        return DiagnosticResult(
            dimension="pacing.time_to_primary_payoff", band="RED",
            evidence=f"target_duration_seconds={target_duration_seconds} -- cannot compute a fraction of runtime",
        )

    fraction = payoff_seconds / target_duration_seconds
    if fraction <= PRIMARY_PAYOFF_TARGET_FRACTION:
        band = "GREEN"
    elif fraction <= PRIMARY_PAYOFF_AMBER_FRACTION:
        band = "AMBER"
    else:
        band = "RED"

    return DiagnosticResult(
        dimension="pacing.time_to_primary_payoff", band=band, value=round(fraction, 2),
        target=f"<= {PRIMARY_PAYOFF_TARGET_FRACTION:.0%} of runtime",
        evidence=f"the primary payoff (beat {payoff_beat_id!r}) lands at {payoff_seconds:.0f}s "
                 f"({fraction:.0%} of the {target_duration_seconds:.0f}s target runtime)",
    )


# STORY_IMPROVEMENT_PLAN.md Phase 25 item 2: a real plan marked payoff=True on 10 of 12
# beats (83%), making the field meaningless and pulling check_time_to_primary_payoff/
# check_cta_placement's own "first beat with a real payoff" anchor onto an early, minor
# beat instead of the video's actual central payoff. A healthy plan should mark only its
# few truly central payoff(s); everything else belongs in mini_payoffs instead.
PAYOFF_BEAT_RATIO_TARGET = 0.3
PAYOFF_BEAT_RATIO_AMBER_MAX = 0.5


def check_payoff_beat_ratio(plan: StoryPlan) -> DiagnosticResult:
    if not plan.beats:
        return DiagnosticResult(dimension="pacing.payoff_beat_ratio", band="RED", evidence="plan has no beats")

    payoff_count = sum(1 for b in plan.beats if b.payoff)
    ratio = payoff_count / len(plan.beats)

    if ratio <= PAYOFF_BEAT_RATIO_TARGET:
        band = "GREEN"
    elif ratio <= PAYOFF_BEAT_RATIO_AMBER_MAX:
        band = "AMBER"
    else:
        band = "RED"

    return DiagnosticResult(
        dimension="pacing.payoff_beat_ratio", band=band, value=round(ratio, 2),
        target=f"<= {PAYOFF_BEAT_RATIO_TARGET:.0%} of beats",
        evidence=f"{payoff_count}/{len(plan.beats)} beats ({ratio:.0%}) are marked payoff=True -- "
                 "a plan where most beats claim a real payoff makes 'the primary payoff beat' "
                 "an unreliable anchor for other checks",
    )


# STORY_IMPROVEMENT_PLAN.md Phase 25 item 5: a real closing beat had 7 of its 9 scenes
# tagged scene_function="recap" with zero new_concepts between them -- the mechanism got
# re-taught a second time right after its real payoff had already landed. Applies to any
# beat, not just the last one (the last beat is simply where this is most damaging).
RECAP_BLOAT_RATIO_TARGET = 0.5


def check_recap_bloat(plan: StoryPlan) -> DiagnosticResult:
    worst_beat_id: str | None = None
    worst_ratio = 0.0
    worst_counts = (0, 0)

    for beat in plan.beats:
        scenes = [s for s in plan.scene_plan if s.beat_id == beat.beat_id]
        if not scenes:
            continue
        pure_recap = sum(1 for s in scenes if s.scene_function == "recap" and not s.new_concepts)
        ratio = pure_recap / len(scenes)
        if ratio > worst_ratio:
            worst_ratio, worst_beat_id, worst_counts = ratio, beat.beat_id, (pure_recap, len(scenes))

    if worst_beat_id is None:
        return DiagnosticResult(
            dimension="pacing.recap_bloat", band="GREEN",
            evidence="no beat has any scenes to assess" if not plan.scene_plan else "no beat is recap-dominated",
        )

    band = "AMBER" if worst_ratio > RECAP_BLOAT_RATIO_TARGET else "GREEN"
    pure_recap, total = worst_counts
    return DiagnosticResult(
        dimension="pacing.recap_bloat", band=band, value=round(worst_ratio, 2),
        target=f"<= {RECAP_BLOAT_RATIO_TARGET:.0%} of a beat's scenes pure recap",
        evidence=(
            f"beat {worst_beat_id!r} has {pure_recap}/{total} scenes tagged recap with zero "
            "new_concepts -- consider compressing it into fewer scenes" if band == "AMBER" else
            f"no beat exceeds {RECAP_BLOAT_RATIO_TARGET:.0%} pure-recap scenes (worst: "
            f"{worst_beat_id!r} at {worst_ratio:.0%})"
        ),
    )
