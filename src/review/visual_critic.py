"""C3 -- visual critic (flash-tier Gemini) (plan §13, V1C).

Judges rendered screenshots against their own scene's screen prose and
spoken narration -- does the screen actually show what the narration says,
at roughly the right visual weight? Never rewrites; only a genuinely
structural rendering problem (never a merely uninspired visual choice)
routes to H REPAIR, decided in Python from `severity`/`layer`/
`repair_owner` on the returned `CritiqueIssue`s, never a separate yes/no
question put to the model.

STORY_IMPROVEMENT_PLAN.md Phase 6 (BUG-4): also the ONLY place H's
screen prose gets any critique at all -- C1 runs inside the story loop,
which completes before H is ever called, so it never sees this text.
Folding a repetition/overclaim check in here (rather than a new pass) is
cheaper: C3 already runs post-H and already has an H-repair route. This
only covers the sampled scenes C3 already audits (`visual_sample.py`'s
flagged + ~20% sample, max 8 images), not every scene -- a real,
documented limitation, not full C1-equivalent coverage.
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
for these; severity `major` or `minor`.

Reserve `severity: critical` WITH `repair_owner: narration_lead` for a
stronger case than a merely suboptimal choice: the screen doesn't just
serve the scene poorly, it actively CONTRADICTS what the narration/prose
claims -- a different concrete example than the one described, a number
that flatly disagrees with what's stated, a mechanism shown working in a
way that contradicts the claim. No HTML repair can fix this (H only
regenerates screen prose/component data, never the underlying facts it's
asked to represent) -- it gets surfaced as a real, blocking finding
rather than routed to a repair, so use this combination only for a
genuine factual contradiction, never a style or quality judgment.

Reserve `severity: critical`, `layer: RENDERER`, `repair_owner: html_author`
ONLY for a genuinely structural rendering problem you can see directly in
the screenshot itself -- text visibly cut off, a component rendered
completely empty or broken, content overlapping illegibly. Never use this
combination for a merely uninspired-but-correct visual choice; it is what
routes a finding straight into an automatic HTML repair, so it must mean
an actual rendering break, not a style opinion.

Also check the on-screen prose text itself (independent of the image) for
two things spoken narration is checked for elsewhere in this pipeline, but
that this screen text never otherwise gets reviewed for:
- REPETITION: each scene carries `scene_function`, `must_not_repeat`, and
  `running_example`, set by the planner. If `scene_function=derivation`
  and the screen prose fully re-explains a concept listed in
  `must_not_repeat` (rather than referencing it in passing), or if the
  prose invents different named objects/values for the same underlying
  `running_example` instead of reusing its exact ones, raise it with
  `category: repetition`, `layer: NARRATION`, `repair_owner: html_author`
  (H writes this prose, not the narrator), severity `major` or `minor`,
  never `critical` -- this is a real defect, but not a rendering break.
- OVERCLAIM: hard-selection language for a soft/weighted mechanism, one
  component's contribution stated as if it single-handedly causes the
  whole outcome, or an architecture-specific detail stated as universal.
  Use `category: clarity`, `layer: NARRATION`, `repair_owner: html_author`,
  same severity rule as above.

Only raise an issue for a real problem -- a scene that already matches its
narration well needs nothing. `scene_ids` on every issue must name the
one scene it's about.
"""


class VisualCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def scene_payload(
    scene_id: str, image_index: int, screen_prose: str, narration_text: str,
    scene_function: str = "standard", must_not_repeat: list[str] | None = None,
    running_example: dict | None = None,
) -> dict:
    return {
        "scene_id": scene_id, "image_index": image_index,
        "screen_prose": screen_prose, "narration_text": narration_text,
        "scene_function": scene_function, "must_not_repeat": must_not_repeat or [],
        "running_example": running_example or {},
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
