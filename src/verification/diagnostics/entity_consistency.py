"""Cross-artifact entity consistency (STORY_IMPROVEMENT_PLAN.md Phase 6,
item #20 from `General Multi-Agent Video Script Pipeline Improvement
Feedback.md`: "narration entities vs. HTML entities vs. diagram
entities... a render should fail validation if these diverge materially").

Confirmed live: a visual audit found `score_s02`/`score_s03` inventing an
entirely different concrete example (`q(it) . k(dog)`, `k(park)`,
`k(bone)`) than the plan's own locked `running_example` ("the cat
couldn't climb the stairs because it was too tired") -- isolated to two
adjacent scenes, not pervasive, and invisible to every hard check at the
time (only the known word-count band issue showed up).

Entity extraction from arbitrary technical prose is not reliable by
regex alone -- this is deliberately a diagnostic signal (AMBER-banded at
most, never RED, never a hard gate that blocks promotion on its own),
pairing with a C1-style judgment check for the cases this heuristic can't
resolve confidently. The heuristic itself piggybacks on a real, observed
convention in this project's own content: a scene illustrating a concrete
example consistently names its entities in quotes ('cat', 'stairs', 'it')
-- so a quoted entity that matches neither the locked running_example nor
anything in the beat's own claims is a real, if imperfect, signal of
invented content.
"""
from __future__ import annotations

import re

from facts.models import Claim
from html_synth.synthesizer import BeatVisual
from planning.models import StoryPlan
from review.models import DiagnosticResult

_QUOTED_ENTITY_RE = re.compile(r"['‘’]([A-Za-z][A-Za-z0-9_-]{1,20})['‘’]")


def _quoted_entities(text: str) -> set[str]:
    return {m.lower() for m in _QUOTED_ENTITY_RE.findall(text)}


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _flatten_strings(v)]
    return []


def _scene_content(scene) -> str:
    return " ".join([scene.screen_prose, *_flatten_strings(scene.component_data)])


def check_running_example_entity_consistency(
    plan: StoryPlan, beat_visuals: list[BeatVisual], claims: list[Claim],
) -> DiagnosticResult:
    if not plan.running_example.values:
        return DiagnosticResult(
            dimension="cross_artifact.running_example_entities", band="GREEN",
            evidence="no running_example set for this video -- nothing to check",
        )

    locked_entities = {k.lower() for k in plan.running_example.values}
    locked_entities |= {w.lower() for w in re.split(r"[/,\s]+", plan.running_example.label) if w}

    beat_id_by_scene_id = {s.scene_id: s.beat_id for s in plan.scene_plan}
    claims_by_beat_id: dict[str, set[str]] = {}
    for beat in plan.beats:
        unit_ids = set(beat.source_unit_ids)
        beat_claim_text = " ".join(c.claim for c in claims if c.source_unit in unit_ids)
        claims_by_beat_id[beat.beat_id] = _quoted_entities(beat_claim_text)

    mismatches: list[str] = []
    for bv in beat_visuals:
        allowed = locked_entities | claims_by_beat_id.get(bv.beat_id, set())
        for scene in bv.scenes:
            quoted = _quoted_entities(_scene_content(scene))
            invented = quoted - allowed
            if invented:
                mismatches.append(f"{scene.scene_id}: {sorted(invented)}")

    if not mismatches:
        return DiagnosticResult(
            dimension="cross_artifact.running_example_entities", band="GREEN",
            evidence=f"every quoted entity in H's screen content matches the locked "
                     f"running_example ({sorted(locked_entities)}) or a beat's own claims",
        )

    return DiagnosticResult(
        dimension="cross_artifact.running_example_entities", band="AMBER",
        evidence=f"scene(s) quote entities matching neither the locked running_example "
                 f"({sorted(locked_entities)}) nor the beat's own claims -- candidate invented "
                 f"example, needs a human/C1-style look: {'; '.join(mismatches)}",
    )
