"""H -- HTML synthesis (HTML Author / Sonnet, subscription lane) (plan §12).

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
from narration.models import SceneNarration
from planning.models import StoryBeat, StoryPlan

from .component_library import component_slots, components_for_story_role

TASK_PROMPT = """\
Design the ON-SCREEN content for this one beat -- NOT spoken narration.
This is visual-first: a viewer's eye should land on one dominant teaching
object per scene (a diagram, a worked comparison, an equation, an
annotated number), with only the minimum text needed to support it --
never a paragraph doing the work a component could do instead. Never
restate the narration text given for reference; where you do write text,
make it independent, denser and more concrete than the spoken narration,
not a copy of it.

For each scene in this beat:
- `screen_prose`: the minimum real text needed to support this scene's
  dominant visual object -- often a single, substantive sentence, up to 3
  only when the idea genuinely can't be carried by the component alone.
  Never blank: a component or diagram is never a substitute for real
  screen text (this page requires visible prose on every scene), but
  "minimum needed" means exactly that -- do not pad a one-sentence idea
  into three just to fill space. More text is not more thorough; it's the
  reader having to read what the visual should already be showing.
- `component_id`: OPTIONAL -- choose one component from `allowed_components`
  if (and only if) this scene's content genuinely benefits from one (a
  concrete comparison, a callout-worthy caveat, an equation, a labeled
  visual). Leave it null for scenes that are better served by prose alone
  -- do not force a component onto every scene.
- `component_data`: once you've chosen a component, fill in EVERY slot
  listed for it in `component_slots` -- a slot left blank renders a
  visibly broken empty box on the page. This means filling every slot in
  completely, not avoiding components -- a scene whose content genuinely
  calls for an equation or a mechanism diagram should still use
  `math_block`/`diagram_card`, just with every slot properly filled. Use
  real content grounded in `available_claims` -- never invent a number or
  fact. For `diagram_card`
  specifically, `content` must be an actual compact ASCII-art diagram
  (arrows like -> or |, boxes, short labels) that concretely depicts this
  scene's mechanism step -- e.g. a labeled flow of a few short stages
  connected by arrows. Never leave it blank and never just restate the
  caption in prose form.
- Any mathematical or algorithmic expression, in `screen_prose` OR
  `component_data`, must use plain, readable notation only -- e.g. "a /
  sqrt(b)" or "f(x)" -- never LaTeX escape syntax (`\\frac{}{}`,
  `\\sqrt{}`, `\\operatorname{}`, `\\left`/`\\right`, `\\cdot`, `\\top`, and
  similar backslash commands), even if a given field like
  `visual_description` already contains LaTeX -- convert it to plain
  notation rather than copying it through. This page renders no LaTeX
  engine -- raw LaTeX source shows up as literal broken text on screen.
- `annotated_numbers`: every number in `screen_prose` (or in
  `component_data`, for a card/table) that comes from a specific claim --
  list `{text, claim_id}` pairs with `text` as the EXACT substring as it
  appears (so it can be found and annotated), and `claim_id` from
  `available_claims`. A number with no backing claim should not appear in
  the prose at all.
- Each claim in `available_claims` may carry `required_qualifiers` --
  conditions its truth actually depends on (e.g. "only for unmasked/
  bidirectional attention, not causal") -- and `scope`
  (UNIVERSAL/MODEL_SPECIFIC/EXAMPLE_SPECIFIC/IMPLEMENTATION_DEPENDENT). If
  your screen prose states something grounded in such a claim, preserve
  its qualifier/scope -- do not describe a conditional mechanism as if it
  applied universally just because the spoken narration you're
  illustrating happened to state it that way; this page's own prose is
  independent and must get it right even where the narration didn't.

Also write this beat's own `heading` (a real `<h2>`, specific to what this
beat teaches, never generic like "Section 3") and a one-sentence
`subheading` framing what a reader is about to learn.

Each scene is also given `narration_text` -- the actual spoken narration
already written for it. Illustrate what was ACTUALLY narrated, not just
the earlier `visual_description` (written before narration existed, and
may have drifted from what the scene ended up saying). If `running_example`
is set (non-empty `label`), and this scene's content is the same running
illustration, reuse its exact named objects/values verbatim in
`screen_prose` and any component -- never invent a different example, a
different number, or a different named entity for the same underlying
idea. This is the one running illustration the whole video (narration
included) is built around.
"""

HERO_TASK_PROMPT = """\
Write the page's hero section: `badge` (a short series/part label, e.g.
"Attention · Part 1 of 3"), `title` (the page's on-screen headline --
related to the hook's promise but written as an article headline, not
read aloud), and `subtitle` (1-2 sentences setting up the problem, in
written article voice). Never reuse the spoken hook narration verbatim.
If `running_example` is set (non-empty `label`) and the subtitle touches
it, reuse its exact named objects/values -- never invent a different one
for the same underlying idea.
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
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "numbers": claim.numbers,
        "scope": claim.scope, "required_qualifiers": claim.required_qualifiers,
    }


def synthesize_hero(plan: StoryPlan, html_author: Agent) -> HeroContent:
    payload = {
        "story_promise": plan.story_promise, "hook_promise": plan.hook.promise,
        "hook_tension": plan.hook.tension, "title_promise": plan.title.promise,
        "running_example": plan.running_example.model_dump(),
    }
    return html_author.run(
        pass_id="H", mode="HERO", task_prompt=HERO_TASK_PROMPT,
        payload=payload, schema=HeroContent, timeout_s=120,
    )


def synthesize_beat_visual(
    beat: StoryBeat, plan: StoryPlan, claims: list[Claim], html_author: Agent,
    narration: list[SceneNarration] = (),
) -> BeatVisual:
    scenes = [s for s in plan.scene_plan if s.beat_id == beat.beat_id]
    beat_claims = [c for c in claims if c.source_unit in set(beat.source_unit_ids)]
    story_role = beat.archetype_role or "observations"
    allowed_components = components_for_story_role(story_role) or components_for_story_role("observations")
    narration_text_by_scene = {n.scene_id: " ".join(s.text for s in n.sentences) for n in narration}

    payload = {
        "beat_purpose": beat.purpose, "forward_driver": beat.forward_driver,
        "learning_objective": beat.learning_objective,
        "scenes": [
            {
                "scene_id": s.scene_id, "visual_description": s.visual_description,
                "narration_text": narration_text_by_scene.get(s.scene_id, ""),
            }
            for s in scenes
        ],
        "allowed_components": allowed_components,
        "component_slots": {cid: component_slots(cid) for cid in allowed_components},
        "available_claims": [_claim_payload(c) for c in beat_claims],
        "running_example": plan.running_example.model_dump(),
    }
    result = html_author.run(
        pass_id="H", mode="BEAT_VISUAL", task_prompt=TASK_PROMPT,
        payload=payload, schema=BeatVisual, timeout_s=180,
    )
    return result
