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

BEFORE anything else, if any critique issue has `category: archetype`,
resolve it first using the procedure below -- do not treat "the critic
marked it critical" as sufficient on its own:

1. Look at what alternative archetype the issue actually names.
2. Check `rejected_archetypes`: did A2 already list that SAME alternative
   there, with a real, substantive reason (not a placeholder)?
3. If yes, AND the critique's `problem` text does not cite any concrete
   evidence beyond what that rejection reason already accounted for, this
   is a RE-RAISED objection, not new evidence. Put it in `dismissed_issues`
   with a `reason` that quotes or closely paraphrases the specific prior
   rejection it fails to add to. Do NOT also set `story_replan_required`
   for this same issue.
4. Only if the critique names an alternative NOT already in
   `rejected_archetypes`, or surfaces a concrete piece of evidence A2's own
   `source_evidence`/`selection_reason` never addressed, treat it as
   genuinely new and eligible to trigger a replan.

This check exists because A2 is required to give a real reason for
rejecting every other archetype on every plan -- so a critic re-arguing
for one of those five without adding anything new is expected noise, not
a finding. Getting this right matters more than any other decision here:
defaulting to "critical means replan" defeats the entire point of giving
you the plan's own reasoning to check it against.

For everything else, set `story_replan_required = true` only when the
plan itself cannot be fixed by rewriting scenes -- for example: the scene
plan's total word budget is far short of the target duration (rewriting
existing scenes cannot manufacture missing scenes), most of the source's
content was never covered by any beat, a required core archetype role is
entirely absent, or step 4 above found a genuinely new archetype dispute.
In every other case, choose the NARROWEST tool that actually covers the
finding -- do not reach for a bigger blast radius than the finding itself
names:
- `rewrite_scenes` (naming specific `scene_id`s and the INTENT of the fix,
  never the prose itself) -- the default choice for a critique issue that
  already names specific `scene_ids` (repetition, pacing, a bad
  transition, an overclaim). Most findings should end up here.
- `rewrite_beats` (naming the whole `beat_id`) -- ONLY when the problem
  genuinely spans every scene in that beat (e.g. the beat's entire causal
  arc needs restructuring, not just one or two sentences inside it). A
  finding naming 1-2 specific scenes is a `rewrite_scenes` case, not a
  `rewrite_beats` case, even if the scenes happen to sit in the same beat.
- `technical_fixes` (a specific correction tied to a claim id), or
  `delete_or_compress` (a specific redundant scene) -- unchanged.

List `preserve` generously: anything not directly implicated by a finding
should be explicitly preserved, not left ambiguous.
"""


def _structural_payload(issues: list[StructuralIssue]) -> list[dict]:
    return [{"code": i.code, "detail": i.detail} for i in issues]


def _grounding_payload(violations: list[GroundingViolation]) -> list[dict]:
    return [{"scene_id": v.scene_id, "code": v.code, "detail": v.detail} for v in violations]


def _critique_payload(issues: list[CritiqueIssue]) -> list[dict]:
    return [
        {"issue_id": i.issue_id, "severity": i.severity, "category": i.category, "layer": i.layer,
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
        "selection_reason": plan.selection_reason,
        "source_evidence": plan.source_evidence,
        "rejected_archetypes": plan.rejected_archetypes,
        "beats": [{"beat_id": b.beat_id, "purpose": b.purpose} for b in plan.beats],
        "structural_issues": _structural_payload(structural_issues),
        "grounding_violations": _grounding_payload(grounding_violations),
        "critique_issues": _critique_payload(critique_issues),
    }
    return story_lead.run(
        pass_id="A3", mode="REVISION_PLANNER", task_prompt=TASK_PROMPT,
        payload=payload, schema=RevisionPlan, budget=budget, estimated_usd=0.05,
    )
