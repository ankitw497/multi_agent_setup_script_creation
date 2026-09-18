"""A2b -- per-beat scene expansion (Story Lead) (plan §5, §9).

The other half of the ERR-010/ERR-023 fix: `beat_word_budget.py` computes
each beat's own word target deterministically; this pass asks one small,
well-scoped call per beat to hit ITS OWN target -- a few hundred words
across 2-6 scenes is an aggregate an LLM can actually satisfy reliably,
unlike the full 20-30-scene, ~1670-word system-wide sum A2 used to be
asked for in one shot.

V2 narrative-continuity fix (STORY_IMPROVEMENT_PLAN.md Phase 1): this pass
used to expand each beat in total isolation -- the direct mechanical cause
of cross-scene repetition (any concept could get independently
re-explained by several different beats, each unaware the others had
already covered it). `expand_beat_scenes()` now takes and returns a
`ViewerLedger` threaded through `story_planner.py`'s existing per-beat
loop, so each beat knows what earlier beats already taught. No new LLM
call -- the loop was already sequential; this just carries state between
its existing calls.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from planning.models import NarrativeBeat, ScenePlan, SceneFunction, StoryBeat, ViewerLedger

TASK_PROMPT = """\
Break this ONE beat into concrete scenes using the MINIMUM number of words
actually needed to satisfy the beat's own learning objective -- not a fixed
target to hit regardless of content. Land within about 15% of `target_words`
when the beat genuinely has that much real depth to cover. If `target_words`
is large enough to need it, use multiple scenes rather than cramming
everything into one overloaded scene; a beat covering real source depth
should usually become 2-6 scenes, not always exactly one.

If `target_words` genuinely CANNOT be filled without padding -- restating
the same point in different words, or re-explaining something already
covered -- do not pad. Instead, write only what the content actually
supports and set `needs_rebudget=true` on the LAST scene you write for this
beat. This is a signal, not a failure: a deterministic pass afterward
redistributes the difference to beats that have real remaining depth,
rather than forcing every beat to hit the same number regardless of how
much it actually has to say.

Each scene needs: a realistic word_budget (30-100 hard bounds, 40-80
preferred), a narrative_beat (hook/teaching/escalation/reveal/close --
`reveal` should be used sparingly, not for every scene), and a concrete,
single-idea visual_description that follows from the beat's own
`purpose`, `forward_driver`, and `archetype_role` -- the scene must feel
caused by what came before it. Ground everything in the `available_claims`
given; never introduce a technical claim outside that registry. When an
available claim already IS a concrete illustration (an actual example, a
specific sentence pair, a real number) rather than an abstract statement,
the `visual_description` for the scene grounded in it must reference that
concrete illustration directly -- do not compress a claim like "changing
X to Y flips the answer" into a vaguer restatement like "context matters
for meaning."

If `visual_description` includes any mathematical or algorithmic
expression, write it in plain, readable notation only -- e.g. "a / sqrt(b)"
or "f(x)" -- never LaTeX escape syntax
(`\\frac{}{}`, `\\sqrt{}`, `\\operatorname{}`, `\\left`/`\\right`, `\\cdot`,
`\\top`, and similar backslash commands). This page renders no LaTeX
engine -- raw LaTeX source shows up as literal broken text on screen, not
typeset math.

You are also given `viewer_knows` -- concept labels already taught by
EARLIER beats -- and `running_example` (the one running illustration for
this whole video, if one has been set). The viewer has continuous memory
across the entire video: never plan a scene that re-explains a concept
already in `viewer_knows` from scratch. For each scene, set `scene_function`
honestly:
  - `standard`: a genuine first explanation of a concept not yet taught.
  - `derivation`: builds on a concept already in `viewer_knows` to reach
    something new -- list the concept(s) it builds on (not re-explains) in
    `must_not_repeat`; reference them in ≤1 sentence, never re-derive them.
  - `recap`: the scene's whole job is compressing prior material (e.g.
    before a payoff or a section boundary) -- keep it brief by design.
  - `preview`: a very short forward mention of something not taught yet,
    naming it without explaining its mechanism (the derivation scene that
    actually teaches it comes later).
