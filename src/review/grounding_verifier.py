"""C2b -- grounding completeness + fidelity (Review Lead / Gemini strong) (plan §5.1, §9 Appendix G #3).

CM accelerates grounding; C2b owns completeness. It receives the raw
narration, CM's own output, and the verified fact set -- and does NOT
trust CM's coverage. Two genuine judgement calls no deterministic check
can make:

1. Completeness: did CM miss a factual proposition CM marked
   grounding_required=False (or never touched)?
2. Fidelity: does a grounded sentence actually say what its cited claim
   says, or has paraphrasing drifted the meaning (e.g. "grows with
   tokens" silently becoming "grows quadratically with tokens")?
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from narration.models import SceneNarration

from .models import CritiqueIssue

TASK_PROMPT = """\
You are independently checking grounding for a narration draft. Do not
trust the `grounding_required`/`grounding_refs` already attached to each
sentence -- another pass produced those, and your job is to catch what it
missed, not confirm it.

For every sentence:
1. COMPLETENESS: if it was marked grounding_required=false, decide for
   yourself whether it actually contains a factual, checkable proposition.
   If it does, raise an issue (category=technical or source depending on
   the failure, layer=NARRATION) naming which claim (if any in the
   registry) should have been cited.
2. FIDELITY: if it was marked grounding_required=true with grounding_refs,
   check whether the sentence actually says what the cited claim says --
   not just whether a claim id is attached. A sentence that changes
   "grows with tokens" to "grows quadratically with tokens" while still
   citing the same claim is a fidelity failure, not a grounding success.
   Raise an issue for any drift, however small it looks.

Only raise issues for real problems -- a sentence correctly marked
ungrounded (a transition, a question, an analogy with no factual content)
needs nothing.
"""


class GroundingReview(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _sentence_payload(scene: SceneNarration) -> list[dict]:
    return [
        {
            "scene_id": scene.scene_id, "sentence_index": i, "text": s.text,
            "grounding_required": s.grounding_required, "grounding_refs": s.grounding_refs,
        }
        for i, s in enumerate(scene.sentences)
    ]


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status}


def verify_grounding(
    narration: list[SceneNarration], claims: list[Claim], review_lead: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    payload = {
        "sentences": [s for scene in narration for s in _sentence_payload(scene)],
        "verified_claims": [_claim_payload(c) for c in claims],
    }
    review = review_lead.run(
        pass_id="C2b", mode="GROUND_NARRATION", task_prompt=TASK_PROMPT,
        payload=payload, schema=GroundingReview, budget=budget, estimated_usd=0.06, timeout_s=180,
    )
    return review.issues
