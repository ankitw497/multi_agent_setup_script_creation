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
from editing.models import RevisionPlan
from editing.revision_planner import plan_revision
from editing.targeted_rewrite import apply_targeted_rewrite
from facts.models import AssumptionLedger, Claim, SourceUnit
from llm.budget import BudgetCounter
from narration.generator import generate_narration
from narration.models import SceneNarration
from planning.archetypes import ALL_ARCHETYPES
from planning.models import ReplanFeedback, SourceBrief, StoryPlan
from planning.story_planner import plan_story
from review.aggregator import aggregate_review
from review.claim_mapper import map_claims
from review.cold_hook_critic import critique_cold_hook
from review.grounding_verifier import verify_grounding
from review.models import CritiqueIssue, ReviewBundle
from review.story_critic import critique_story
from review.style_critic import critique_style
from verification.diagnostics.cta import check_cta_position
from verification.diagnostics.pacing import check_hook_tension_pacing
from verification.diagnostics.retention import check_novelty_coverage, check_retention
from verification.diagnostics.voice import check_voice
from verification.hard.grounding import check_grounding_policy, check_numeric_fidelity
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
    worker: Agent  # Haiku, subscription/free -- first tier of the C4a/C4s cold-hook cascade


@dataclass
class PipelineResult:
    plan: StoryPlan
    narration: list[SceneNarration]
    review_bundle: ReviewBundle
    final_status: FinalStatus
    story_replans_used: int = 0
    major_revisions_used: int = 0
    log: list[str] = field(default_factory=list)


def _hook_context(plan: StoryPlan, narration: list[SceneNarration]) -> tuple[str, str]:
    """(hook_narration_text, hook_visual_description) from the plan's first
    beat's own scenes -- the first-positioned beat IS the opening by
    construction (same reasoning as `verification/diagnostics/pacing.py`'s
    first-beat fallback), so this doesn't depend on `narrative_beat="hook"`
    being tagged accurately."""
    if not plan.beats:
        return "", ""
    first_beat_id = plan.beats[0].beat_id
    hook_scene_ids = {s.scene_id for s in plan.scene_plan if s.beat_id == first_beat_id}
    hook_narration = " ".join(
        s.text for scene in narration if scene.scene_id in hook_scene_ids for s in scene.sentences
    )
    hook_visual = next(
        (s.visual_description for s in plan.scene_plan if s.beat_id == first_beat_id and s.visual_description),
        "",
    )
    return hook_narration, hook_visual


def _run_review_block(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    all_source_unit_ids: list[str], target_duration_seconds: float,
    agents: PipelineAgents, budget: BudgetCounter, source_units: list[SourceUnit],
    source_brief: SourceBrief,
) -> tuple[list[SceneNarration], ReviewBundle]:
    structural = check_structure(plan, target_duration_seconds, all_source_unit_ids, source_brief)

    narration = map_claims(narration, claims, agents.cm_agent, budget)
    grounding_violations = check_grounding_policy(narration, claims) + check_numeric_fidelity(narration, claims)
    grounding_issues = verify_grounding(narration, claims, agents.review_lead, budget)
    story_issues = critique_story(plan, narration, agents.review_lead, budget, source_units)

    # C4 cold-hook critic (plan §8/§20.7): built for shorts only until now
    # (STORY_IMPROVEMENT_PLAN.md Phase 8.2) -- long-form's hook got no
    # independent "would a real viewer actually keep watching" critique at
    # all. Reuses the exact same Haiku->Gemini-flash cascade shorts already
    # use; C4a/C4b pass-id labels (not C4s) match this project's own
    # long-form naming for the cold-viewer tiers (plan §8).
    hook_narration, hook_visual = _hook_context(plan, narration)
    cold_hook_issues = critique_cold_hook(
        plan.title.chosen, hook_narration, hook_visual, agents.worker, agents.review_lead, budget,
        haiku_pass_id="C4a", gemini_pass_id="C4b",
    )

    diagnostics = check_retention(plan) + [
        check_cta_position(plan), check_hook_tension_pacing(plan), check_novelty_coverage(plan, source_brief),
    ]
    voice_diagnostic = check_voice(narration)
    diagnostics.append(voice_diagnostic)

    style_issues: list = []
    if voice_diagnostic.band in ("AMBER", "RED"):
        # C5 (plan §8): only invoked when voice signals something -- a clean
        # voice diagnostic costs nothing. Shares the flash-tier cm_agent
        # (Gemini flash), same reuse pattern as review_lead serving C1+C2b.
        style_issues = critique_style(narration, agents.cm_agent, budget)

    bundle = aggregate_review(
        run_id="pipeline",
        structural_issues=structural,
        grounding_violations=grounding_violations,
        critique_issues=grounding_issues + story_issues + cold_hook_issues + style_issues,
        diagnostics=diagnostics,
    )
    return narration, bundle


