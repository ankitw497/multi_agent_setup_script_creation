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

from .models import SceneNarration, SentenceNarration, SentenceType

PLANNING_WPM = 167

TASK_PROMPT = """\
Write the spoken narration for every scene in the story plan below, in the
plan's own voice: short-to-medium sentences, varied rhythm, concrete verbs,
causal connectors (because, so, but, which means, that creates a problem,
so we need, this solves). Write for listening, never for silent reading.

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
- If this scene is the CTA scene (matches plan.cta.primary_after_beat or is
  the final scene), write the CTA sentence in the plan's chosen intent, ≤18
  words, naming the payoff just earned -- never a generic "like and
  subscribe".
- Do not invent a technical claim that is not in the claim registry. Reduce
  words, never the causal reasoning a mechanism needs to make sense.

The viewer has continuous memory across the entire video -- do not treat any
scene as a standalone article. Each scene carries `scene_function`,
`new_concepts`, and `must_not_repeat`, set by the planner:
- `scene_function=standard`: a genuine first explanation -- write it in full.
- `scene_function=derivation`: this scene builds on concepts listed in
  `must_not_repeat`. Reference each in ONE short clause (e.g. "since we
  already have X from before,...") -- do not re-explain or re-derive it,
  even briefly, as if for the first time.
- `scene_function=recap`: compress everything it touches into 1-2 bridging
  sentences on the way to what's new -- never restate it at full length.
- `scene_function=preview`: keep it to a single short forward-looking line
  naming what's coming, without explaining the mechanism yet.
If `running_example` is set (non-empty `label`), and a scene's content is
the same running illustration, reuse its exact named objects and values
verbatim -- never invent new numbers or a different example for the same
underlying idea; the viewer should not have to rebuild their mental model
from scratch every scene.

State a claim whose `verification_status` is VERIFIED as plain, direct fact
-- never hedge a verified technical claim with "is believed to", "is
thought to", or "seems to"; that phrasing belongs to genuine uncertainty,
not to a fact the pipeline has already confirmed. When describing a soft,
weighted, or probabilistic mechanism, prefer language that reflects a
weighted contribution over language implying a single hard selection (a
higher-scoring option "contributes more strongly," not "is the one
selected," unless the real mechanism genuinely does pick exactly one).
When a behavior is actually produced by several components acting
together, describe what one component contributes rather than claiming it
alone fully causes or resolves the outcome. Never state a detail specific
to one architecture, algorithm, or implementation as if it were universal
to every version of the underlying general idea.
"""


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
    return {"claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status}


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
            "must_not_repeat": scene.must_not_repeat,
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
        payload=payload, schema=GeneratedNarration, timeout_s=300,
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
