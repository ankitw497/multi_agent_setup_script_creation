"""B1 -- narration first draft (Narration Lead / Sonnet, subscription lane) (plan §5, §8, §11.4).

One call for the whole script (batch, don't loop -- the plan's own cost
discipline). sentence_type is the writer's own metadata, never the
grounding boundary (plan §5.1) -- grounding_required/grounding_refs are
left unset here and populated later, independently, by the Claim Mapper.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from planning.models import StoryPlan

from .factual_invariants import NARRATION_FACTUAL_INVARIANTS
from .models import SceneNarration, SentenceNarration, SentenceType

PLANNING_WPM = 167

TASK_PROMPT = """\
Write the spoken narration for every scene in the story plan below, in the
plan's own voice: short-to-medium sentences, varied rhythm, concrete verbs,
causal connectors (because, so, but, which means, that creates a problem,
so we need, this solves). Write for listening, never for silent reading.

Causal connectors are seasoning, not a default sentence template: use one
where the actual logic calls for it, but let most sentences open plainly,
with no connector at all -- a script where "so"/"since"/"because" opens
several sentences in a row reads as formulaic, not causal. The same
discipline applies to any other rhetorical device (e.g. a "not X, but Y"
contrast) -- effective the first couple of times, a tell once it becomes
the script's default move. Real variety, not a rotating cast of the same
few constructions, is what makes narration sound spoken rather than
templated.

Confirmed live, twice, on real full-length narration from two different
models: "so" opening sentence after sentence across the WHOLE script (not
just within one scene) is a real, recurring failure mode this instruction
alone has not been enough to prevent -- so it needs a hard number, not
just a qualitative warning. Across the ENTIRE narration you write in this
one call: no more than 2 sentences total may open with "so", no more than
2 may open with "because"/"since", and no two sentences in a row --
including across a scene boundary -- may open with the same connector
word or the same rhetorical device (e.g. two "not X, but Y" contrasts back
to back). If a sentence's logic would naturally lead with "so", first try
stating the consequence directly instead ("So the scores blow up" ->
"The scores blow up") -- reserve the connector for the few places its own
causal weight actually earns it.

One specific device confirmed live (2026-09-25) as a repeat offender in its
own right: "The fix:" (and near-variants like "So the fix:") used to open
the sentence that pivots from a problem to its solution -- a real script
used it 3 times, clustered across 3 consecutive beats. It counts against
the SAME cap as any other rhetorical device above (at most 2 uses total
across the whole script, never twice in a row) -- vary the pivot instead
(name the mechanism directly, state what changes, or ask what the fix
would need to do) rather than reaching for this exact phrase by default.

Each sentence carries exactly ONE idea. If a sentence needs "and" or
"because" to link two separate claims, or a claim plus its own
consequence, split it into two sentences instead -- a single 50+ word
sentence stacking cause, mechanism, and a numeric example together is
harder to follow out loud than the same content in two or three shorter
ones, even though the total information is the same.

"One idea per sentence" is not "one length per sentence" -- confirmed
live (STORY_IMPROVEMENT_PLAN.md Phase 30 P2 item 7), this instruction's
own side effect can flatten every sentence toward the same medium length,
measurably (a real script's rhythm/burstiness diagnostic landed AMBER,
outside its target band, meaning sentence lengths clustered too tightly
around the average instead of genuinely varying). Deliberately mix
sentence lengths within each scene: at least one short (under 8 words)
punch sentence alongside the longer explanatory ones -- a landed
conclusion, a flat statement of what just happened, a single-clause
transition -- not every sentence built out to the same comfortable
medium length just because each one only carries one idea.

