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
from collections import Counter
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
from verification.hard.text_overlap import DEFAULT_OVERLAP_THRESHOLD
from verification.hard.text_overlap import overlap as _text_overlap
from planning.models import ReplanFeedback, SourceBrief, StoryPlan
from planning.story_planner import plan_story
from review.aggregator import aggregate_review
from review.claim_mapper import map_claims
from review.cold_hook_critic import critique_cold_hook
from review.cold_viewer_critic import critique_cold_viewer, critique_continuing_viewer
from review.grounding_verifier import apply_grounding_metadata_repairs, grounding_verdicts_to_issues, verify_grounding
from review.models import CritiqueIssue, ReviewBundle
from review.story_critic import critique_story
from review.style_critic import critique_style
from verification.diagnostics.compactness import check_sentence_density
from verification.diagnostics.cta import check_cta_position
from verification.diagnostics.pacing import (
    check_beat_airtime_outliers, check_hook_tension_pacing, check_payoff_beat_ratio,
    check_recap_bloat, check_time_to_primary_payoff,
)
from verification.diagnostics.retention import check_novelty_coverage, check_retention, check_title_scope_coverage
from verification.diagnostics.voice import check_voice
from verification.hard.grounding import check_grounding_policy, check_numeric_fidelity
from verification.hard.structure import check_structure

from .policy_gate import FinalStatus, compute_final_status
from .routing import RevisionAction, decide_action

# MAX_STORY_REPLANS raised 1 -> 2 (2026-09-15): confirmed live -- a real run's ONE replan
# attempt also failed to fully fix a structural coverage gap (`required_source_unit_uncovered`
# can ONLY be fixed by a replan; targeted_rewrite only rewrites existing scenes, never adds
# one), and with no second chance the pipeline fell through to FAIL and still rendered/spent
# on H/HV and shorts for a video missing whole sections of its source (STORY_IMPROVEMENT_PLAN.md).
# One extra attempt doesn't guarantee success against a systematically bad A2, but it's a real,
# cheap second chance against what's likely ordinary LLM stochasticity, not a structural flaw
# in A2 itself (17/18 runs since this project's Sep-11 baseline had complete coverage on the
# very first plan).
MAX_STORY_REPLANS = 2
MAX_MAJOR_REVISIONS = 2


