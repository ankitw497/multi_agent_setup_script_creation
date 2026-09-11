"""C3 -- visual critic (flash-tier Gemini) (plan §13, V1C).

Judges rendered screenshots against their own scene's screen prose and
spoken narration -- does the screen actually show what the narration says,
at roughly the right visual weight? Never rewrites; only a genuinely
structural rendering problem (never a merely uninspired visual choice)
routes to H REPAIR, decided in Python from `severity`/`layer`/
`repair_owner` on the returned `CritiqueIssue`s, never a separate yes/no
question put to the model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter

from .models import CritiqueIssue

TASK_PROMPT = """\
You are reviewing screenshots of a technical YouTube explainer's rendered
scenes. `scenes` lists one entry per screenshot, in the SAME order the
images were attached -- each entry's `image_index` (0-based) tells you
which attached image shows that scene; match them by that index, not by
position in the text alone.

For each scene, you have its on-screen prose and its spoken narration
text alongside the image. Judge: does the screen actually show what the
narration and on-screen prose describe, at roughly the right visual
weight (a scene about one number shouldn't be dominated by an unrelated
diagram; a scene about a mechanism should show the mechanism, not just an
unrelated stat card)?

Most findings here are ordinary content critique -- a visual choice that
is technically fine but doesn't serve the scene as well as it could. Use
`category: visual_mismatch`, `layer: VISUAL`, `repair_owner: narration_lead`
for these; severity `major` or `minor`, never `critical`.

Reserve `severity: critical`, `layer: RENDERER`, `repair_owner: html_author`
ONLY for a genuinely structural rendering problem you can see directly in
the screenshot itself -- text visibly cut off, a component rendered
completely empty or broken, content overlapping illegibly. Never use this
combination for a merely uninspired-but-correct visual choice; it is what
routes a finding straight into an automatic HTML repair, so it must mean
an actual rendering break, not a style opinion.

Only raise an issue for a real problem -- a scene that already matches its
narration well needs nothing. `scene_ids` on every issue must name the
one scene it's about.
"""


class VisualCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def scene_payload(scene_id: str, image_index: int, screen_prose: str, narration_text: str) -> dict:
    return {
        "scene_id": scene_id, "image_index": image_index,
        "screen_prose": screen_prose, "narration_text": narration_text,
    }


def critique_visuals(
    scene_payloads: list[dict], images_b64: list[str], visual_auditor: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    """`images_b64` must be in the same order `scene_payloads`' `image_index`
    values reference -- the caller (the H-repair loop) owns building both
    from the same scene selection, this function only sends what it's given."""
    critique = visual_auditor.run(
        pass_id="C3", mode="VISUAL_AUDITOR", task_prompt=TASK_PROMPT,
        payload={"scenes": scene_payloads}, schema=VisualCritique,
        budget=budget, estimated_usd=0.02, timeout_s=180, images=images_b64,
    )
    return critique.issues
