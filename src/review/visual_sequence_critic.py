"""C3-sequence -- compositional monotony across a run of scenes (flash-tier Gemini)
(STORY_IMPROVEMENT_PLAN.md Phase 15).

`review/visual_critic.py`'s C3 judges one screenshot against its own scene's prose and
narration -- it has no way to notice that 10 individually-fine scenes in a row all use the
same card/grid layout, which is boring even though no single scene is wrong. This pass looks
at a CONTACT SHEET of consecutive scenes together and judges the sequence as a whole, never a
rendering break or a factual problem (those stay C3's job) -- purely a compositional judgement,
so it never becomes a hard gate: `severity` here is `major`/`minor` only, and the caller
(`orchestration/html_pipeline.py`) never routes it into the repair loop, only reports it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter

from .models import CritiqueIssue

TASK_PROMPT = """\
You are reviewing a CONTACT SHEET of consecutive scenes from a technical
YouTube explainer, in video order. `scenes` lists one entry per
screenshot -- `scene_id`, `image_index` (0-based, matching the attached
images in the same order), and `component_id` (the visual component
chosen for that scene, or null for prose-only). Judge the SEQUENCE, not
any one scene on its own:

- Is the same component_id (or the same visual layout/rhythm) repeating
  across most or all of these scenes, when the underlying content
  actually varies? A run of card/card/card/card is monotonous even if
  each card individually is fine.
- Are visually important moments (a payoff, a key mechanism) actually
  larger or more visually prominent than routine ones, or does everything
  carry the same visual weight regardless of importance?
- Is the visual state actually changing meaningfully from scene to scene,
  or does the sequence feel static, like the same screen redrawn with
  different words?

Only raise an issue when there's a REAL pattern across SEVERAL of these
scenes, never a single scene's own choice -- name every scene_id in the
run the pattern actually spans. Use `category: visual_mismatch`,
`layer: VISUAL`, `repair_owner: html_author`, severity `major` or `minor`
only -- never `critical`. This is a compositional judgement call about
variety and pacing, never a rendering break or a factual contradiction
(those are C3's own per-scene job, not this pass's).

If composition across this sequence is varied and purposeful, return no
issues.
"""


class VisualSequenceCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def sequence_scene_payload(scene_id: str, image_index: int, component_id: str | None) -> dict:
    return {"scene_id": scene_id, "image_index": image_index, "component_id": component_id}


def critique_visual_sequence(
    scene_payloads: list[dict], images_b64: list[str], visual_auditor: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    """`images_b64` must be in the same order `scene_payloads`' `image_index` values
    reference -- same convention as `review/visual_critic.py::critique_visuals`."""
    critique = visual_auditor.run(
        pass_id="C3seq", mode="VISUAL_SEQUENCE_AUDITOR", task_prompt=TASK_PROMPT,
        payload={"scenes": scene_payloads}, schema=VisualSequenceCritique,
        budget=budget, estimated_usd=0.02, timeout_s=180, images=images_b64,
    )
    return critique.issues
