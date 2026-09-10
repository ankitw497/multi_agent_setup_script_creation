"""SC -- candidate finder (Worker/Haiku, subscription lane) (plan §20.6).

Runs only after the parent's plan is final. Mechanical: a cheap shortlist
of 3-5 plausible short candidates from the parent's beats/scenes -- the
actual SELECTION judgement (which of these make good shorts) is A2s's
job, cross-family, not this pass's. Haiku's part here is squarely inside
the Haiku rule: extract and shortlist, never decide.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from narration.models import SceneNarration
from planning.models import StoryPlan
from planning.shorts_models import ShortsCandidate

TASK_PROMPT = """\
From this finished long-form script, shortlist 3-5 plausible short-video
candidates -- a cheap first pass, not the final selection (that happens
later, with more judgement). For each candidate:

- `beat_ids`: the specific beat(s) it would be built from (usually 1, at
  most 2 adjacent ones).
- `insight`: the single central insight this candidate would teach --
  must be genuinely self-contained without the rest of the video.
- `hook_material`: the concrete moment, number, or contrast that could
  open it in the first 0-3 seconds.
- `micro_arc_suggestion`: your best guess at which micro-arc fits
  (contradiction_resolution / problem_fix / before_after /
  question_answer / prediction_explanation / myth_correction /
  mini_derivation) -- A2s may override this.
- `prerequisites`: anything a viewer would need to already know for this
  candidate to make sense on its own (keep this list short -- a long one
  means the candidate is a poor short).
- `visual_object`: the one concrete thing the short would visually center on.
- `bridge_question`: the larger question this candidate's payoff could
  naturally open onto, if any (for a BRIDGE-goal short later) -- empty if
  none.

Do not rank or score here -- just shortlist real, concrete candidates.
A candidate that needs the whole video's context to land is not a real
candidate; skip it rather than force one.
"""


class CandidateShortlist(BaseModel):
    candidates: list[ShortsCandidate] = Field(default_factory=list)


def _beat_payload(plan: StoryPlan) -> list[dict]:
    return [
        {"beat_id": b.beat_id, "purpose": b.purpose, "archetype_role": b.archetype_role,
         "learning_objective": b.learning_objective, "source_unit_ids": b.source_unit_ids}
        for b in plan.beats
    ]


def _scene_payload(narration: list[SceneNarration]) -> list[dict]:
    return [{"scene_id": s.scene_id, "text": " ".join(sent.text for sent in s.sentences)} for s in narration]


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "importance": claim.importance}


def find_candidates(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim], worker: Agent,
) -> list[ShortsCandidate]:
    payload = {
        "central_question": plan.central_question, "story_promise": plan.story_promise,
        "beats": _beat_payload(plan), "narration": _scene_payload(narration),
        "claims": [_claim_payload(c) for c in claims],
    }
    result = worker.run(
        pass_id="SC", mode="CANDIDATE_FINDER", task_prompt=TASK_PROMPT,
        payload=payload, schema=CandidateShortlist, timeout_s=300,
    )
    return result.candidates
