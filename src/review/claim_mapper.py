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
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from narration.models import SceneNarration

TASK_PROMPT = """\
For each narration sentence below, decide independently -- ignoring nothing
except the words themselves -- whether it makes a factual, checkable
proposition (a claim about how something works, a number, a comparison, a
historical fact) as opposed to a transition, a rhetorical question, an
analogy, or a pure narrative beat with no checkable content.

Mark `grounding_required = true` for any sentence with a factual
proposition, even if it reads like an aside or is phrased conversationally.
Do not assume a sentence is safe just because it sounds like commentary --
"that's obviously true because X" still asserts X.

When grounding_required is true, list every claim_id from the registry that
plausibly supports it in `grounding_refs`. If no claim in the registry
covers it, leave `grounding_refs` empty -- that is itself important
information, not a failure to report.
"""


class MappedSentence(BaseModel):
    scene_id: str
    sentence_index: int
    grounding_required: bool
    grounding_refs: list[str] = Field(default_factory=list)


class ClaimMapperOutput(BaseModel):
    sentences: list[MappedSentence] = Field(default_factory=list)


def _sentence_payload(scene: SceneNarration, claims: list[Claim]) -> list[dict]:
    return [
        {"scene_id": scene.scene_id, "sentence_index": i, "text": sentence.text}
        for i, sentence in enumerate(scene.sentences)
    ]


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim}


def map_claims(
    narration: list[SceneNarration], claims: list[Claim], review_lead: Agent, budget: BudgetCounter,
) -> list[SceneNarration]:
    sentences_payload = [s for scene in narration for s in _sentence_payload(scene, claims)]
    payload = {"sentences": sentences_payload, "claim_registry": [_claim_payload(c) for c in claims]}

    mapped = review_lead.run(
        pass_id="CM", mode="CLAIM_MAPPER", task_prompt=TASK_PROMPT,
        payload=payload, schema=ClaimMapperOutput, budget=budget, estimated_usd=0.03,
    )

    by_key = {(m.scene_id, m.sentence_index): m for m in mapped.sentences}
    result: list[SceneNarration] = []
    for scene in narration:
        new_sentences = []
        for i, sentence in enumerate(scene.sentences):
            m = by_key.get((scene.scene_id, i))
            if m is None:
                new_sentences.append(sentence)  # no verdict returned -- leave untouched, never guess
                continue
            new_sentences.append(sentence.model_copy(update={
                "grounding_required": m.grounding_required,
                "grounding_refs": m.grounding_refs,
            }))
        result.append(scene.model_copy(update={"sentences": new_sentences}))
    return result
