"""D* CTA diagnostic (plan §10.3): position vs the 20-40% target band.

The non-negotiable placement rules (not in the hook, not before the first
payoff) are hard gates -- see verification/hard/structure.py's
check_cta_placement. This is the softer "is it roughly in the right third
of the video" signal, banded rather than pass/fail, using the same
ScenePlan word-budget-as-duration-proxy the rest of the pipeline uses.
"""
from __future__ import annotations

from planning.models import StoryPlan
from review.models import DiagnosticResult

PLANNING_WPM = 167
CTA_POSITION_BAND = (0.20, 0.40)  # plan §10.3
CTA_POSITION_AMBER_MARGIN = 0.10  # how far outside the band still counts as AMBER, not RED


def check_cta_position(plan: StoryPlan) -> DiagnosticResult:
    beat_seconds: dict[str, float] = {}
    for scene in plan.scene_plan:
        beat_seconds[scene.beat_id] = beat_seconds.get(scene.beat_id, 0.0) + scene.word_budget / PLANNING_WPM * 60
    total = sum(beat_seconds.values())

    if total <= 0 or plan.cta.primary_after_beat not in beat_seconds:
        return DiagnosticResult(
            dimension="cta.position", band="RED",
            evidence=f"no scene timing available for cta.primary_after_beat={plan.cta.primary_after_beat!r}",
        )

    elapsed = 0.0
    for beat in plan.beats:
        elapsed += beat_seconds.get(beat.beat_id, 0.0)
        if beat.beat_id == plan.cta.primary_after_beat:
            break

    fraction = elapsed / total
    low, high = CTA_POSITION_BAND
    if low <= fraction <= high:
        band = "GREEN"
    elif (low - CTA_POSITION_AMBER_MARGIN) <= fraction <= (high + CTA_POSITION_AMBER_MARGIN):
        band = "AMBER"
    else:
        band = "RED"

    return DiagnosticResult(
        dimension="cta.position", band=band, value=round(fraction, 2), target=f"{low:.0%}-{high:.0%}",
        evidence=f"CTA lands after beat {plan.cta.primary_after_beat!r}, {fraction:.0%} through the story",
    )