For each scene:
- Stay within its word_budget (target the middle of 30-100 words; err toward
  the beat's own pacing, not a fixed count).
- Follow the beat's narrative_job, forward_driver, and archetype_role -- the
  scene must feel caused by what came before it, not a topic switch.
- Ground every technical_assertion and source_paraphrase sentence in a real
  claim from the registry given -- cite it in `claim_refs`. Never state a
  technical fact with no backing claim.
- Classify each sentence's `sentence_type` honestly:
  technical_assertion / source_paraphrase / explanatory_inference / analogy /
  transition / question / payoff / cta. This is your own bookkeeping, not a
  security boundary -- classify accurately rather than to avoid scrutiny.
- Do not merely describe what a visual shows -- explain its consequence.
- The beat whose `archetype_role` is `hook` is the video's very first beat --
  its LAST scene must end on `hook.open_loop`, voiced as a genuine,
  unresolved QUESTION (a close paraphrase is fine, it need not be verbatim).
  Never let the hook's own closing line already state or imply the
  mechanism/answer, even partially -- that resolves the exact curiosity a
  hook exists to create instead of sustaining it. Confirmed live on a real
  comparison between two full scripts on the same source: one hook closed
  by stating its own conclusion in declarative form, the other closed on
  its `open_loop` field's literal question -- the question was the
  stronger hook, and it's exactly what `open_loop` was written to hand
  you, not just plan-internal bookkeeping. `hook.tension` (plus any
  concrete illustration) is what builds the tension; `open_loop` is what
  should still be ringing in the viewer's ear as the video moves past the
  hook.
- A scene is the CTA scene ONLY when it matches `plan.cta.primary_after_beat`
  -- full stop, never because it happens to be the final scene. There, write
  the CTA sentence in the plan's chosen intent, ≤18 words, naming the payoff
  just earned -- never a generic "like and subscribe". Do not invent a
  second CTA scene the plan didn't place.
- If the video's TRUE final scene is a DIFFERENT scene than the one above,
  and `cta.final_enabled` is true, that final scene may add ONE short, soft
  closing line reinforcing the payoff just earned -- never a second full CTA
  ask, never a new call to action. If `cta.final_enabled` is false, the
  final scene must end cleanly on its own content with no CTA-adjacent
  language at all.
- Do not invent a technical claim that is not in the claim registry. Reduce
  words, never the causal reasoning a mechanism needs to make sense.

The viewer has continuous memory across the entire video -- do not treat any
scene as a standalone article. Each scene carries `scene_function`,
`new_concepts`, and `must_not_repeat`, set by the planner:
- `scene_function=standard`: a genuine first explanation -- write it in full.
- `scene_function=derivation`: this scene builds on concepts listed in
  `must_not_repeat`. Reference each in ONE short clause (e.g. "since we
  already have X from before,...") -- do not re-explain or re-derive it,
  even briefly, as if for the first time. If `must_not_repeat` names an
  EXACT value (a specific number or outcome, not just a general concept)
  the viewer already saw during an earlier preview, frame reaching it here
  as CONFIRMING what was already shown rather than presenting it as a fresh
  discovery -- vary how you signal that across the script instead of
  reaching for the same construction every time (e.g. "that's the same
  0.88 we already saw -- here's why", "0.88 again -- and now we know why",
  "the number hasn't moved: still 0.88"). Confirmed live: a real script's
  contraction rate landed AMBER against the fitted voice bands, driven
  disproportionately by "that's"/"it's" used as the default confirming-
  callback opener in scene after scene -- treat this the same as any other
  rhetorical device in this prompt (the "so"/"because"/"The fix:" caps
  above): effective once, a tell once it becomes the reflexive default.
  `must_not_repeat` now also names concepts your OWN earlier scenes in this
  SAME beat already covered, not just other beats -- confirmed live: a real
  script re-derived the same underlying assumptions across 3 consecutive
  scenes within one beat, violating this rule even though it was already
  flagged, apparently because the source felt like "the same beat, still
  building the same point" rather than a genuinely separate prior scene. A
  sibling scene two
  sentences back is exactly as off-limits to re-derive as a concept from a
  completely different, earlier beat -- proximity within the same beat is
  not an exception.
- `scene_function=recap`: compress everything it touches into 1-2 bridging
  sentences on the way to what's new -- never restate it at full length.
- `scene_function=preview`: keep it to a single short forward-looking line
  naming what's coming, without explaining the mechanism yet.
If `running_example` is set (non-empty `label`), and a scene's content is
the same running illustration, reuse its exact named objects and values
verbatim -- never invent new numbers or a different example for the same
underlying idea; the viewer should not have to rebuild their mental model
from scratch every scene.

Each scene also carries `mechanism_scope` -- the current known scope of
any mechanism whose applicability is conditional rather than universal
(e.g. a technique that only applies under one specific setup), as
`{flag_name: true/false}`. A `recap`/summary scene must state such a
mechanism using its actual recorded condition, never as an unconditional,
universal fact -- if `mechanism_scope` says a technique only applies under
a specific condition, say so, don't drop the qualifier for brevity.

State a claim whose `verification_status` is VERIFIED as plain, direct fact
-- never hedge a verified technical claim with "is believed to", "is
thought to", or "seems to"; that phrasing belongs to genuine uncertainty,
not to a fact the pipeline has already confirmed. Every claim also carries
`importance` (CORE/SUPPORTING/OPTIONAL) and `verification_status`
together, and they gate whether a claim may be narrated AT ALL, not just
how confidently to phrase it:
  - REJECTED: never narrate this claim, in any form, regardless of importance.
  - UNVERIFIED with importance CORE or SUPPORTING: do not narrate this
    specific fact -- no hedge makes it acceptable. Either omit it, or, if
    the scene genuinely needs that content, ground it in a different
    VERIFIED or CONTEXT_DEPENDENT claim instead.
  - UNVERIFIED with importance OPTIONAL: only narrate it with an explicit
    hedge ("approximately," "roughly," "in this example," "under these
    assumptions," or similar) -- never state it as settled fact.
  - CONTEXT_DEPENDENT: narrate it as true within the stated context, not
    as a universal fact.
This is a hard requirement, not a style preference -- a scene that skips a
claim it can't ground this way is correct; a scene that narrates it anyway
is not. When describing a soft,
weighted, or probabilistic mechanism, prefer language that reflects a
weighted contribution over language implying a single hard selection (a
higher-scoring option "contributes more strongly," not "is the one
selected," unless the real mechanism genuinely does pick exactly one).
When a behavior is actually produced by several components acting
together, describe what one component contributes rather than claiming it
alone fully causes or resolves the outcome. Never state a detail specific
to one architecture, algorithm, or implementation as if it were universal
to every version of the underlying general idea.

""" + NARRATION_FACTUAL_INVARIANTS


class GeneratedSentence(BaseModel):
    text: str
    sentence_type: SentenceType
    claim_refs: list[str] = Field(default_factory=list)


class GeneratedScene(BaseModel):
    scene_id: str
    sentences: list[GeneratedSentence] = Field(default_factory=list)


class GeneratedNarration(BaseModel):
    scenes: list[GeneratedScene] = Field(default_factory=list)


def _claims_for_beat(beat_id: str, plan: StoryPlan, claims: list[Claim]) -> list[Claim]:
    beat = next((b for b in plan.beats if b.beat_id == beat_id), None)
    if beat is None:
        return []
    unit_ids = set(beat.source_unit_ids)
    return [c for c in claims if c.source_unit in unit_ids]


def _claim_payload(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id, "claim": claim.claim,
        "verification_status": claim.verification_status, "importance": claim.importance,
    }


def generate_narration(plan: StoryPlan, claims: list[Claim], narration_lead: Agent) -> list[SceneNarration]:
    scenes_payload = []
    for scene in plan.scene_plan:
        beat_claims = _claims_for_beat(scene.beat_id, plan, claims)
        scenes_payload.append({
            "scene_id": scene.scene_id, "beat_id": scene.beat_id,
            "narrative_job": scene.narrative_job, "archetype_role": scene.archetype_role,
            "narrative_beat": scene.narrative_beat, "visual_description": scene.visual_description,
            "word_budget": scene.word_budget,
            "scene_function": scene.scene_function, "new_concepts": scene.new_concepts,
            "must_not_repeat": scene.must_not_repeat, "mechanism_scope": scene.mechanism_scope,
            "available_claims": [_claim_payload(c) for c in beat_claims],
        })

    payload = {
        "story_promise": plan.story_promise, "central_question": plan.central_question,
        "hook": plan.hook.model_dump(), "cta": plan.cta.model_dump(), "ending": plan.ending.model_dump(),
        "running_example": plan.running_example.model_dump(),
        "scenes": scenes_payload,
    }

    generated = narration_lead.run(
        pass_id="B1", mode="FIRST_DRAFT", task_prompt=TASK_PROMPT,
        payload=payload, schema=GeneratedNarration, timeout_s=600,
    )

    result: list[SceneNarration] = []
    for scene in generated.scenes:
        sentences = [
            SentenceNarration(text=s.text, sentence_type=s.sentence_type, claim_refs=s.claim_refs)
            for s in scene.sentences
        ]
        word_count = sum(len(s.text.split()) for s in sentences)
        result.append(SceneNarration(
            scene_id=scene.scene_id, sentences=sentences,
            est_seconds=word_count / PLANNING_WPM * 60,
        ))
    return result
