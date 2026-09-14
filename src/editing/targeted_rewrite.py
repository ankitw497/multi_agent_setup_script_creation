"""B2 -- targeted rewrite (Narration Lead / Sonnet, subscription lane) (plan §8, §15).

A3 already decided WHAT must change (`RevisionPlan.rewrite_beats` /
`technical_fixes` / `delete_or_compress`) and named the INTENT, never the
prose (plan §15's own rule: the revision planner decides scope, the
narration lead decides how it sounds). This pass executes exactly that
scope: only the named beats'/scenes' narration is regenerated; every other
scene is passed through byte-for-byte untouched, so a targeted rewrite can
never silently drift a part of the script A3 never named.

`delete_or_compress` has no separate delete-vs-compress flag in the
`RevisionPlan` contract (it's A3's own judgement call, carried only in
`reason`) -- this pass treats it as a scoped rewrite of that one scene,
never removing it from `plan.scene_plan` (which the structural hard checks
are keyed off of). A genuinely redundant scene compresses down to a single
bridging sentence rather than being structurally deleted -- a deliberate
V1A scope choice, not an oversight (removing a scene from the plan would
leave `plan.scene_plan`'s own word-budget target inconsistent with what
was actually narrated).
"""
from __future__ import annotations

from agents.base import Agent
from facts.models import Claim
from narration.models import SceneNarration, SentenceNarration
from planning.models import StoryPlan

from .models import RevisionPlan

PLANNING_WPM = 167

TASK_PROMPT = """\
Rewrite ONLY the scenes listed below, each with its own `required_intent`
-- do not touch anything else, and do not expand scope beyond what the
intent actually asks for. Follow the same voice rules as a first draft:
short-to-medium sentences, varied rhythm, concrete verbs, causal
connectors. Stay within the scene's word_budget. Ground every
technical_assertion/source_paraphrase sentence in a real claim from
`available_claims` and cite it in `claim_refs` -- never invent a technical
claim that isn't in the registry. Anything named in `preserve` must not be
contradicted by the rewrite. If a scene's intent says to delete or
compress a redundant scene, either compress it to the smallest sentence
that still bridges the surrounding scenes, or -- only if it is genuinely
adding nothing -- return it with a single short bridging sentence and no
technical content; never leave a scene's sentences empty.

The viewer has continuous memory across the entire video -- a rewrite must
not reintroduce a repetition the original draft avoided. Each scene still
carries `scene_function`, `new_concepts`, and `must_not_repeat`, set by the
planner:
- `scene_function=standard`: a genuine first explanation -- write it in full.
- `scene_function=derivation`: this scene builds on concepts listed in
  `must_not_repeat`. Reference each in ONE short clause (e.g. "since we
  already have X from before,...") -- do not re-explain or re-derive it,
  even briefly, as if for the first time.
- `scene_function=recap`: compress everything it touches into 1-2 bridging
  sentences on the way to what's new -- never restate it at full length.
- `scene_function=preview`: keep it to a single short forward-looking line
  naming what's coming, without explaining the mechanism yet.
If `running_example` is set (non-empty `label`), and this scene's content
is the same running illustration, reuse its exact named objects and values
verbatim -- never invent new numbers or a different example for the same
underlying idea, even when rewriting for a different reason.
"""


def _claims_for_beat(beat_id: str, plan: StoryPlan, claims: list[Claim]) -> list[Claim]:
    beat = next((b for b in plan.beats if b.beat_id == beat_id), None)
    if beat is None:
        return []
    unit_ids = set(beat.source_unit_ids)
    return [c for c in claims if c.source_unit in unit_ids]


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status}


