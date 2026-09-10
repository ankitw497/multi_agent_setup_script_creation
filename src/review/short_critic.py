"""C1s -- micro-arc critic (flash-tier Gemini) (plan §20.7).

The short-format analogue of C1: judges the narration against its chosen
MICRO-ARC (not an archetype -- shorts have no archetype, plan §20.3), and
against the shape §20.4 requires (hook in 0-3s, one mechanism, a real
central payoff, no reserved outro). Diagnoses only, never rewrites.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter
from narration.models import SceneNarration

from .models import CritiqueIssue

TASK_PROMPT = """\
Judge this short's narration against its chosen micro-arc and the
short-format shape (plan §20.3-§20.4) -- not against long-form story
rules, which do not apply here.

Check, in order:

1. MICRO-ARC FIT. Does the narration actually follow the shape its
   micro_arc implies (e.g. contradiction_resolution needs a real
   contradiction before the resolution; problem_fix needs a real naive
   attempt before the fix; mini_derivation needs one real step, not a
   restated goal)? If the narration doesn't actually enact its own
   micro_arc, raise a `category: micro_arc` issue naming what's missing.

2. ONE MECHANISM. Is exactly one mechanism explained, or does the
   `mechanism` segment tour more than one? A short has no room for a tour.

3. NO RESERVED OUTRO. Does the ending stop at the payoff (or a short
   bridge line), or does it drift into a recap, a takeaway paragraph, or a
   generic subscribe ask? Shorts have no narrative room for any of that --
   flag it if present.

4. HOOK DELIVERS. Does the `hook` segment's narration actually create the
   tension the plan's hook event describes, or does it explain instead of
   creating the moment?

5. SELF-CONTAINED. Does anything in the narration require knowledge from
   outside this short's own setup/mechanism to make sense?

Rate severity honestly: critical = the short doesn't work as this
micro-arc or violates the no-reserved-outro rule; major = a real defect a
viewer would notice; minor = polish. Every issue needs a concrete
`recommended_intent`, never replacement prose.
"""


class ShortCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _segment_payload(scene: SceneNarration) -> dict:
    return {"segment": scene.scene_id, "text": " ".join(s.text for s in scene.sentences)}


def critique_short(
    micro_arc: str, narration: list[SceneNarration], review_agent: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    payload = {"micro_arc": micro_arc, "narration": [_segment_payload(s) for s in narration]}
    critique = review_agent.run(
        pass_id="C1s", mode="SHORT_CRITIC", task_prompt=TASK_PROMPT,
        payload=payload, schema=ShortCritique, budget=budget, estimated_usd=0.02, timeout_s=120,
    )
    return critique.issues
