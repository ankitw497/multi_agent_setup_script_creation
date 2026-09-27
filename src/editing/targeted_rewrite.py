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
from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS
from narration.models import SceneNarration, SentenceNarration
from planning.models import StoryPlan

from .models import RevisionPlan

PLANNING_WPM = 167

# ERR-065 (2026-09-15): a gpt-5.6-sol live run's revision plan named 16 scenes in one
# rewrite_beats/rewrite_scenes/technical_fixes/delete_or_compress mix -- sent as a single B2
# call, each scene carrying its own visual_description + available_claims, it timed out at
# the 300s ceiling ERR-051 had raised specifically because "not yet live-verified" a large
# batch would fit. Chunking bounds each call's payload the same way CM/C2b already batch
# (review/claim_mapper.py's CM_BATCH_SIZE) instead of raising the timeout again with no
# ceiling on how large a single revision plan can get.
B2_BATCH_SIZE = 5

TASK_PROMPT = """\
Rewrite ONLY the scenes listed below, each with its own `required_intent`
-- do not touch anything else, and do not expand scope beyond what the
intent actually asks for. Follow the same voice rules as a first draft:
short-to-medium sentences, varied rhythm, concrete verbs, causal
connectors.

Causal connectors are seasoning, not a default sentence template: use one
where the actual logic calls for it, but let most sentences open plainly,
with no connector at all. The same discipline applies to any other
rhetorical device (e.g. a "not X, but Y" contrast, or "The fix:"/"So the
fix:" as the pivot from problem to solution -- confirmed live as a real
repeat offender, 3 uses across 3 consecutive beats in one script) --
effective the first couple of times, a tell once it becomes a default
move. This matters MORE here than in a first draft: you only see the
handful of scenes listed below, not the whole script, so a device that
reads as fine in isolation may already be overused elsewhere in scenes
you can't see -- never use the same connector word or device in two of
YOUR OWN rewritten scenes here, and when `required_intent` names a
repetition/repeated-device problem specifically, treat that as a signal
to reach for a genuinely different construction, not a synonym of the
same one. "One idea per sentence" is not "one length per sentence" either
(2026-09-25, Phase 30 P2 item 7 -- this rewrite pass had never received
this guidance at all, unlike the first-draft prompt): mix sentence
lengths across your rewritten scenes rather than rebuilding every
sentence out to the same comfortable medium length. Stay within the
scene's word_budget. Ground every
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

A scene's own `mechanism_scope` (`{flag_name: true/false}`) is the current
known scope of any mechanism whose applicability is conditional rather than
universal. If this scene states such a mechanism, use its actual recorded
condition -- never drop the qualifier for brevity, even under a tight
word_budget.

A scene with `is_cta_beat=true` is the ONLY scene that may carry the CTA:
write it in `cta.intent`'s chosen intent, at most 18 words, naming the
payoff just earned -- never a generic "like and subscribe", never a second
CTA in a scene where `is_cta_beat` is false. A scene with
`is_true_final_scene=true` that is NOT `is_cta_beat` may add one short, soft
closing line reinforcing the payoff only if `cta.final_enabled` is true;
if it is false, end that scene cleanly on its own content with no
CTA-adjacent language at all.

A scene with `is_hook_last_scene=true` must end on `hook.open_loop`, voiced
as a genuine, unresolved question (a close paraphrase is fine) -- never let
its closing line state or imply the mechanism/answer, even partially, since
that resolves the exact curiosity the hook exists to create.

""" + NARRATION_FACTUAL_INVARIANTS


def _claims_for_beat(beat_id: str, plan: StoryPlan, claims: list[Claim]) -> list[Claim]:
    beat = next((b for b in plan.beats if b.beat_id == beat_id), None)
    if beat is None:
        return []
    unit_ids = set(beat.source_unit_ids)
    return [c for c in claims if c.source_unit in unit_ids]


