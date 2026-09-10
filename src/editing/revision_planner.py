"""A3 -- revision planner (Story Lead / GPT) (design doc §36, plan §15).

Decides WHAT must change and how much -- never writes replacement prose,
never touches a number directly. Structural (deterministic) findings and
critic (LLM) findings are both given as plain evidence; the routing
decision itself (story_replan_required, or a bounded set of targeted
rewrites) is this pass's judgement call, made once per revision cycle.
"""
from __future__ import annotations

from agents.base import Agent
from llm.budget import BudgetCounter
from planning.models import StoryPlan
from review.models import CritiqueIssue
from verification.hard.grounding import GroundingViolation
from verification.hard.structure import StructuralIssue

from .models import RevisionPlan

TASK_PROMPT = """\
Decide the MINIMUM necessary repair for this story plan and narration,
given the findings below. You decide WHAT changes; you never write
replacement prose, and you never alter a verified number.

Set `story_replan_required = true` only when the plan itself cannot be
fixed by rewriting scenes -- for example: the scene plan's total word
budget is far short of the target duration (rewriting existing scenes
cannot manufacture missing scenes), most of the source's content was never
covered by any beat, a required core archetype role is entirely absent, or
the critic raised a critical archetype-fit issue naming a better-supported
alternative. In every other case, prefer `rewrite_beats` (naming the
specific beats and the INTENT of the fix, never the prose itself),
`technical_fixes` (a specific correction tied to a claim id), or
`delete_or_compress` (a specific redundant scene) -- and list everything
that should be `preserve`d untouched.

List `preserve` generously: anything not directly implicated by a finding
should be explicitly preserved, not left ambiguous.
"""


def _structural_payload(issues: list[StructuralIssue]) -> list[dict]:
    return [{"code": i.code, "detail": i.detail} for i in issues]


def _grounding_payload(violations: list[GroundingViolation]) -> list[dict]:
    return [{"scene_id": v.scene_id, "code": v.code, "detail": v.detail} for v in violations]


def _critique_payload(issues: list[CritiqueIssue]) -> list[dict]:
    return [
        {"severity": i.severity, "category": i.category, "layer": i.layer,
         "scene_ids": i.scene_ids, "problem": i.problem, "recommended_intent": i.recommended_intent}
        for i in issues
    ]


def plan_revision(
    plan: StoryPlan,
    structural_issues: list[StructuralIssue],
    grounding_violations: list[GroundingViolation],
    critique_issues: list[CritiqueIssue],
    story_lead: Agent,
    budget: BudgetCounter,
) -> RevisionPlan:
    payload = {
        "archetype": plan.archetype,
        "beats": [{"beat_id": b.beat_id, "purpose": b.purpose} for b in plan.beats],
        "structural_issues": _structural_payload(structural_issues),
        "grounding_violations": _grounding_payload(grounding_violations),
        "critique_issues": _critique_payload(critique_issues),
    }
    return story_lead.run(
        pass_id="A3", mode="REVISION_PLANNER", task_prompt=TASK_PROMPT,
        payload=payload, schema=RevisionPlan, budget=budget, estimated_usd=0.05,
    )
