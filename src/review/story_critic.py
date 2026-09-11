"""C1 -- story critic (Review Lead / Gemini strong) (plan §5, §10, design doc §27-28).

Diagnoses only, never rewrites. Judges the narration against its RESOLVED
archetype -- and must actively challenge a foundation/framework resolution,
since both are the easy defaults an LLM reaches for even when the source
supports a causal shape (playbook: "Foundation Became the Lazy Default").
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import SourceUnit
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
   Re-test the source evidence yourself against the real `source_units`
   given below -- not just the plan's own self-description -- is there
   really no violated expectation (mystery), no problem->fix->new-problem
   chain (build), no real comparison (experiment), no equation the story is
   built around (derivation)? If any source unit is the author's own
   production notes, storyboard plan, or pacing outline, weigh it heavily --
   it is the author's own account of the intended structure, not something
   you have to infer. If ANY of those fits better than what was chosen,
   raise a `category: archetype`, `severity: critical` issue naming the
   better fit, the specific source evidence for it, and the specific scenes
   that show the mismatch -- this is the single most important thing to get
   right.

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

7. REPETITION. Does any concept get substantively re-explained after it
   was already taught earlier in the narration, without being a
   deliberately marked recap or compression? The viewer has continuous
   memory across the entire video -- a scene that re-derives something
   from scratch a second or third time (not just briefly referencing it
   to build on it) is a real defect, not stylistic reinforcement. Name the
   concept and every scene_id where it recurs. Use `category: repetition`.

8. PACING. Does the hook resolve its central tension quickly, or does the
   narration spend multiple scenes on setup/context before the first real
   mechanism or payoff begins? A viewer should understand the central
   problem within the hook itself, not several scenes later. Use
   `category: pacing`.

9. OVERCLAIM. Flag narration that states more certainty or mechanism than
   is actually justified by the source, regardless of the video's topic:
   - Hard-selection language describing a mechanism that is actually
     soft/weighted or probabilistic -- narrating a graded, weighted
     contribution as if it were a single discrete pick.
   - Claiming one single component or step fully causes or resolves an
     outcome that the source actually attributes to several components
     acting together -- narrating a partial contribution as if it were the
     entire explanation.
   - A detail specific to one particular architecture, algorithm,
     implementation, or system stated as if it were universal to every
     version of the underlying general idea.
   - A motivation or limitation claim overstated as an absolute
     ("X can only ever do one thing") where the source's actual claim is
     narrower or conditional.
   Use `category: clarity`.

Rate severity honestly: critical = the story doesn't work as this
archetype; major = a real story defect a viewer would notice; minor =
polish. Every issue needs a concrete `recommended_intent` (what must
change), never replacement prose.
"""


class StoryCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _scene_payload(scene: SceneNarration) -> dict:
    return {"scene_id": scene.scene_id, "text": " ".join(s.text for s in scene.sentences)}


def _source_unit_payload(unit: SourceUnit) -> dict:
    return {
        "id": unit.id, "heading": unit.heading, "text": unit.text,
        "equations": unit.equations, "callouts": unit.callouts,
        "code": unit.code, "numbers": unit.numbers,
    }


def critique_story(
    plan: StoryPlan, narration: list[SceneNarration], review_lead: Agent, budget: BudgetCounter,
    source_units: list[SourceUnit],
) -> list[CritiqueIssue]:
    payload = {
        "archetype": plan.archetype,
        "selection_reason": plan.selection_reason,
        "rejected_archetypes": plan.rejected_archetypes,
        "hook": plan.hook.model_dump(),
        "beats": [b.model_dump() for b in plan.beats],
        "ending": plan.ending.model_dump(),
        "narration": [_scene_payload(s) for s in narration],
        "source_units": [_source_unit_payload(u) for u in source_units],
    }
    critique = review_lead.run(
        pass_id="C1", mode="STORY_CRITIC", task_prompt=TASK_PROMPT,
        payload=payload, schema=StoryCritique, budget=budget, estimated_usd=0.08, timeout_s=180,
    )
    return critique.issues
