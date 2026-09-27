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


def _expected_formula_stage_by_scene(plan: StoryPlan) -> dict[str, dict]:
    """scene_id -> {"stage_id", "expression", "values"} for every scene tagged with a
    `formula_stage_id`, using the SAME "most advanced stage reached so far" algorithm
    `verification/hard/formula_consistency.py::check_formula_stage_consistency` checks
    against after the fact -- computed here, deterministically, so H is actually TOLD what
    that check will require instead of being silently graded against it. Duplicated rather
    than imported (formula_consistency.py imports BeatVisual from this module; importing
    back would cycle) -- kept in lockstep by keeping both walks identical to this plan's
    own `scene_plan` order and `formula_stages` registration."""
    if not plan.formula_stages:
        return {}
    stage_index = {s.stage_id: i for i, s in enumerate(plan.formula_stages)}
    expected: dict[str, dict] = {}
    most_advanced_idx = -1
    for scene in plan.scene_plan:
        if not scene.formula_stage_id or scene.formula_stage_id not in stage_index:
            continue
        idx = stage_index[scene.formula_stage_id]
        most_advanced_idx = max(most_advanced_idx, idx)
        stage = plan.formula_stages[most_advanced_idx]
        expected[scene.scene_id] = {
            "stage_id": stage.stage_id, "expression": stage.expression, "values": stage.values,
        }
    return expected

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
  `beat_screen_text_word_budget` is this beat's own real share of the WHOLE
  page's word-count ceiling (summed across `screen_prose` and any
  `component_data` text, across every scene in this beat) -- a hard
  constraint, not a suggestion: coming in noticeably under it is fine, going
  over it is not. Divide it across this beat's own scenes by how much each
  one genuinely needs, not evenly -- a scene whose idea is fully carried by
  a diagram needs far less of it than one that has no component at all.
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
  caption in prose form. Three components exist for a specific narrative
  shape, not general decoration -- reach for them only when the content
  genuinely IS that shape: `suspect_board` (when `allowed_components`
  offers it) is a lineup of candidate causes for a sustained mystery/
  investigation beat -- `items` is `{name, note}` pairs naming each
  candidate and what it actually is, never the reveal itself (the reveal
  belongs in a later scene). `solution_grid` is for a payoff that resolves
  into SEVERAL concrete options side by side, not one -- `items` is
  `{name, body}` pairs, each a real, distinct option grounded in
  `available_claims`, never padding a single real option out to look like
  several. `case_card` is one labeled concrete scenario -- `title` names
  it, `body` states what actually happens in THIS instance, grounded in a
  real claim -- use it when the scene's job is "here's a specific case,"
  not a general rule (that's prose/`defbox`'s job instead). `metric_table`
  (where `allowed_components` offers it) is a real head-to-head comparison
  across several metrics -- `headers` is a flat list of column labels, and
  `rows` is a list where each row is ALSO a flat list of cell values, in
  the SAME order as `headers` (never a list of `{label: value}` objects,
  and never a bare value in place of a row).
  `diagram_card` is legal under nearly every role and is always a safe
  choice, which is exactly why it must not become the reflexive default:
  confirmed live across two real full pages, it was picked in roughly two
  out of every three components chosen, including scenes where a more
  specific component was legally available and a better fit (e.g. a
  `payoff` scene resolving into several concrete options never once used
  `solution_grid`). Before reaching for `diagram_card`, check whether this
  scene's content is actually a labeled case (`case_card`), several
  parallel options (`solution_grid`), or a lineup of candidates
  (`suspect_board`, where offered) -- pick the component that matches the
  content's real shape, not the one that's always legal.
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
- Each claim also carries `verification_status` and `importance`, and they
  gate whether it may appear in `screen_prose`/`component_data`/
  `annotated_numbers` AT ALL, the same as they gate spoken narration:
  REJECTED claims may never appear in any form; an UNVERIFIED claim with
  importance CORE or SUPPORTING must be omitted (ground the same point in a
  different VERIFIED or CONTEXT_DEPENDENT claim instead, or leave it out);
  an UNVERIFIED claim with importance OPTIONAL may appear only with an
  explicit hedge ("approximately," "roughly," "in this example," or
  similar) in the prose around it -- never state it as settled fact. Just
  because `narration_text` mentions something does not make it safe to
  illustrate independently; check the claim's own status before grounding
  a number or fact in it.