List any genuinely NEW concept this beat introduces for the first time in
`new_concepts` (short, topic-specific labels naming the actual concept
this source teaches -- e.g. "the retry backoff formula" for a networking
source, "the balance invariant" for a tree-rotation source) so later beats
know not to re-teach it -- do not list a concept that is already in the
given `viewer_knows`.

If most of what remains to narrate for a beat is recap (nothing left to
teach that isn't already in `viewer_knows`), that is a signal to compress
it into ONE OR TWO `recap` scenes total, not to allocate the beat's usual
scene count to walking back through each already-taught concept one at a
time. This applies to any beat, but matters most for the CLOSING beat --
confirmed live: a real closing beat had 7 of its 9 scenes tagged `recap`
with zero new concepts between them, re-teaching the whole mechanism a
second time right after its real payoff had already landed. A closing
beat's job is to land the payoff and give one forward-looking beat, not
to re-derive everything scene by scene.

A `preview` scene can be too complete, not just present: if it reveals an
EXACT concrete value (a specific number, a specific outcome), not just
the general shape of the mechanism, name that exact value as its own
entry in `new_concepts` (e.g. "the exact 0.88 weight for X", not just "the
weights") -- so a later `derivation` scene that reaches the same value
knows to frame it as CONFIRMING what the viewer already saw, not
discovering it fresh.

If `running_example` is set (label/description/values), and this beat's
content is the same running illustration, reuse its exact named
objects/values in `visual_description` rather than inventing a new
example for the same idea -- the viewer should not have to rebuild their
mental model from scratch every beat.

You are also given `central_question` (the whole video's driving question)
and a `neighbor_contract` built from the plan's own existing fields for the
beat immediately before and after this one (either may be `null` at the
start/end of the video): each neighbor's `purpose`, `forward_driver`,
`viewer_question_before`, and `next_question`. Use it two ways: (1) do not
have this beat's scenes resolve or pre-empt what `next_beat.viewer_question_before`
or `next_beat.next_question` says the NEXT beat is responsible for
answering -- leave that genuinely open, even if a sentence resolving it
early would be easy to write; (2) do not have this beat re-answer a
question `previous_beat.next_question` already says was answered.

If `formula_stages` is non-empty and one of this beat's scenes visually
presents one of those registered stages (an equation, a worked
computation, a diagram of that step), set that scene's `formula_stage_id`
to the matching `stage_id` so its on-screen form can be checked against
the registered expression later -- once a stage has been reached, a later
scene representing the same computation must show that stage's form, not
an earlier, already-superseded one. Leave `formula_stage_id` blank for
every scene that isn't presenting one of these registered stages.

You are also given `mechanism_scope` -- the current known scope of any
mechanism whose applicability is conditional rather than universal (e.g.
a technique that only applies under one specific setup, not every
version of the underlying idea), as `{flag_name: true/false}`. If this
beat's own content is what ESTABLISHES that a mechanism only applies
under certain conditions, record that in `mechanism_scope_updates` with a
short, descriptive flag name (e.g. `"causal_mask_required"`) and its
value -- so a later beat's recap/summary can be checked against it. This
will be empty for most scenes -- only set it when this scene is genuinely
the one establishing or changing a mechanism's conditional scope.
"""


class ExpandedScene(BaseModel):
    narrative_beat: NarrativeBeat = "teaching"
    visual_description: str = ""
    word_budget: int = Field(ge=30, le=100, default=60)
    scene_function: SceneFunction = "standard"
    new_concepts: list[str] = Field(default_factory=list)
    must_not_repeat: list[str] = Field(default_factory=list)
    formula_stage_id: str = ""
    mechanism_scope_updates: dict[str, bool] = Field(default_factory=dict)
    needs_rebudget: bool = False  # STORY_IMPROVEMENT_PLAN.md Phase 12


class BeatSceneExpansion(BaseModel):
    scenes: list[ExpandedScene] = Field(default_factory=list)


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "importance": claim.importance}


def _neighbor_payload(beat: StoryBeat | None) -> dict | None:
    if beat is None:
        return None
    return {
        "purpose": beat.purpose, "forward_driver": beat.forward_driver,
        "viewer_question_before": beat.viewer_question_before, "next_question": beat.next_question,
    }


def expand_beat_scenes(
    beat: StoryBeat, target_words: int, claims: list[Claim], story_lead: Agent,
    budget: BudgetCounter, ledger: ViewerLedger,
    *, previous_beat: StoryBeat | None = None, next_beat: StoryBeat | None = None,
    central_question: str = "",
) -> tuple[list[ScenePlan], ViewerLedger]:
    beat_claims = [c for c in claims if c.source_unit in set(beat.source_unit_ids)]
    payload = {
        "beat_id": beat.beat_id, "purpose": beat.purpose, "archetype_role": beat.archetype_role,
        "forward_driver": beat.forward_driver, "learning_objective": beat.learning_objective,
        "target_words": target_words,
        "available_claims": [_claim_payload(c) for c in beat_claims],
        "viewer_knows": ledger.viewer_knows,
        "running_example": ledger.running_example.model_dump(),
        "formula_stages": [s.model_dump() for s in ledger.formula_stages],
        "mechanism_scope": ledger.mechanism_scope,
        "central_question": central_question,
        "neighbor_contract": {
            "previous_beat": _neighbor_payload(previous_beat),
            "next_beat": _neighbor_payload(next_beat),
        },
    }
    result = story_lead.run(
        pass_id="A2b", mode="SCENE_EXPANSION", task_prompt=TASK_PROMPT,
        payload=payload, schema=BeatSceneExpansion, budget=budget, estimated_usd=0.03,
    )
    scenes = []
    running_scope = dict(ledger.mechanism_scope)
    # STORY_IMPROVEMENT_PLAN.md Phase 27 item 2: `must_not_repeat` used to be tied
    # exclusively to `viewer_knows` (prior BEATS, via the model's own self-reporting from
    # the payload above) -- confirmed live, a real beat's own 3 sibling scenes (generated
    # in this SAME call) each independently re-derived the same setup, because nothing told
    # scene 3 that scenes 1-2 (its own siblings, not an earlier beat) already covered it.
    # Deterministic, same "arithmetic accumulates in Python, not left to the model to
    # self-track across its own single response" principle already used for
    # `new_viewer_knows` below -- accumulated and merged in, on top of (never replacing)
    # whatever cross-beat concepts the model itself already listed.
    sibling_concepts_so_far: list[str] = []
    for i, s in enumerate(result.scenes, start=1):
        running_scope.update(s.mechanism_scope_updates)
        must_not_repeat = list(s.must_not_repeat)
        for concept in sibling_concepts_so_far:
            if concept not in must_not_repeat:
                must_not_repeat.append(concept)
        scenes.append(ScenePlan(
            scene_id=f"{beat.beat_id}_s{i:02d}", beat_id=beat.beat_id,
            archetype_role=beat.archetype_role, narrative_beat=s.narrative_beat,
            narrative_job=beat.purpose, visual_description=s.visual_description,
            word_budget=s.word_budget, scene_function=s.scene_function,
            new_concepts=s.new_concepts, must_not_repeat=must_not_repeat,
            formula_stage_id=s.formula_stage_id,
            mechanism_scope=dict(running_scope),
            needs_rebudget=s.needs_rebudget,
        ))
        for concept in s.new_concepts:
            if concept not in sibling_concepts_so_far:
                sibling_concepts_so_far.append(concept)
    new_viewer_knows = list(ledger.viewer_knows)
    for scene in scenes:
        for concept in scene.new_concepts:
            if concept not in new_viewer_knows:
                new_viewer_knows.append(concept)
    updated_ledger = ViewerLedger(
        viewer_knows=new_viewer_knows, running_example=ledger.running_example,
        formula_stages=ledger.formula_stages, mechanism_scope=running_scope,
    )
    return scenes, updated_ledger