@dataclass
class PipelineAgents:
    story_lead: Agent
    narration_lead: Agent
    # strong tier: C1 (unconditional, plan §2.2) -- C2b's own unconditional-strong default was
    # replaced 2026-09-16 (STORY_IMPROVEMENT_PLAN.md Phase 22) with flash-first + escalate-on-
    # flag; `review_lead` is now C2b's ESCALATION partner, not its primary pass.
    review_lead: Agent
    cm_agent: Agent  # flash tier: CM is mechanical/cheap by design (plan §2.2); also C2b's new primary pass
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
    # C2b's dense per-sentence verdicts (STORY_IMPROVEMENT_PLAN.md Phase 10) run BEFORE the
    # deterministic grounding checks below, so a CM false negative C2b itself disproves
    # (apply_grounding_metadata_repairs) is corrected in the narration first -- not left to
    # trip check_grounding_policy as a false "ungrounded_factual_sentence" hard failure.
    #
    # 2026-09-16, STORY_IMPROVEMENT_PLAN.md Phase 22 (Gemini cost reduction, escalation-gate
    # step 1 of 6): flash (`cm_agent`) is now the primary pass over every sentence, escalating
    # only a flagged verdict (unsupported / qualifier dropped / scope broadened / a named
    # violation code -- see `_needs_escalation`) to the strong tier for a second opinion.
    # Confirmed live (this session's own cost audit) that C2b's unconditional strong-tier
    # default was 83% of all Gemini spend project-wide -- this keeps the strong tier as a real
    # second opinion on exactly the sentences that need one, never removing it outright.
    c2b_verdicts = verify_grounding(narration, claims, agents.cm_agent, budget, escalate_to=agents.review_lead)
    narration = apply_grounding_metadata_repairs(narration, c2b_verdicts)
    grounding_violations = check_grounding_policy(narration, claims) + check_numeric_fidelity(narration, claims)
    grounding_issues = grounding_verdicts_to_issues(narration, c2b_verdicts)
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

    # C4c mid-video cold viewer (STORY_IMPROVEMENT_PLAN.md Phase 8.2): C4a/
    # C4b only judge the OPENING -- nothing judged whether a viewer who just
    # landed partway through would still know why this is being discussed
    # and still want to keep watching. Sampled at a few evenly-spaced
    # mid-video scenes (never the first/last beat), same free-first cascade.
    narration_text_by_scene_id = {n.scene_id: " ".join(s.text for s in n.sentences) for n in narration}
    cold_viewer_issues = critique_cold_viewer(plan, narration_text_by_scene_id, agents.worker, agents.review_lead, budget)

    # C4d continuing viewer (STORY_IMPROVEMENT_PLAN.md Phase 13): alongside, never replacing,
    # C4c above -- a different, complementary question at the same checkpoints (does this
    # feel caused by what came before, given the viewer HAS been following continuously,
    # rather than pretending they just landed here).
    continuing_viewer_issues = critique_continuing_viewer(
        plan, narration_text_by_scene_id, agents.worker, agents.review_lead, budget,
    )

    diagnostics = check_retention(plan) + [
        check_cta_position(plan), check_hook_tension_pacing(plan), check_novelty_coverage(plan, source_brief),
        check_title_scope_coverage(plan),
        check_beat_airtime_outliers(plan, claims), check_time_to_primary_payoff(plan, target_duration_seconds),
        check_payoff_beat_ratio(plan), check_recap_bloat(plan),
    ]
    voice_diagnostic = check_voice(narration)
    diagnostics.append(voice_diagnostic)
    diagnostics.append(check_sentence_density(narration))

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
        critique_issues=(
            grounding_issues + story_issues + cold_hook_issues + cold_viewer_issues
            + continuing_viewer_issues + style_issues
        ),
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
    finding, its `problem` text names a specific archetype, that archetype
    is already a key in `plan.rejected_archetypes` (i.e. A2's own reasoning
    already explicitly considered and gave a real reason to rule it out),
    AND (STORY_IMPROVEMENT_PLAN.md Phase 13) A3's own dismissal `reason`
    substantively engages with what A2 actually said about it.

    This last condition is Phase 13's tightening of ERR-022/025's open
    question. The original version treated ANY critique naming an
    already-rejected archetype as automatically dismissable, with no check
    on whether A3's dismissal was a real engagement with A2's own
    reasoning or just a rubber stamp ("no new evidence") -- too blunt per
    the doc's own framing: a different, well-argued INTERPRETATION of the
    same cited evidence is a legitimate disagreement, not noise, and a
    crude archetype-name keyword match can't tell the two apart. The
    word-overlap check (same mechanism `verification/hard/text_overlap.py`
    already uses for the promise-chain gate) is still a mechanical proxy,
    not real semantic judgement -- but it now requires A3's `reason` to
    actually reference the substance of what A2 said, not just the
    archetype's name, before honoring a dismissal. A genuinely new
    alternative (never in `rejected_archetypes` at all) is still never
    dismissable this way, regardless of what A3's reason says.
    """
    issues_by_id = {i.issue_id: i for i in issues}
    rejection_reason_by_archetype = {a.lower(): reason for a, reason in plan.rejected_archetypes.items()}
    legitimate: set[str] = set()
    for dismissed in revision_plan.dismissed_issues:
        issue = issues_by_id.get(dismissed.issue_id)
        if issue is None or issue.severity != "critical" or issue.category != "archetype":
            continue
        # Naming the CURRENT archetype is expected phrasing for a dispute
        # ("not a build arc") -- exclude it so only a proposed ALTERNATIVE
        # has to already be in rejected_archetypes to count as "not new".
        mentioned = {a for a in ALL_ARCHETYPES if a in issue.problem.lower()} - {plan.archetype}
        if not mentioned or not mentioned.issubset(rejection_reason_by_archetype):
            continue
        if any(
            _text_overlap(dismissed.reason, rejection_reason_by_archetype[alt]) >= DEFAULT_OVERLAP_THRESHOLD
            for alt in mentioned
        ):
            legitimate.add(dismissed.issue_id)
    return legitimate


def _remove_dismissed_hard_failures(hard_failures: list[str], dismissed_issue_ids: set[str]) -> list[str]:
    return [f for f in hard_failures if not any(f"[{iid}]" in f for iid in dismissed_issue_ids)]


def _badness(bundle: ReviewBundle) -> tuple[int, int, int, int, int, int]:
    """Lower is better, compared lexicographically. Hard failures dominate the comparison
    (a rewrite that clears one hard failure but adds two minor issues is still real
    progress) -- STORY_IMPROVEMENT_PLAN.md Phase 8.5. Phase 13 extends the original bare
    (hard_failures, issue_count) pair with a full severity/diagnostic-band ordering: that
    pair already handled a critical-vs-minor tradeoff correctly (`aggregate_review` promotes
    every critical issue into `hard_failures` too), but couldn't tell a real improvement --
    3 major issues becoming 0 major + 5 minor -- from a regression, since a flat issue count
    reads 5 as worse than 3."""
    severity_counts = Counter(i.severity for i in bundle.issues)
    band_counts = Counter(d.band for d in bundle.diagnostics)
    return (
        len(bundle.hard_failures),
        severity_counts["critical"], severity_counts["major"], severity_counts["minor"],
        band_counts["RED"], band_counts["AMBER"],
    )


def _red_dimensions(bundle: ReviewBundle) -> set[str]:
    return {d.dimension for d in bundle.diagnostics if d.band == "RED"}


def _major_issue_count(bundle: ReviewBundle) -> int:
    """STORY_IMPROVEMENT_PLAN.md Phase 27 item 3: `compute_final_status` never reads
    `bundle.issues` at all -- confirmed by direct code read. A `major`-severity issue
    (repetition, pacing, anything C1/C5 find) can never force a fix on its own, no matter
    how many exist; it's recorded and the run passes clean regardless. Measurement only,
    matching this project's own "measure before gate" precedent (`check_bridge_selection_
    defaulted`, `check_payoff_beat_ratio`, etc.) -- NOT wired into the escalation policy
    itself. A real policy change (should N+ majors also force REVISE, mirroring the
    existing "3+ REDs" rule) is a genuine behavior/cost tradeoff that needs more evidence
    than one run's own count before deciding, not a number this function should act on."""
    return sum(1 for i in bundle.issues if i.severity == "major")


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

    # Set right before a TARGETED_REWRITE `continue` to the pre-rewrite
    # (narration, bundle) -- checked at the top of the next iteration so a
    # rewrite that made things strictly worse is reverted before it can
    # become the accepted state (STORY_IMPROVEMENT_PLAN.md Phase 8.5: the
    # loop used to accept whatever the last cycle produced, even when a
    # real run showed hard failures going UP across revision rounds).
    # Deliberately scoped to one rewrite cycle at a time, not across a
    # REPLAN -- a replan starts the plan over for a real structural
    # reason, so "reverting" to the pre-replan state would just
    # reintroduce the defect that motivated it.
    pending_rewrite_baseline: tuple[list[SceneNarration], ReviewBundle] | None = None
    # PIPELINE_AUDIT_2026-09-17.md finding #6: `compute_final_status`'s own `red_survived_
    # a_round` parameter (plan §10: "3+ REDs, OR a RED that survived a prior revision
    # round") was fully implemented but never populated from any real call site -- half the
    # documented escalation policy was dead in production. Design decision: "survived a
    # round" means the SAME diagnostic dimension was RED immediately before a
    # TARGETED_REWRITE attempt and is STILL RED once that attempt's review completes
    # (whether the rewrite was kept or reverted for being worse -- a reverted rewrite
    # trivially still carries the baseline's own REDs, which is the correct read: nothing
    # was actually fixed). Deliberately scoped to one rewrite cycle at a time, same
    # lifecycle as `pending_rewrite_baseline` right above -- a REPLAN starts the story over,
    # so a RED from before it is a different plan's problem, not a "survived" one.
    red_dimensions_before_rewrite: set[str] | None = None

    while True:
        narration, bundle = _run_review_block(
            plan, narration, claims, all_source_unit_ids, target_duration_seconds, agents, budget, source_units,
            source_brief,
        )
        log.append(f"review: {len(bundle.hard_failures)} hard failures, {len(bundle.issues)} issues")

        if pending_rewrite_baseline is not None:
            baseline_narration, baseline_bundle = pending_rewrite_baseline
            if _badness(bundle) > _badness(baseline_bundle):
                log.append(
                    f"targeted rewrite #{major_revisions_used} made things worse "
                    f"({len(bundle.hard_failures)} hard failures, {len(bundle.issues)} issues vs "
                    f"{len(baseline_bundle.hard_failures)}/{len(baseline_bundle.issues)} before) -- reverting"
                )
                narration, bundle = baseline_narration, baseline_bundle
            pending_rewrite_baseline = None

        survived = (red_dimensions_before_rewrite or set()) & _red_dimensions(bundle)
        red_survived_a_round = bool(survived)
        if red_survived_a_round:
            log.append(f"a RED diagnostic survived a targeted-rewrite round unchanged: {sorted(survived)}")
        red_dimensions_before_rewrite = None

        replan_budget_remaining = story_replans_used < MAX_STORY_REPLANS
        revision_budget_remaining = major_revisions_used < MAX_MAJOR_REVISIONS
        any_budget_remaining = replan_budget_remaining or revision_budget_remaining

        status = compute_final_status(
            hard_failures=bundle.hard_failures, diagnostics=bundle.diagnostics,
            revision_budget_remaining=any_budget_remaining, red_survived_a_round=red_survived_a_round,
        )

        if status not in ("REVISE",):
            log.append(f"final status: {status} ({_major_issue_count(bundle)} major issue(s) uncorrected)")
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
                    revision_budget_remaining=any_budget_remaining, red_survived_a_round=red_survived_a_round,
                )
                if status not in ("REVISE",):
                    log.append(f"final status after dismissal: {status} ({_major_issue_count(bundle)} major issue(s) uncorrected)")
                    return PipelineResult(
                        plan, narration, bundle, status, story_replans_used, major_revisions_used, log,
                    )

        action = decide_action(revision_plan)
        log.append(f"A3: action={action.value}")

        if action == RevisionAction.REPLAN:
            if not replan_budget_remaining:
                log.append(f"replan budget exhausted -> FAIL ({_major_issue_count(bundle)} major issue(s) uncorrected)")
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
            red_dimensions_before_rewrite = None  # a new plan -- any prior RED is a different plan's problem
            continue

        if action == RevisionAction.TARGETED_REWRITE:
            if not revision_budget_remaining:
                log.append(f"revision budget exhausted -> emit best candidate ({_major_issue_count(bundle)} major issue(s) uncorrected)")
                final = compute_final_status(
                    bundle.hard_failures, bundle.diagnostics, revision_budget_remaining=False,
                    red_survived_a_round=red_survived_a_round,
                )
                return PipelineResult(plan, narration, bundle, final, story_replans_used, major_revisions_used, log)
            major_revisions_used += 1
            pending_rewrite_baseline = (narration, bundle)
            red_dimensions_before_rewrite = _red_dimensions(bundle)
            narration = apply_targeted_rewrite(plan, narration, claims, revision_plan, agents.narration_lead)
            log.append(
                f"targeted rewrite #{major_revisions_used}: {len(revision_plan.rewrite_beats)} beat(s), "
                f"{len(revision_plan.rewrite_scenes)} scene(s), {len(revision_plan.technical_fixes)} fix(es), "
                f"{len(revision_plan.delete_or_compress)} delete/compress"
            )
            continue

        # action == NONE but status was REVISE (diagnostics-only escalation, no
        # structural/grounding fix available) -- nothing more this loop can do.
        log.append(f"no revision action available for a diagnostics-only escalation -> emit best candidate ({_major_issue_count(bundle)} major issue(s) uncorrected)")
        final = compute_final_status(
            bundle.hard_failures, bundle.diagnostics, revision_budget_remaining=False,
            red_survived_a_round=red_survived_a_round,
        )
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