Also write this beat's own `heading` (a real `<h2>`, specific to what this
beat teaches, never generic like "Section 3") and a one-sentence
`subheading` framing what a reader is about to learn.

If `archetype` is `mystery` or `build`, `heading` should read as the next
beat of an unfolding investigation, using this beat's own
`viewer_question_before`/`answer_or_payoff`/`next_question` -- a narrative
beat continuing the hook's own tension, not a topic label, even when the
topic label would be accurate. Confirmed live (STORY_IMPROVEMENT_PLAN.md
Phase 31 item 2): headings that stay accurate but description-toned
("Query, Key, Value: Splitting One Job Into Three") are correct but read
as a syllabus; a real comparison series that kept headings in the
video's own investigative voice throughout ("It must be a memory leak.",
"Six tenants. One of them is a mystery guest.", "Same error. Four
different culprits.") sustained the hook's momentum into every section
instead of spending it all in the first 10 seconds. For every OTHER
archetype (`foundation`, `framework`, `experiment`, `derivation`), a
descriptive heading is the honest, correct choice -- do not force a
mystery tone onto content that isn't genuinely investigative.

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

If a scene carries a non-null `required_formula_stage` ({stage_id, expression,
values}), this video's own expression evolves stage by stage across beats, and
this scene is at or past the given stage -- your rendered content for that
scene (`screen_prose` and/or `component_data`, whichever actually carries the
expression) MUST include `expression` and every one of `values` VERBATIM
(exact characters, whitespace doesn't matter). This is true even when the
scene's own narration only shows an earlier, simpler form -- the registered
stage is the video's own source of truth for what has been DERIVED so far,
not a summary of what this one scene's narration happened to say. Never
silently reuse an earlier stage's now-superseded expression or numbers once a
later stage has been registered, and never omit the expression just because
it was already shown in an earlier beat -- each scene tagged this way must
carry it again, in its own right.
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


# Mirrors verification/hard/render.py::READER_STANDALONE_WORD_BAND = (2000, 3200) -- not
# imported (that module imports FROM this one; importing back would cycle). 2600 is the
# band's own midpoint, giving H real headroom on both sides rather than aiming at the
# ceiling. 2026-09-24: confirmed live H had NO numeric awareness of this band at all --
# a denser, more complete narration (Opus 5.5 story_lead, 2249 spoken words vs. a thinner
# comparison run's 1402) pushed the RENDERED page to 3377 words, over the 3200 cap, even
# though each scene's own screen_prose stayed reasonably close to "minimum needed." A
# stateless per-beat call can't self-regulate against a whole-page total it never sees --
# same reasoning as beat_word_budget.py's own deterministic (not LLM-summed) allocation.
_SCREEN_TEXT_TARGET_WORDS = 2600


def _screen_text_word_budget_by_beat(plan: StoryPlan) -> dict[str, int]:
    """beat_id -> target screen-text word count, proportional to each beat's own scene
    count (a beat with more scenes legitimately needs more on-screen text) -- same
    proportional-allocation shape as planning/beat_word_budget.py, applied to H's render
    text instead of B1's spoken narration. The last beat absorbs the rounding remainder."""
    beat_ids = [b.beat_id for b in plan.beats]
    if not beat_ids:
        return {}
    scene_counts = {bid: sum(1 for s in plan.scene_plan if s.beat_id == bid) for bid in beat_ids}
    total_scenes = sum(max(1, c) for c in scene_counts.values())
    allocations: dict[str, int] = {}
    allocated_so_far = 0
    for i, bid in enumerate(beat_ids):
        if i == len(beat_ids) - 1:
            words = _SCREEN_TEXT_TARGET_WORDS - allocated_so_far
        else:
            words = round(_SCREEN_TEXT_TARGET_WORDS * max(1, scene_counts[bid]) / total_scenes)
        # allocated_so_far tracks the CLAMPED value, not the pre-clamp `words` (real bug
        # found live, 2026-09-27): whenever a beat's proportional share rounds below the
        # 20-word floor, its shortfall was never charged against the running total, so the
        # last beat's "absorb the remainder" share silently let the SUM exceed
        # _SCREEN_TEXT_TARGET_WORDS -- precisely undermining the guardrail this function
        # exists to provide (bounding H's total screen text, added because a real run
        # overflowed render.py's verified word ceiling).
        allocation = max(words, 20)
        allocations[bid] = allocation
        allocated_so_far += allocation
    return allocations


def _claim_payload(claim: Claim) -> dict:
    # verification_status/importance added (2026-09-26, Phase 32 P0): H had no
    # gating data at all for annotated_numbers/component_data, unlike every
    # narration-writing pass -- nothing stopped it independently annotating a
    # number from a REJECTED or gate-failing claim that never made it into the
    # spoken narration it's meant to be illustrating.
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "numbers": claim.numbers,
        "scope": claim.scope, "required_qualifiers": claim.required_qualifiers,
        "verification_status": claim.verification_status, "importance": claim.importance,
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
    expected_formula_stage_by_scene = _expected_formula_stage_by_scene(plan)

    payload = {
        "beat_purpose": beat.purpose, "forward_driver": beat.forward_driver,
        "learning_objective": beat.learning_objective,
        # archetype + these 3 fields (2026-09-26, Phase 31 item 2): previously never sent
        # to H at all -- needed so a mystery/build-archetype heading can read as the next
        # beat of an unfolding investigation instead of a topic label.
        "archetype": plan.archetype, "viewer_question_before": beat.viewer_question_before,
        "answer_or_payoff": beat.answer_or_payoff, "next_question": beat.next_question,
        "scenes": [
            {
                "scene_id": s.scene_id, "visual_description": s.visual_description,
                "narration_text": narration_text_by_scene.get(s.scene_id, ""),
                # 2026-09-24: previously never sent -- H had no way to know
                # verification/hard/formula_consistency.py would require this scene's
                # rendered content to contain a specific earlier-registered stage's exact
                # expression/values verbatim. None for a scene with no formula_stage_id.
                "required_formula_stage": expected_formula_stage_by_scene.get(s.scene_id),
            }
            for s in scenes
        ],
        "allowed_components": allowed_components,
        "component_slots": {cid: component_slots(cid) for cid in allowed_components},
        "available_claims": [_claim_payload(c) for c in beat_claims],
        "running_example": plan.running_example.model_dump(),
        # 2026-09-24: this beat's own share of the whole page's word-count band
        # (verification/hard/render.py::READER_STANDALONE_WORD_BAND) -- a stateless
        # per-beat call has no visibility into what earlier/later beats will spend, so it
        # needs its own explicit target, not a vague "keep it short" reminder.
        "beat_screen_text_word_budget": _screen_text_word_budget_by_beat(plan).get(beat.beat_id),
    }
    result = html_author.run(
        pass_id="H", mode="BEAT_VISUAL", task_prompt=TASK_PROMPT,
        payload=payload, schema=BeatVisual, timeout_s=180,
    )
    # beat_id forced from the input, never trusted from the model's own response
    # (2026-09-27, real crash): the payload above never even SENDS beat.beat_id, yet the
    # BeatVisual schema requires the model to invent one from context -- confirmed live,
    # a real plan's beat "B1_hook" came back from H with a different self-chosen beat_id,
    # and `html_pipeline.py::apply_repairs`'s `beat_visual_by_id[b.beat_id] for b in
    # plan.beats` (keyed off the model's own field) raised KeyError. This had silently
    # worked by luck on every run that never needed a repair pass.
    return result.model_copy(update={"beat_id": beat.beat_id})