def _touched_scene_intents(plan: StoryPlan, revision_plan: RevisionPlan) -> dict[str, str]:
    """scene_id -> the combined intent text every finding that named it asked for."""
    intents: dict[str, str] = {}

    rewrite_intent_by_beat = {rb.beat_id: rb.intent for rb in revision_plan.rewrite_beats}
    for scene in plan.scene_plan:
        if scene.beat_id in rewrite_intent_by_beat:
            intents[scene.scene_id] = rewrite_intent_by_beat[scene.beat_id]

    # Narrower than rewrite_beats (STORY_IMPROVEMENT_PLAN.md Phase 8.5): a
    # scene-scoped fix, same blast radius as technical_fixes/
    # delete_or_compress below -- never the whole beat's worth of scenes.
    for rs in revision_plan.rewrite_scenes:
        note = f"targeted fix: {rs.intent}"
        intents[rs.scene_id] = f"{intents[rs.scene_id]}; {note}" if rs.scene_id in intents else note

    for fix in revision_plan.technical_fixes:
        note = f"technical correction: {fix.required_change}"
        if fix.claim_id:
            note += f" (claim {fix.claim_id})"
        intents[fix.scene_id] = f"{intents[fix.scene_id]}; {note}" if fix.scene_id in intents else note

    for dc in revision_plan.delete_or_compress:
        note = f"delete or compress -- {dc.reason}"
        intents[dc.scene_id] = f"{intents[dc.scene_id]}; {note}" if dc.scene_id in intents else note

    return intents


def apply_targeted_rewrite(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    revision_plan: RevisionPlan, narration_lead: Agent,
) -> list[SceneNarration]:
    from narration.generator import GeneratedNarration  # reuse B1's response schema

    intents = _touched_scene_intents(plan, revision_plan)
    if not intents:
        return narration  # A3 named nothing concrete -- nothing to touch

    scene_by_id = {s.scene_id: s for s in plan.scene_plan}
    scenes_payload = []
    for scene_id, intent in intents.items():
        scene = scene_by_id.get(scene_id)
        if scene is None:
            continue  # A3 named a scene id that no longer exists in the plan
        beat_claims = _claims_for_beat(scene.beat_id, plan, claims)
        scenes_payload.append({
            "scene_id": scene.scene_id, "beat_id": scene.beat_id,
            "narrative_job": scene.narrative_job, "archetype_role": scene.archetype_role,
            "narrative_beat": scene.narrative_beat, "visual_description": scene.visual_description,
            "word_budget": scene.word_budget, "required_intent": intent,
            "scene_function": scene.scene_function, "new_concepts": scene.new_concepts,
            "must_not_repeat": scene.must_not_repeat,
            "available_claims": [_claim_payload(c) for c in beat_claims],
        })

    if not scenes_payload:
        return narration

    payload = {
        "story_promise": plan.story_promise, "central_question": plan.central_question,
        "preserve": revision_plan.preserve, "scenes": scenes_payload,
        "running_example": plan.running_example.model_dump(),
    }
    rewritten = narration_lead.run(
        # timeout_s=300 (2026-09-14, was 180): a real "targeted" rewrite can
        # still carry multiple scenes' full claim payloads (a whole-beat
        # rewrite_beats call, not just a single scene) -- confirmed live,
        # twice, on two separate runs: the 180s ceiling was too tight even
        # after ERR-050's fix made a timeout retryable, since every retry
        # hit the exact same too-short limit and still failed. Matches B1's
        # own timeout_s=300 (narration/generator.py) for the same reason --
        # a full-scale Sonnet narration call routinely needs this long.
        pass_id="B2", mode="TARGETED_REWRITE", task_prompt=TASK_PROMPT,
        payload=payload, schema=GeneratedNarration, timeout_s=300,
    )
    rewritten_by_id = {s.scene_id: s for s in rewritten.scenes}

    result: list[SceneNarration] = []
    for scene in narration:
        gs = rewritten_by_id.get(scene.scene_id)
        if gs is None:
            result.append(scene)  # untouched, byte-for-byte
            continue
        sentences = [
            SentenceNarration(text=s.text, sentence_type=s.sentence_type, claim_refs=s.claim_refs)
            for s in gs.sentences
        ]
        word_count = sum(len(s.text.split()) for s in sentences)
        result.append(SceneNarration(
            scene_id=scene.scene_id, sentences=sentences, est_seconds=word_count / PLANNING_WPM * 60,
        ))
    return result
