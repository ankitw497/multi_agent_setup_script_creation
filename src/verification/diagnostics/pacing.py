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

from planning.models import StoryPlan
from review.models import DiagnosticResult

PLANNING_WPM = 167
HOOK_TENSION_TARGET_SECONDS = 30.0  # plan §10.2: "tension reached inside ~30 s"
HOOK_TENSION_AMBER_MARGIN_SECONDS = 30.0  # up to ~60s still counts as AMBER, not RED


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
