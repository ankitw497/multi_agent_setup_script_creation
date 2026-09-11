"""Formula-stage consistency (STORY_IMPROVEMENT_PLAN.md Phase 6, item 7).

Deterministic, Python-only pattern matching against a video's own
registered `StoryPlan.formula_stages` -- catches a later scene's
equation/diagram content silently regressing to an earlier, already-
superseded form. Confirmed live: a `gpt-5.6-sol` run's B8 equation card
read `softmax(QK^T)_row`, dropping the `/sqrt(d_k)` term B7's narration
had already derived one beat earlier -- C1 (a model critic) did not catch
it. This is exactly the class of defect a per-run critic cannot be
trusted to reliably catch run after run; the fix is a Python check
against the plan's own registered stages, not another model call.

Most videos have no `formula_stages` at all (empty list is normal) --
this check is then a no-op, never a false positive against sources with
no evolving expression.
"""
from __future__ import annotations

import re

from html_synth.synthesizer import BeatVisual
from planning.models import StoryPlan

from .render import RenderIssue

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub("", text)


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _flatten_strings(v)]
    return []


def _scene_content_by_id(beat_visuals: list[BeatVisual]) -> dict[str, str]:
    return {
        scene.scene_id: " ".join([scene.screen_prose, *_flatten_strings(scene.component_data)])
        for bv in beat_visuals for scene in bv.scenes
    }


def check_formula_stage_consistency(plan: StoryPlan, beat_visuals: list[BeatVisual]) -> list[RenderIssue]:
    """Walks `plan.scene_plan` in order. For each scene tagged with a
    `formula_stage_id`, the expected form is the MOST ADVANCED registered
    stage reached so far (this scene's own stage, or a later one an
    earlier scene already reached) -- once introduced, a stage's exact
    `expression` must keep appearing verbatim (whitespace-insensitive) in
    every later tagged scene's own rendered content, never drop back to
    an earlier stage's simpler form."""
    if not plan.formula_stages:
        return []
    stage_index = {s.stage_id: i for i, s in enumerate(plan.formula_stages)}
    content_by_scene = _scene_content_by_id(beat_visuals)
    issues: list[RenderIssue] = []
    most_advanced_idx = -1
    for scene in plan.scene_plan:
        if not scene.formula_stage_id or scene.formula_stage_id not in stage_index:
            continue
        idx = stage_index[scene.formula_stage_id]
        expected_idx = max(most_advanced_idx, idx)
        expected_stage = plan.formula_stages[expected_idx]
        content = content_by_scene.get(scene.scene_id, "")
        normalized_content = _normalize(content)
        if _normalize(expected_stage.expression) not in normalized_content:
            issues.append(RenderIssue(
                "formula_stage_regression",
                f"scene {scene.scene_id} should retain stage {expected_stage.stage_id!r}'s "
                f"registered form ({expected_stage.expression!r}) but its rendered content "
                "does not contain it",
                scene_id=scene.scene_id,
            ))
        missing_values = {
            name: value for name, value in expected_stage.values.items()
            if _normalize(value) not in normalized_content
        }
        if missing_values:
            issues.append(RenderIssue(
                "formula_stage_values_missing",
                f"scene {scene.scene_id} should show stage {expected_stage.stage_id!r}'s "
                f"own worked numbers {missing_values} but its rendered content does not "
                "contain them (a later stage must not silently reuse an earlier stage's "
                "unchanged numbers)",
                scene_id=scene.scene_id,
            ))
        most_advanced_idx = expected_idx
    return issues
