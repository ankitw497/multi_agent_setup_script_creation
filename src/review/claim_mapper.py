"""CM -- the Claim Mapper (Review Lead / Gemini flash) (plan §5.1).

Reads every narration sentence and independently decides which carry a
factual proposition, mapping each to registry claims -- regardless of how
the writer classified it. The writer's sentence_type is deliberately NOT
shown to this pass: showing it would let the model anchor on the writer's
own label instead of judging independently, which is exactly the failure
this pass exists to prevent (plan §5.1: "never let the producer define its
own validation boundary").

CM accelerates grounding; it does not own completeness -- C2b independently
checks whether CM missed anything (plan §9 Appendix G #3).

STORY_IMPROVEMENT_PLAN.md Phase 10: a real bug lived here until this phase --
a sentence CM's structured output omitted a verdict for silently kept its
pydantic default (`grounding_required=False`), indistinguishable from CM
having actually checked it and found nothing factual. Both real A/B runs
that motivated this phase showed exactly this shape (a factual sentence
with `grounding_required=false` appearing later in the script than
earlier, across two different Story Lead models -- ruling out a
Story-Lead-specific cause). Fixed by keying verdicts to a stable
`sentence_id` and failing closed (`ReviewCoverageError`) when the response
doesn't cover every sentence, plus batching calls so a single giant
structured output isn't the thing silently truncating.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from llm.concurrency import run_concurrently
from narration.models import SceneNarration, stamp_sentence_ids

from .models import ReviewCoverageError

# Bounds the size of a single CM structured output -- lower truncation risk,
# smaller/easier retries, localized failures (STORY_IMPROVEMENT_PLAN.md Phase 10 §4.4).
CM_BATCH_SIZE = 20

FactualStatus = Literal["FACTUAL", "NON_FACTUAL", "UNCERTAIN"]

TASK_PROMPT = """\
For each narration sentence below, decide independently -- ignoring nothing
except the words themselves -- whether it makes a factual, checkable
proposition (a claim about how something works, a number, a comparison, a
historical fact) as opposed to a transition, a rhetorical question, an
analogy, or a pure narrative beat with no checkable content.

Set `factual_status` to FACTUAL for any sentence with a factual
proposition, even if it reads like an aside or is phrased conversationally
-- do not assume a sentence is safe just because it sounds like commentary,
"that's obviously true because X" still asserts X. Set it to NON_FACTUAL
for a transition/question/analogy/pure narrative beat with no checkable
content. If you genuinely cannot tell either way, set it to UNCERTAIN
rather than guessing NON_FACTUAL -- an uncertain sentence is routed to a
second, independent check, so it is always safe to say so.

You MUST return exactly one entry, keyed by `sentence_id`, for EVERY
sentence given -- never omit one, even a sentence you're confident is
NON_FACTUAL.

When factual_status is FACTUAL or UNCERTAIN, list every claim_id from the
registry that plausibly supports it in `grounding_refs`. If no claim in the
registry covers it, leave `grounding_refs` empty -- that is itself
important information, not a failure to report.
"""


class MappedSentence(BaseModel):
    sentence_id: str
    scene_id: str
    sentence_index: int
    factual_status: FactualStatus = "NON_FACTUAL"
    grounding_refs: list[str] = Field(default_factory=list)


class ClaimMapperOutput(BaseModel):
    sentences: list[MappedSentence] = Field(default_factory=list)


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim}


def _call_cm(
    batch: list[tuple[str, int, object]], claim_registry_payload: list[dict],
    review_lead: Agent, budget: BudgetCounter,
) -> ClaimMapperOutput:
    sentences_payload = [
        {"sentence_id": sentence.sentence_id, "scene_id": scene_id, "sentence_index": i, "text": sentence.text}
        for scene_id, i, sentence in batch
    ]
    payload = {"sentences": sentences_payload, "claim_registry": claim_registry_payload}
    return review_lead.run(
        pass_id="CM", mode="CLAIM_MAPPER", task_prompt=TASK_PROMPT,
        payload=payload, schema=ClaimMapperOutput, budget=budget, estimated_usd=0.03,
    )


def map_claims(
    narration: list[SceneNarration], claims: list[Claim], review_lead: Agent, budget: BudgetCounter,
) -> list[SceneNarration]:
    narration = stamp_sentence_ids(narration)
    all_sentences = [
        (scene.scene_id, i, sentence) for scene in narration for i, sentence in enumerate(scene.sentences)
    ]
    claim_registry_payload = [_claim_payload(c) for c in claims]

    # 2026-09-15: batches are independent of each other (each covers a disjoint slice of
    # sentences against the same read-only claim registry), so they're dispatched
    # concurrently -- llm/concurrency.py's own docstring explains why this is safe and why
    # it only saves wall-clock, not $ (each batch is still billed the same). BudgetCounter
    # now locks its own bookkeeping (llm/budget.py) so sharing one `budget` across threads
    # is safe.
    batches = [all_sentences[i:i + CM_BATCH_SIZE] for i in range(0, len(all_sentences), CM_BATCH_SIZE)]
    results = run_concurrently([
        (lambda b=batch: _call_cm(b, claim_registry_payload, review_lead, budget)) for batch in batches
    ])
    verdicts_by_id: dict[str, MappedSentence] = {}
    for mapped in results:
        for m in mapped.sentences:
            verdicts_by_id[m.sentence_id] = m

    expected_ids = {sentence.sentence_id for _, _, sentence in all_sentences}
    missing_ids = expected_ids - verdicts_by_id.keys()
    if missing_ids:
        # STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live (2026-09-15) --
        # even a bounded ~20-sentence batch can still drop a single entry (a real run
        # missed 1/57 sentences with batching already in place, distinct from the
        # pre-batching 16/58 failure this phase originally fixed). One small retry with
        # JUST the missing sentences resolves an isolated, likely-stochastic miss without
        # paying to redo whole batches or failing the entire run over one sentence.
        retry_batch = [(scene_id, i, sentence) for scene_id, i, sentence in all_sentences if sentence.sentence_id in missing_ids]
        retried = _call_cm(retry_batch, claim_registry_payload, review_lead, budget)
        for m in retried.sentences:
            verdicts_by_id[m.sentence_id] = m
        missing_ids = expected_ids - verdicts_by_id.keys()

    if missing_ids:
        missing = sorted(missing_ids)
        raise ReviewCoverageError(
            f"CM did not return a verdict for {len(missing)}/{len(expected_ids)} sentence(s) "
            f"even after one retry: {missing[:10]}{'...' if len(missing) > 10 else ''}"
        )

    result: list[SceneNarration] = []
    for scene in narration:
        new_sentences = []
        for sentence in scene.sentences:
            m = verdicts_by_id[sentence.sentence_id]
            new_sentences.append(sentence.model_copy(update={
                # UNCERTAIN is treated as requiring grounding -- conservative by design,
                # never silently dropped (Phase 10 §4.2's third verdict state).
                "grounding_required": m.factual_status in ("FACTUAL", "UNCERTAIN"),
                "grounding_refs": m.grounding_refs,
            }))
        result.append(scene.model_copy(update={"sentences": new_sentences}))
    return result
