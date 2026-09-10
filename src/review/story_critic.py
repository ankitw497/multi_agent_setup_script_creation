"""C1 -- story critic (Review Lead / Gemini strong) (plan §5, §10, design doc §27-28).

Diagnoses only, never rewrites. Judges the narration against its RESOLVED
archetype -- and must actively challenge a foundation/framework resolution,
since both are the easy defaults an LLM reaches for even when the source
supports a causal shape (playbook: "Foundation Became the Lazy Default").
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter
from narration.models import SceneNarration
from planning.models import StoryPlan

from .models import CritiqueIssue

TASK_PROMPT = """\
You are reviewing a finished narration draft against its story plan. Do not
rewrite anything -- diagnose only, and describe what must change, never how
it should read.

Check, in order:

1. ARCHETYPE FIT. The plan resolved ONE archetype. Does the narration
   actually behave like it? If the resolved archetype is `foundation` or
   `framework`, be especially skeptical -- these are the easy defaults an
   LLM reaches for even when the source genuinely supports a causal shape.
   Re-test the source evidence yourself: is there really no violated
   expectation (mystery), no problem->fix->new-problem chain (build), no
   real comparison (experiment), no equation the story is built around
   (derivation)? If ANY of those fits better than what was chosen, raise a
   `category: archetype`, `severity: critical` issue naming the better fit
   and the specific scenes that show it -- this is the single most
   important thing to get right.

2. HOOK. Does it create a real knowledge gap, or does it announce a
   syllabus ("in this video we will cover...")? Does it reveal too much,
   killing the reason to keep watching?

3. CAUSAL FLOW. For every scene transition, is there an actual causal
   reason ("that creates a new problem", "which means") or just a topic
   switch ("next, let's look at...")? Flag every transition that is
   secretly just "because this is the next topic."

4. MINI-PAYOFFS. Does each major beat actually resolve a question with a
   real gain in understanding, or does it just restate the question?

5. COGNITIVE LOAD. How many concepts are open at once with no resolution?
   Is anything introduced before the problem that motivates it exists?

6. ENDING. Does it resolve the hook's specific promise? Is there an earned
   capstone, or does it just stop after covering the material?

Rate severity honestly: critical = the story doesn't work as this
archetype; major = a real story defect a viewer would notice; minor =
polish. Every issue needs a concrete `recommended_intent` (what must
change), never replacement prose.
"""


class StoryCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _scene_payload(scene: SceneNarration) -> dict:
    return {"scene_id": scene.scene_id, "text": " ".join(s.text for s in scene.sentences)}


def critique_story(
    plan: StoryPlan, narration: list[SceneNarration], review_lead: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    payload = {
        "archetype": plan.archetype,
        "selection_reason": plan.selection_reason,
        "rejected_archetypes": plan.rejected_archetypes,
        "hook": plan.hook.model_dump(),
        "beats": [b.model_dump() for b in plan.beats],
        "ending": plan.ending.model_dump(),
        "narration": [_scene_payload(s) for s in narration],
    }
    critique = review_lead.run(
        pass_id="C1", mode="STORY_CRITIC", task_prompt=TASK_PROMPT,
        payload=payload, schema=StoryCritique, budget=budget, estimated_usd=0.08, timeout_s=180,
    )
    return critique.issues
