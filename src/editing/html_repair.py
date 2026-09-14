"""H REPAIR (Narration Lead / Sonnet, subscription lane) (plan §13, §15, V1C).

Fixes structural render failures by regenerating ONLY the affected beat's
screen prose/component choices -- reuses H's own `BeatVisual`/`HeroContent`
schemas, never `GeneratedNarration`, so the spoken narration text (and its
DOM hash) is structurally untouched by any repair. Never a paid model and
never routed through B2/A3 (plan §15's routing table: "HTML structural /
render -> H REPAIR -- never B2, never a paid model") -- and never
model-chosen scope: `beats_to_repair()` decides WHICH beats need another
look from concrete `RenderIssue`/`CritiqueIssue` scene ids, resolved
against `plan.scene_plan` in plain Python, the same "arithmetic is
deterministic, not model-voted" principle this codebase already applies
to fact-set scoping and word budgets.
"""
from __future__ import annotations

from agents.base import Agent
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, HeroContent
from html_synth.component_library import component_slots, components_for_story_role
from narration.models import SceneNarration
from planning.models import StoryBeat, StoryPlan
from verification.hard.render import RenderIssue

REPAIR_TASK_PROMPT = """\
This beat's rendered output failed one or more real checks, listed in
`render_failures` below (each names a `scene_id`, a failure `code`, and a
concrete `detail`). Regenerate ONLY this beat's screen prose and component
choices to resolve those specific failures -- do not otherwise change
content for scenes not named in `render_failures`.

For each scene in this beat:
- `screen_prose`: 1-3 sentences of on-screen article prose, NOT spoken
  narration. If this scene's failure was clipping/overflow, shorten the
  prose or simplify the component data enough to fit; if it was
  invisible-required-content, make sure real prose is present at all; if
  it was low contrast, that is a design-token issue this pass cannot fix
  by changing content -- leave the prose as the best version you can write
  and let the failure surface honestly rather than silently dropping content.
- `component_id`/`component_data`: same rules as a first H pass -- choose
  from `allowed_components`, fill exactly the slots in `component_slots`,
  ground every number in `available_claims`, never invent a fact. For
  `diagram_card`, `content` must be a real compact ASCII-art diagram, never
  blank.
- `annotated_numbers`: as in a first pass -- exact substrings backed by a
  real claim.

Also write this beat's own `heading` and `subheading`, matching a first
H pass's own rules (a real, specific `<h2>`, never generic).

Each scene is also given `narration_text` (the actual spoken narration
already written for it) and `running_example` -- reuse the same rules as
a first H pass: illustrate what was actually narrated, and if this
scene's content is the same running illustration, reuse its exact named
objects/values verbatim rather than inventing a different one.
"""

HERO_REPAIR_TASK_PROMPT = """\
The page's hero section failed one or more real rendered checks, listed in
`render_failures` below. Regenerate `badge`/`title`/`subtitle` to resolve
those specific failures (typically clipping or invisible content from an
overlong title/subtitle) -- same rules as a first hero pass: related to
the hook's promise, written as an article headline, never the spoken hook
narration verbatim. If `running_example` is set and the subtitle touches
it, reuse its exact named objects/values.
"""


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "numbers": claim.numbers}


def _render_failure_payload(issue: RenderIssue) -> dict:
    return {"scene_id": issue.scene_id, "code": issue.code, "detail": issue.detail}


def beats_to_repair(plan: StoryPlan, flagged_scene_ids: set[str]) -> dict[str, list[str]]:
    """beat_id -> the flagged scene ids inside it, per `plan.scene_plan`.

    A flagged scene id that names no known scene (a `"hero"` sentinel, or a
    page-wide issue never tied to one scene) is deliberately set aside, not
    silently dropped -- there is no beat to regenerate for it, so it stays
    a real hard failure until the repair budget is exhausted. A systemic
    design-token bug (e.g. a real contrast failure baked into the CSS)
    should surface as FAIL loudly; a content-repair loop that can't
    actually fix it must not be able to mask that by looping forever.
    """
    beat_by_scene_id = {s.scene_id: s.beat_id for s in plan.scene_plan}
    result: dict[str, list[str]] = {}
    for scene_id in flagged_scene_ids:
        beat_id = beat_by_scene_id.get(scene_id)
        if beat_id is None:
            continue
        result.setdefault(beat_id, []).append(scene_id)
    return result


def repair_beat_visual(
    beat: StoryBeat, plan: StoryPlan, claims: list[Claim], narration_lead: Agent,
    render_failures: list[RenderIssue], narration: list[SceneNarration] = (),
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
        "render_failures": [_render_failure_payload(i) for i in render_failures],
        "running_example": plan.running_example.model_dump(),
    }
    return narration_lead.run(
        pass_id="H", mode="BEAT_VISUAL_REPAIR", task_prompt=REPAIR_TASK_PROMPT,
        payload=payload, schema=BeatVisual, timeout_s=180,
    )


def repair_hero(plan: StoryPlan, narration_lead: Agent, render_failures: list[RenderIssue]) -> HeroContent:
    payload = {
        "story_promise": plan.story_promise, "hook_promise": plan.hook.promise,
        "hook_tension": plan.hook.tension, "title_promise": plan.title.promise,
        "render_failures": [_render_failure_payload(i) for i in render_failures],
        "running_example": plan.running_example.model_dump(),
    }
    return narration_lead.run(
        pass_id="H", mode="HERO_REPAIR", task_prompt=HERO_REPAIR_TASK_PROMPT,
        payload=payload, schema=HeroContent, timeout_s=120,
    )
