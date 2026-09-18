"""Consecutive visual-component repetition (PIPELINE_AUDIT_2026-09-17.md, visual monotony).

An external review of a real generated video found its closing beat rendering 8
near-consecutive card-style scenes -- "a run of card/card/card/card is monotonous," in the
exact words `review/visual_sequence_critic.py`'s own C3 audit prompt already uses. That
critique is real, but it's LLM-judgment only, sampled to whichever scenes have a screenshot
(a bounded C3 subset, not necessarily the whole video), and by its own module docstring never
routed into the repair loop -- reported for visibility, nothing more.

`planning/models.py::ScenePlan.components` (the plan-level field that would let this be
caught before synthesis) is confirmed dead -- A2b never populates it. The actual component
choice happens per-BEAT in `html_synth/synthesizer.py::synthesize_beat_visual()`, with no
cross-beat visibility into what a neighboring beat chose. Fixing generation itself (giving H
visibility across beats) is a bigger change than this pass scopes to.

This is the cheap, deterministic, always-available alternative: `beat_visuals` (built for
EVERY scene, not just a sampled subset, and needing no screenshot/playwright availability)
already gives the exact component_id sequence, in true video order. A plain Python scan for
the longest run of consecutive identical, non-empty component_ids costs nothing and needs no
LLM call -- advisory only (AMBER at most, matches this project's own "a layout-rhythm
judgement call, never a hard gate" precedent for the LLM-based sequence critique above), since
"how many is too many" is a real judgment call, not a fact.
"""
from __future__ import annotations

from html_synth.synthesizer import BeatVisual
from review.models import DiagnosticResult

# The real reported case was 8 near-consecutive; a run of 4+ is the threshold chosen here --
# generous enough that a genuinely repeated structural device (e.g. 2-3 comparison cards in a
# row) isn't flagged, but a real run long enough for a viewer to actually notice is.
CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD = 4


def check_consecutive_component_repetition(beat_visuals: list[BeatVisual]) -> DiagnosticResult:
    sequence = [
        (s.scene_id, s.component_id) for bv in beat_visuals for s in bv.scenes if s.component_id
    ]

    worst_run = 0
    worst_component: str | None = None
    worst_start: str | None = None
    run_len = 0
    run_component: str | None = None
    run_start: str | None = None

    for scene_id, component_id in sequence:
        if component_id == run_component:
            run_len += 1
        else:
            run_component, run_len, run_start = component_id, 1, scene_id
        if run_len > worst_run:
            worst_run, worst_component, worst_start = run_len, run_component, run_start

    band = "AMBER" if worst_run >= CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD else "GREEN"
    return DiagnosticResult(
        dimension="render.consecutive_component_repetition", band=band, value=worst_run,
        target=f"< {CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD} consecutive scenes sharing a component",
        evidence=(
            f"{worst_run} consecutive scenes (starting at {worst_start!r}) all use the "
            f"{worst_component!r} component -- a real viewer is likely to notice the repetition"
            if band == "AMBER" else
            f"no run of {CONSECUTIVE_COMPONENT_REPETITION_THRESHOLD}+ consecutive scenes shares "
            "the same component"
        ),
    )