def _legitimately_dismissed_issue_ids(
    revision_plan: RevisionPlan, issues: list[CritiqueIssue], plan: StoryPlan,
) -> set[str]:
    """ERR-025's fix: A3 may propose dismissing a critique issue, but
    whether that's actually honored is enforced HERE, in code, not left to
    the model's own say-so -- C1 is a different model family specifically
    for adversarial independence (Appendix G's "producer != validator"),
    so A3 (same family as A2) freely overruling it on its own judgement
    would make that independence decorative.

    A dismissal is only honored when: the issue is a `critical`/`archetype`
    finding, its `problem` text names a specific archetype, AND that
    archetype is already a key in `plan.rejected_archetypes` (i.e. A2's own
    reasoning already explicitly considered and gave a real reason to rule
    it out). This is a narrow, mechanical, imperfect proxy (word matching,
    not real semantic judgement) for "this isn't new evidence" -- any
    archetype named that ISN'T already in `rejected_archetypes` fails this
    check, so a genuinely novel critique can never be waved away this way.
    """
    issues_by_id = {i.issue_id: i for i in issues}
    considered = {a.lower() for a in plan.rejected_archetypes}
    legitimate: set[str] = set()
    for dismissed in revision_plan.dismissed_issues:
        issue = issues_by_id.get(dismissed.issue_id)
        if issue is None or issue.severity != "critical" or issue.category != "archetype":
            continue
        # Naming the CURRENT archetype is expected phrasing for a dispute
        # ("not a build arc") -- exclude it so only a proposed ALTERNATIVE
        # has to already be in rejected_archetypes to count as "not new".
        mentioned = {a for a in ALL_ARCHETYPES if a in issue.problem.lower()} - {plan.archetype}
        if mentioned and mentioned.issubset(considered):
            legitimate.add(dismissed.issue_id)
    return legitimate


def _remove_dismissed_hard_failures(hard_failures: list[str], dismissed_issue_ids: set[str]) -> list[str]:
    return [f for f in hard_failures if not any(f"[{iid}]" in f for iid in dismissed_issue_ids)]


def run_story_and_narration_loop(
    source_brief: SourceBrief,
    claims: list[Claim],
    ledger: AssumptionLedger,
    all_source_unit_ids: list[str],
    target_duration_seconds: float,
    agents: PipelineAgents,
    budget: BudgetCounter,
    source_units: list[SourceUnit] | None = None,
    initial_plan: StoryPlan | None = None,
    archetype_override: str | None = None,
) -> PipelineResult:
    """The bounded loop. `initial_plan` lets a caller reuse an already-produced
    A2 result (e.g. for cost-free re-testing) instead of always calling A2 fresh.
    `source_units` is the source's real content -- given to A2 and C1 directly
    (not just A1's SourceBrief summary) so the archetype call and its review
    can both be cross-checked against the actual material, including any
    author production notes (a real gap found 2026-09-10)."""
    log: list[str] = []
    story_replans_used = 0
    major_revisions_used = 0
    source_units = source_units or []

    plan = initial_plan or plan_story(
        source_brief, claims, ledger, agents.story_lead, budget,
        target_duration_seconds, source_units, archetype_override,
    )
    log.append(f"A2: archetype={plan.archetype}, beats={len(plan.beats)}, scenes={len(plan.scene_plan)}")

    narration = generate_narration(plan, claims, agents.narration_lead)
    log.append(f"B1: {len(narration)} scenes narrated")

    while True:
        narration, bundle = _run_review_block(
            plan, narration, claims, all_source_unit_ids, target_duration_seconds, agents, budget, source_units,
            source_brief,
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
        structural = check_structure(plan, target_duration_seconds, all_source_unit_ids, source_brief)
        grounding_violations = check_grounding_policy(narration, claims)
        revision_plan = plan_revision(
            plan, structural, grounding_violations, bundle.issues, agents.story_lead, budget,
        )

        if revision_plan.dismissed_issues:
            legitimate_ids = _legitimately_dismissed_issue_ids(revision_plan, bundle.issues, plan)
            rejected_ids = {d.issue_id for d in revision_plan.dismissed_issues} - legitimate_ids
            if rejected_ids:
                log.append(f"A3 tried to dismiss {len(rejected_ids)} issue(s) without adequate grounds -- ignored")
            if legitimate_ids:
                bundle = ReviewBundle(
                    run_id=bundle.run_id,
                    hard_failures=_remove_dismissed_hard_failures(bundle.hard_failures, legitimate_ids),
                    issues=bundle.issues, diagnostics=bundle.diagnostics,
                )
                log.append(
                    f"A3 dismissed {len(legitimate_ids)} critique issue(s) already ruled out "
                    "in the plan's own rejected_archetypes"
                )
                status = compute_final_status(
                    hard_failures=bundle.hard_failures, diagnostics=bundle.diagnostics,
                    revision_budget_remaining=any_budget_remaining,
                )
                if status not in ("REVISE",):
                    log.append(f"final status after dismissal: {status}")
                    return PipelineResult(
                        plan, narration, bundle, status, story_replans_used, major_revisions_used, log,
                    )

        action = decide_action(revision_plan)
        log.append(f"A3: action={action.value}")

        if action == RevisionAction.REPLAN:
            if not replan_budget_remaining:
                log.append("replan budget exhausted -> FAIL")
                return PipelineResult(plan, narration, bundle, "FAIL", story_replans_used, major_revisions_used, log)
            story_replans_used += 1
            feedback = ReplanFeedback(
                previous_archetype=plan.archetype,
                critique_issues=[
                    {"severity": i.severity, "category": i.category, "problem": i.problem,
                     "recommended_intent": i.recommended_intent}
                    for i in bundle.issues
                ],
                structural_issues=[{"code": i.code, "detail": i.detail} for i in structural],
            )
            plan = plan_story(
                source_brief, claims, ledger, agents.story_lead, budget,
                target_duration_seconds, source_units, archetype_override,
                replan_feedback=feedback,
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
            narration = apply_targeted_rewrite(plan, narration, claims, revision_plan, agents.narration_lead)
            log.append(
                f"targeted rewrite #{major_revisions_used}: {len(revision_plan.rewrite_beats)} beat(s), "
                f"{len(revision_plan.technical_fixes)} fix(es), {len(revision_plan.delete_or_compress)} delete/compress"
            )
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