def _claim_payload(claim: Claim) -> dict:
    # importance included (2026-09-26, Phase 32 P0): same fix as
    # narration/short_generator.py's own _claim_payload -- the shared
    # NARRATION_FACTUAL_INVARIANTS fragment below gates narration on
    # `importance` + `verification_status` together, which this payload
    # used to make impossible to follow.
    return {
        "claim_id": claim.claim_id, "claim": claim.claim,
        "verification_status": claim.verification_status, "importance": claim.importance,
    }


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


def _hook_last_scene_id(plan: StoryPlan) -> str:
    # positional, not archetype_role=="hook" (2026-09-27, found live): archetype_role is a
    # plain, model-filled string, not a Literal -- a beat that IS the hook by construction
    # but whose archetype_role the model tagged slightly differently (or left blank) would
    # silently disable this whole guardrail with no signal at all. Matches the same,
    # already-established, safer convention `verification/diagnostics/pacing.py` uses for
    # the exact same "which beat is the hook" question (its own comment: "the FIRST beat
    # (the hook, by construction)"), rather than trusting the label.
    if not plan.beats:
        return ""
    hook_beat_id = plan.beats[0].beat_id
    hook_scenes = [s.scene_id for s in plan.scene_plan if s.beat_id == hook_beat_id]
    return hook_scenes[-1] if hook_scenes else ""


def apply_targeted_rewrite(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    revision_plan: RevisionPlan, narration_lead: Agent,
) -> list[SceneNarration]:
    from narration.generator import GeneratedNarration  # reuse B1's response schema

    intents = _touched_scene_intents(plan, revision_plan)
    if not intents:
        return narration  # A3 named nothing concrete -- nothing to touch

    hook_last_scene_id = _hook_last_scene_id(plan)
    true_final_scene_id = plan.scene_plan[-1].scene_id if plan.scene_plan else ""

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
            # mechanism_scope/is_cta_beat/is_hook_last_scene/is_true_final_scene added
            # (2026-09-26, Phase 32 P0): B1's own first-draft prompt has hard rules keyed
            # off all four of these, but this rewrite pass previously sent none of them --
            # a rewrite of a recap scene, the CTA scene, or the hook's closing scene had
            # neither the rule nor the data needed to avoid re-breaking what B1 got right.
            "mechanism_scope": scene.mechanism_scope,
            "is_cta_beat": scene.beat_id == plan.cta.primary_after_beat,
            "is_hook_last_scene": scene.scene_id == hook_last_scene_id,
            "is_true_final_scene": scene.scene_id == true_final_scene_id,
            "available_claims": [_claim_payload(c) for c in beat_claims],
        })

    if not scenes_payload:
        return narration

    rewritten_by_id: dict[str, object] = {}
    for batch_start in range(0, len(scenes_payload), B2_BATCH_SIZE):
        batch = scenes_payload[batch_start:batch_start + B2_BATCH_SIZE]
        payload = {
            "story_promise": plan.story_promise, "central_question": plan.central_question,
            "preserve": revision_plan.preserve, "scenes": batch,
            "running_example": plan.running_example.model_dump(),
            # cta/hook added (2026-09-26, Phase 32 P0) -- see each scene's own
            # is_cta_beat/is_hook_last_scene flags above for which rewritten
            # scene(s), if any, these rules actually apply to this call.
            "cta": plan.cta.model_dump(), "hook": plan.hook.model_dump(),
        }
        rewritten = narration_lead.run(
            # timeout_s=300 (2026-09-14, was 180): matches B1's own
            # timeout_s=300 (narration/generator.py) -- a full-scale Sonnet
            # call routinely needs this long. ERR-065 (2026-09-15): even at
            # 300s this was not enough once a single call carried 16 scenes'
            # worth of claims -- B2_BATCH_SIZE above is what actually bounds
            # payload size now; this timeout is a per-batch ceiling, not a
            # substitute for chunking.
            pass_id="B2", mode="TARGETED_REWRITE", task_prompt=TASK_PROMPT,
            payload=payload, schema=GeneratedNarration, timeout_s=300,
        )
        for s in rewritten.scenes:
            rewritten_by_id[s.scene_id] = s

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
