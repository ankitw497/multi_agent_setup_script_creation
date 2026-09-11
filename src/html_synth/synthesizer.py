"""H -- HTML synthesis (Narration Lead / Sonnet, subscription lane) (plan §12).

The dual-audience contract (plan §12.0): the reader sees screen prose in an
on-screen voice, never the spoken narration; the renderer reads the
embedded narration JSON block. This module writes the SCREEN prose and
picks components -- it never touches or duplicates the narration text
that narration/generator.py already produced.

Per-beat calls, not one page-wide call -- the same ERR-010/ERR-024 lesson
applied here: asking one call to produce screen prose + component choices
for an entire 20-30-scene page in one shot risks the exact aggregate-
generation unreliability that broke A2's scene_plan. Each beat's own
prose is a small, independently-achievable task.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from planning.models import StoryBeat, StoryPlan

from .component_library import component_slots, components_for_story_role

TASK_PROMPT = """\
Write the ON-SCREEN article prose for this one beat -- NOT spoken
narration. This is a different text a reader sees on a webpage, in an
explanatory written voice (more like a technical article than a script):
denser, more concrete, can use terms the spoken narration simplifies away.
Never restate the narration text given for reference; write independent
prose that explains the same idea in writing.

For each scene in this beat:
- `screen_prose`: 1-3 sentences of article prose covering that scene's idea.
- `component_id`: OPTIONAL -- choose one component from `allowed_components`
  if (and only if) this scene's content genuinely benefits from one (a
  concrete comparison, a callout-worthy caveat, an equation, a labeled
  visual). Leave it null for scenes that are better served by prose alone
  -- do not force a component onto every scene.
- `component_data`: if `component_id` is set, fill in exactly the slots
  that component needs (see `component_slots` for the exact fields) with
  real content grounded in `available_claims` -- never invent a number or
  fact. For `diagram_card` specifically, `content` must be an actual
  compact ASCII-art diagram (arrows like -> or |, boxes, short labels)
  that concretely depicts this scene's mechanism step -- e.g. a labeled
  flow of a few short stages connected by arrows. Never leave it blank
  and never just restate the caption in prose form.
- `annotated_numbers`: every number in `screen_prose` (or in
  `component_data`, for a card/table) that comes from a specific claim --
  list `{text, claim_id}` pairs with `text` as the EXACT substring as it
  appears (so it can be found and annotated), and `claim_id` from
  `available_claims`. A number with no backing claim should not appear in
  the prose at all.

Also write this beat's own `heading` (a real `<h2>`, specific to what this
beat teaches, never generic like "Section 3") and a one-sentence
`subheading` framing what a reader is about to learn.
"""

HERO_TASK_PROMPT = """\
Write the page's hero section: `badge` (a short series/part label, e.g.
"Attention · Part 1 of 3"), `title` (the page's on-screen headline --
related to the hook's promise but written as an article headline, not
read aloud), and `subtitle` (1-2 sentences setting up the problem, in
written article voice). Never reuse the spoken hook narration verbatim.
"""


class NumberAnnotation(BaseModel):
    text: str
    claim_id: str


class SceneVisual(BaseModel):
    scene_id: str
    screen_prose: str = ""
    component_id: str | None = None
    component_data: dict = Field(default_factory=dict)
    annotated_numbers: list[NumberAnnotation] = Field(default_factory=list)


class BeatVisual(BaseModel):
    beat_id: str
    heading: str = ""
    subheading: str = ""
    scenes: list[SceneVisual] = Field(default_factory=list)


class HeroContent(BaseModel):
    badge: str = ""
    title: str = ""
    subtitle: str = ""


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "numbers": claim.numbers}


def synthesize_hero(plan: StoryPlan, narration_lead: Agent) -> HeroContent:
    payload = {
        "story_promise": plan.story_promise, "hook_promise": plan.hook.promise,
        "hook_tension": plan.hook.tension, "title_promise": plan.title.promise,
    }
    return narration_lead.run(
        pass_id="H", mode="HERO", task_prompt=HERO_TASK_PROMPT,
        payload=payload, schema=HeroContent, timeout_s=120,
    )


def synthesize_beat_visual(
    beat: StoryBeat, plan: StoryPlan, claims: list[Claim], narration_lead: Agent,
) -> BeatVisual:
    scenes = [s for s in plan.scene_plan if s.beat_id == beat.beat_id]
    beat_claims = [c for c in claims if c.source_unit in set(beat.source_unit_ids)]
    story_role = beat.archetype_role or "observations"
    allowed_components = components_for_story_role(story_role) or components_for_story_role("observations")

    payload = {
        "beat_purpose": beat.purpose, "forward_driver": beat.forward_driver,
        "learning_objective": beat.learning_objective,
        "scenes": [{"scene_id": s.scene_id, "visual_description": s.visual_description} for s in scenes],
        "allowed_components": allowed_components,
        "component_slots": {cid: component_slots(cid) for cid in allowed_components},
        "available_claims": [_claim_payload(c) for c in beat_claims],
    }
    result = narration_lead.run(
        pass_id="H", mode="BEAT_VISUAL", task_prompt=TASK_PROMPT,
        payload=payload, schema=BeatVisual, timeout_s=180,
    )
    return result
