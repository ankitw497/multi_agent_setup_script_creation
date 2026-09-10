"""The V1A orchestrator (plan §8, §14, §15). Deterministic control flow --
no model chooses the next stage. This wires: A2 -> B1 -> [CM, C1, C2b,
structural checks] -> aggregate -> policy gate -> (A3 -> route -> replan
or targeted rewrite, bounded) -> final policy gate -> emit.

Story understanding (A1) and everything upstream of it (S0-C2a) are
treated as already-produced inputs here -- they're validated independently
elsewhere; this module's job is the story-and-narration loop, which is
where the bounded revision cycle actually lives.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agents.base import Agent
from editing.revision_planner import plan_revision
from facts.models import AssumptionLedger, Claim
from llm.budget import BudgetCounter
from narration.generator import generate_narration
from narration.models import SceneNarration
from planning.models import SourceBrief, StoryPlan
from planning.story_planner import plan_story
from review.aggregator import aggregate_review
from review.claim_mapper import map_claims
from review.grounding_verifier import verify_grounding
from review.models import ReviewBundle
from review.story_critic import critique_story
from verification.hard.grounding import check_grounding_policy
from verification.hard.structure import check_structure

from .policy_gate import FinalStatus, compute_final_status
from .routing import RevisionAction, decide_action

MAX_STORY_REPLANS = 1
MAX_MAJOR_REVISIONS = 2


@dataclass
class PipelineAgents:
    story_lead: Agent
    narration_lead: Agent
    review_lead: Agent  # strong tier: C1, C2b -- correctness-critical, no cheap tier (plan §2.2)
    cm_agent: Agent  # flash tier: CM is mechanical/cheap by design (plan §2.2)


@dataclass
class PipelineResult:
    plan: StoryPlan
    narration: list[SceneNarration]
    review_bundle: ReviewBundle
    final_status: FinalStatus
    story_replans_used: int = 0
    major_revisions_used: int = 0
    log: list[str] = field(default_factory=list)


def _run_review_block(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    all_source_unit_ids: list[str], target_duration_seconds: float,
    agents: PipelineAgents, budget: BudgetCounter,
) -> tuple[list[SceneNarration], ReviewBundle]:
    structural = check_structure(plan, target_duration_seconds, all_source_unit_ids)

    narration = map_claims(narration, claims, agents.cm_agent, budget)
    grounding_violations = check_grounding_policy(narration, claims)
    grounding_issues = verify_grounding(narration, claims, agents.review_lead, budget)
    story_issues = critique_story(plan, narration, agents.review_lead, budget)

    bundle = aggregate_review(
        run_id="pipeline",
        structural_issues=structural,
        grounding_violations=grounding_violations,
        critique_issues=grounding_issues + story_issues,
        diagnostics=[],  # voice/visual/retention/learning diagnostics: V1C/V1D, not yet built
    )
    return narration, bundle


def run_story_and_narration_loop(
    source_brief: SourceBrief,
    claims: list[Claim],
    ledger: AssumptionLedger,
    all_source_unit_ids: list[str],
    target_duration_seconds: float,
    agents: PipelineAgents,
    budget: BudgetCounter,
    initial_plan: StoryPlan | None = None,
    archetype_override: str | None = None,
) -> PipelineResult:
    """The bounded loop. `initial_plan` lets a caller reuse an already-produced
    A2 result (e.g. for cost-free re-testing) instead of always calling A2 fresh."""
    log: list[str] = []
    story_replans_used = 0
    major_revisions_used = 0

    plan = initial_plan or plan_story(
        source_brief, claims, ledger, agents.story_lead, budget,
        target_duration_seconds, archetype_override,
    )
    log.append(f"A2: archetype={plan.archetype}, beats={len(plan.beats)}, scenes={len(plan.scene_plan)}")

    narration = generate_narration(plan, claims, agents.narration_lead)
    log.append(f"B1: {len(narration)} scenes narrated")

    while True:
        narration, bundle = _run_review_block(
            plan, narration, claims, all_source_unit_ids, target_duration_seconds, agents, budget,
        )
        log.append(f"review: {len(bundle.hard_failures)} hard failures, {len(bundle.issues)} issues")

        replan_budget_remaining = story_replans_used < MAX_STORY_REPLANS
        revision_budget_remaining = major_revisions_used < MAX_MAJOR_REVISIONS
        any_budget_remaining = replan_budget_remaining or revision_budget_remaining

        status = compute_final_status(
            hard_failures=bundle.hard_failures, diagnostics=bundle.diagnostics,
            revision_budget_remaining=any_budget_remaining,
        )

        if status not in ("REVISE",):
            log.append(f"final status: {status}")
            return PipelineResult(plan, narration, bundle, status, story_replans_used, major_revisions_used, log)

        # status == REVISE: ask A3 what to do about it.
        structural = check_structure(plan, target_duration_seconds, all_source_unit_ids)
        grounding_violations = check_grounding_policy(narration, claims)
        revision_plan = plan_revision(
            plan, structural, grounding_violations, bundle.issues, agents.story_lead, budget,
        )
        action = decide_action(revision_plan)
        log.append(f"A3: action={action.value}")

        if action == RevisionAction.REPLAN:
            if not replan_budget_remaining:
                log.append("replan budget exhausted -> FAIL")
                return PipelineResult(plan, narration, bundle, "FAIL", story_replans_used, major_revisions_used, log)
            story_replans_used += 1
            plan = plan_story(
                source_brief, claims, ledger, agents.story_lead, budget,
                target_duration_seconds, archetype_override,
            )
            narration = generate_narration(plan, claims, agents.narration_lead)
            log.append(f"A2 replan #{story_replans_used}: archetype={plan.archetype}")
            continue

        if action == RevisionAction.TARGETED_REWRITE:
            if not revision_budget_remaining:
                log.append("revision budget exhausted -> emit best candidate")
                final = compute_final_status(bundle.hard_failures, bundle.diagnostics, revision_budget_remaining=False)
                return PipelineResult(plan, narration, bundle, final, story_replans_used, major_revisions_used, log)
            major_revisions_used += 1
            # B2 targeted rewrite is not yet implemented (V1A scope note) --
            # the loop still re-verifies so the exhaustion path is real and testable.
            log.append(f"targeted rewrite #{major_revisions_used} requested (B2 not yet implemented)")
            continue

        # action == NONE but status was REVISE (diagnostics-only escalation, no
        # structural/grounding fix available) -- nothing more this loop can do.
        log.append("no revision action available for a diagnostics-only escalation -> emit best candidate")
        final = compute_final_status(bundle.hard_failures, bundle.diagnostics, revision_budget_remaining=False)
        return PipelineResult(plan, narration, bundle, final, story_replans_used, major_revisions_used, log)


def save_result(result: PipelineResult, run_dir: Path) -> None:
    (run_dir / "planning" / "plan.json").write_text(result.plan.model_dump_json(indent=2))
    (run_dir / "drafts" / "narration_final.json").write_text(
        json.dumps([n.model_dump() for n in result.narration], indent=2)
    )
    (run_dir / "reviews" / "review_bundle.json").write_text(result.review_bundle.model_dump_json(indent=2))
    (run_dir / "final" / "status.json").write_text(json.dumps({
        "final_status": result.final_status,
        "story_replans_used": result.story_replans_used,
        "major_revisions_used": result.major_revisions_used,
        "log": result.log,
    }, indent=2))
