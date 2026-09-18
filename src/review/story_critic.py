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
   You are also given `scene_plan` -- the planner's own explicit intent per
   scene (`scene_function`, `must_not_repeat`, `new_concepts`). When a
   scene is tagged `scene_function=derivation` with a `must_not_repeat`
   concept, and the narration re-explains that exact concept from scratch
   anyway, this is a CONFIRMED plan violation, not a suspected one -- say
   so explicitly and treat it as at least `major` severity.

8b. RUNNING-EXAMPLE FIDELITY. You are given `running_example` -- the one
    concrete illustration the plan committed to reusing everywhere. If a
    scene's narration introduces different named entities/values for what
    is clearly meant to be the same underlying illustration (rather than
    reusing the locked example's own names/numbers), flag it under
    `category: repetition` -- this is a continuity break, not a stylistic
    choice, even though nothing about the sentence itself is factually
    wrong.

8. PACING. Does the hook resolve its central tension quickly, or does the
   narration spend multiple scenes on setup/context before the first real
   mechanism or payoff begins? A viewer should understand the central
   problem within the hook itself, not several scenes later. Use
   `category: pacing`.

9. MECHANISM SCOPE. `scene_plan` gives each scene's `mechanism_scope` --
   the recorded scope of any mechanism whose applicability is conditional
   rather than universal (e.g. a technique that only applies under one
   specific setup, not every version of the underlying idea). If a scene's
   narration states such a mechanism without its recorded condition (e.g.
   as if it applies unconditionally, when `mechanism_scope` says it only
   applies under a specific setup), that is a CONFIRMED overclaim, not a
   suspected one -- the plan's own record already settles it. Use
   `category: clarity`. This also runs in the OTHER direction: if an
   EARLIER scene establishes a mechanism as broad/unconditional (or under
   one setup), and a LATER scene narrates a MORE RESTRICTED or otherwise
   DIFFERENT version of that same mechanism (a stricter condition added, a
   condition silently dropped, an exception introduced) with no explicit
   transition marking the change of setup, that is the same class of
   confirmed contradiction, read across the two scenes' own
   `mechanism_scope` records, not judged from either scene alone -- missing
   this exact shape on a real run is what prompted spelling it out here.
   (Generic technical-overclaim language -- soft-vs-hard mechanism
   phrasing, single-component causality, architecture-specific-as-
   universal claims -- is C2b's job now, checked per sentence against each
   cited claim's own `scope`/`required_qualifiers`; this check is
   narrower, using only the plan's own `mechanism_scope` record.)

10. PROMISE / SCOPE. You are given `scope_contract` (the story's own committed
    `title_promise`, `central_question`, `must_cover`, `supporting`,
    `deferred`, `title_must_not_imply`) and `source_coverage` (A2's per-source-unit
    disposition, with a reason). Check, concretely:
    - TITLE_TOO_NARROW: does the chosen title (or its `promise`) actually
      narrow the story down to something in `title_must_not_imply`, or to
      only a fraction of `must_cover`, while the beats go on to cover the
      full committed scope? Name the specific gap between what the title
      promises and what the story actually delivers.
    - BEAT_OUT_OF_SCOPE: does any beat cover a topic that `scope_contract`
      never classified as `must_cover`/`supporting` at all -- content that
      crept in without ever being committed to?
    - IMPORTANT_SOURCE_CONTENT_DROPPED: does `source_coverage` mark a unit
      `MUST_COVER` or `SUPPORTING` with a genuinely weak `reason`, or mark
      something `DEFERRED`/`REDUNDANT` that the story's own `must_cover`
      list actually depends on to make sense?
    - SUPPORTING_BEAT_TOO_LONG: does a beat built from only `supporting`
      source units consume a disproportionate share of the runway compared
      to the beats actually paying off `must_cover`?
    Use `category: scope`, and name which of the four findings above
    applies in `problem` so it's unambiguous which check fired.

Rate severity honestly: critical = the story doesn't work as this
archetype; major = a real story defect a viewer would notice; minor =
polish. Every issue needs a concrete `recommended_intent` (what must
change), never replacement prose.
"""


class StoryCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _scene_payload(scene: SceneNarration) -> dict:
    return {"scene_id": scene.scene_id, "text": " ".join(s.text for s in scene.sentences)}


def _scene_plan_payload(scene) -> dict:
    return {
        "scene_id": scene.scene_id, "beat_id": scene.beat_id, "scene_function": scene.scene_function,
        "must_not_repeat": scene.must_not_repeat, "new_concepts": scene.new_concepts,
        "mechanism_scope": scene.mechanism_scope,
    }


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
        "title": plan.title.model_dump(),
        "hook": plan.hook.model_dump(),
        "beats": [b.model_dump() for b in plan.beats],
        "ending": plan.ending.model_dump(),
        "narration": [_scene_payload(s) for s in narration],
        "scene_plan": [_scene_plan_payload(s) for s in plan.scene_plan],
        "running_example": plan.running_example.model_dump(),
        "source_units": [_source_unit_payload(u) for u in source_units],
        "scope_contract": plan.scope_contract.model_dump(),
        "source_coverage": [d.model_dump() for d in plan.source_coverage],
    }
    critique = review_lead.run(
        pass_id="C1", mode="STORY_CRITIC", task_prompt=TASK_PROMPT,
        payload=payload, schema=StoryCritique, budget=budget, estimated_usd=0.08, timeout_s=180,
    )
    return critique.issues
