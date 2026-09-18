"""The V1A-S short run (plan §20.7).

2026-09-15: gained a bounded, single-attempt targeted-rewrite cycle (B2s), replacing the
pure single-pass design this module used to have. Built on real evidence, not ahead of it:
six live verification rounds kept finding two failure categories (`micro_arc`/naive-attempt,
`ending` repetition-or-recap) resurface in new shapes after each prompt-only fix closed the
previous shape -- the same signature that made the long-form loop outgrow pure prompting
early in this project (ERR-022 through ERR-026). This module's own docstring had pre-
committed to exactly this escalation ("added later if real runs show it's needed"); this is
that evidence. See `editing/short_targeted_rewrite.py` for why the mechanism itself is much
smaller than long-form's A3+B2 pair (no separate planner call, no plan-level fix, bounded to
one attempt).

Three agents cover the whole short run at flash/mini/subscription cost
(plan §20.7's ~$0.65-for-long-form-plus-3-shorts budget): `worker` (Haiku,
subscription) for C4s's cheap first pass, `narration_lead` (Sonnet,
subscription) for B1s (and now B2s), and one `review_agent` (Gemini flash,
paid) shared across CM, C1s, C2b, and C4s's escalation -- no strong tier
needed anywhere in a short run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agents.base import Agent
from editing.short_targeted_rewrite import apply_short_targeted_rewrite
from facts.models import Claim
from llm.budget import BudgetCounter
from narration.models import SceneNarration
from narration.short_generator import generate_short_narration
from planning.shorts_models import ShortPlan
from review.claim_mapper import map_claims
from review.cold_hook_critic import critique_cold_hook
from review.grounding_verifier import apply_grounding_metadata_repairs, grounding_verdicts_to_issues, verify_grounding
from review.models import CritiqueIssue, DiagnosticResult
from review.short_critic import critique_short
from verification.diagnostics.shorts import check_short_diagnostics
from verification.hard.grounding import GroundingViolation, check_grounding_policy, check_numeric_fidelity
from verification.hard.shorts import ShortHardIssue, check_short_structure

from .policy_gate import FinalStatus, apply_editorial_downgrade, compute_final_status

# Bounded to ONE attempt (2026-09-15) -- a short is cheap enough that a second full
# regeneration (a fresh SC/A2s/B1s cycle on the next run) is a better use of a persistent
# miss than an unbounded in-run loop; matches this module's own "don't build ahead of
# evidence" discipline, now applied to the size of the fix, not just whether to build one.
MAX_SHORT_REVISIONS = 1


@dataclass
class ShortsPipelineAgents:
    narration_lead: Agent  # Sonnet, subscription -- B1s
    worker: Agent  # Haiku, subscription -- C4s first pass
    review_agent: Agent  # Gemini flash, paid -- CM, C1s, C2b, C4s escalation


@dataclass
class ShortRunResult:
    plan: ShortPlan
    narration: list[SceneNarration]
    hard_failures: list[str]
    issues: list[CritiqueIssue]
    diagnostics: list[DiagnosticResult]
    final_status: FinalStatus
    log: list[str] = field(default_factory=list)
    preview_audio: bytes | None = None  # V1C: real TTS audio, when synthesis succeeded
    measured_duration_seconds: float | None = None
    degraded_capabilities: list[str] = field(default_factory=list)
    revisions_used: int = 0  # 0 or 1 (MAX_SHORT_REVISIONS) -- the bounded B2s rewrite cycle


def save_short_debug(result: ShortRunResult, index: int, run_dir: Path, short_html: str | None = None) -> None:
    """Always-written debug status for one short attempt (2026-09-15) -- unlike
    `final/shorts/<i>/` (only ever populated on promotion, matching the long-form side's
    own "final/ never holds a partial or failed artifact" rule), this small summary
    exists specifically so a FAILed short's own reasons are still inspectable after the
    run. Real gap found live: a short FAILed, `run_pipeline.py` logged only
    `final_status=FAIL` and a dollar figure to stdout, and nothing about WHY was ever
    written to disk -- once the process exited, the actual hard_failures/issues were
    gone for good. Mirrors `orchestration/pipeline.py::save_result`'s own always-written
    `final/status.json` for the long-form loop.

    `short_html` (2026-09-15, same day, second real gap found): `final/shorts/<i>/` is
    gated on the OVERALL run's combined status (the parent long-form result), not each
    short's own -- confirmed live that a short can individually PASS_WARN its own
    review with zero hard failures, yet never be written anywhere on disk simply
    because the unrelated parent long-form run FAILed. `plan`/`narration` are written
    here too (not just the html) so the short's actual title/spoken text is readable
    without a browser, same reasoning as saving status.json as JSON rather than
    forcing a re-render to see why something failed."""
    short_dir = run_dir / "shorts" / str(index)
    short_dir.mkdir(parents=True, exist_ok=True)
    (short_dir / "status.json").write_text(json.dumps({
        "final_status": result.final_status,
        "hard_failures": result.hard_failures,
        "issues": [i.model_dump() for i in result.issues],
        "diagnostics": [d.model_dump() for d in result.diagnostics],
        "revisions_used": result.revisions_used,
        "degraded_capabilities": result.degraded_capabilities,
        "log": result.log,
    }, indent=2))
    (short_dir / "plan.json").write_text(result.plan.model_dump_json(indent=2))
    (short_dir / "narration.json").write_text(
        json.dumps([n.model_dump() for n in result.narration], indent=2)
    )
    if short_html is not None:
        (short_dir / "short.html").write_text(short_html)


_SEGMENT_ORDER = ("hook", "setup", "mechanism", "payoff")


def _narration_script_text(narration: list[SceneNarration]) -> str:
    by_id = {n.scene_id: n for n in narration}
    return " ".join(
        " ".join(s.text for s in by_id[seg].sentences)
        for seg in _SEGMENT_ORDER if seg in by_id
    )


_GROUNDING_VIOLATION_INTENTS = {
    "ungrounded_factual_sentence": "cite a real supporting claim from the registry, or rewrite "
        "this as a non-factual transition if no claim actually supports it",
    "grounding_ref_unknown_claim": "replace the cited claim id with a real one from the claim "
        "registry that actually supports this sentence",
    "unverified_in_hook_or_ending": "replace this with a VERIFIED claim, or move this content "
        "out of the hook/payoff entirely -- an UNVERIFIED claim is never allowed there, hedge or not",
    "numeric_drift": "correct the stated number to match the cited claim's own figure, or cite "
        "a different claim that actually supports this number",
}


def _grounding_violation_to_issue(v: GroundingViolation) -> CritiqueIssue:
    """2026-09-16, found live (v10 verification run): a short FAILed with 4
    `ungrounded_factual_sentence` hard failures and `revisions_used=0` -- the targeted rewrite
    never even attempted a fix, because `GroundingViolation` (a plain dataclass: scene_id,
    sentence_index, code, detail) was never converted into the `CritiqueIssue` shape
    `critical_issues`/`apply_short_targeted_rewrite` actually key on. This module's own
    docstring had already flagged the gap ("extend once a live run actually shows one of
    these firing on a real short, not ahead of that evidence") -- this is that evidence.
    `grounding_policy_violation` (from `_claim_allows_narration`'s own reason string) has no
    dedicated entry in `_GROUNDING_VIOLATION_INTENTS` -- its own `detail` is already a
    specific, actionable explanation (e.g. "claim X is REJECTED and must never be narrated"),
    so it's used directly rather than duplicated into a second static sentence."""
    intent = _GROUNDING_VIOLATION_INTENTS.get(v.code, v.detail)
    return CritiqueIssue(
        issue_id=f"gp_{v.scene_id}_{v.sentence_index}_{v.code}", severity="critical",
        category="clarity", layer="TECHNICAL", scene_ids=[v.scene_id],
        problem=v.detail, why_it_matters=v.detail, recommended_intent=intent,
        repair_owner="narration_lead",
    )


_REWRITABLE_HARD_CODES = {"duration_estimate_exceeds_max", "measured_duration_exceeds_max"}


def _hard_issue_to_critique_issue(issue: ShortHardIssue, narration: list[SceneNarration]) -> CritiqueIssue | None:
    """PIPELINE_AUDIT_2026-09-17.md finding #4 (same shape as `_grounding_violation_to_issue`
    above, and the same shape as the already-fixed ERR-077): `check_short_structure`'s own
    `ShortHardIssue`s were never converted into the `CritiqueIssue` shape the B2s rewrite
    trigger actually keys on, so a short whose critics all passed cleanly but whose narration
    simply ran too long (`duration_estimate_exceeds_max`/`measured_duration_exceeds_max`)
    could never attempt a rewrite at all, despite `short_targeted_rewrite.py`'s own prompt
    explicitly covering "cut a clause to make room."

    Deliberately narrow: NOT every `ShortHardIssue` code is narration-fixable. `no_central_
    insight`, `title_hook_mismatch`, `title_payoff_mismatch`, and `missing_parent_reference`
    are all PLAN-level defects (the fix is a different title or a different plan, not
    different prose) -- converting those into a scene-targeted rewrite would misdirect the
    rewrite at content that isn't the actual problem, so they correctly stay hard failures
    with no rewrite path, exactly as before. `claim_outside_allowed_fact_set` already carries
    a scene_id (embedded in `detail`, "{scene_id} sentence {i} cites...") and is real content
    the narration can actually be changed to fix, so it's included too.

    The returned issue is used ONLY to decide whether/what to rewrite -- it is deliberately
    NOT added to the `critique_issues` list `_format_hard_failures` reads, since `hard`
    already contributes this exact failure to `hard_failures` once; adding it again here
    would double-print it."""
    if issue.code in _REWRITABLE_HARD_CODES:
        if not narration:
            return None
        longest = max(narration, key=lambda s: s.est_seconds)
        return CritiqueIssue(
            issue_id=f"hard_{issue.code}", severity="critical", category="pacing", layer="STORY",
            scene_ids=[longest.scene_id], problem=issue.detail, why_it_matters=issue.detail,
            recommended_intent="cut a less essential clause here to bring the short's total runtime under the cap",
            repair_owner="narration_lead",
        )
    if issue.code == "claim_outside_allowed_fact_set":
        scene_id = issue.detail.split(" ", 1)[0]
        return CritiqueIssue(
            issue_id=f"hard_{issue.code}_{scene_id}", severity="critical", category="clarity", layer="TECHNICAL",
            scene_ids=[scene_id], problem=issue.detail, why_it_matters=issue.detail,
            recommended_intent="remove or replace the out-of-scope claim citation with one from allowed_fact_ids",
            repair_owner="narration_lead",
        )
    return None  # a plan-level defect -- no scene a narration rewrite could fix


def _run_review(
    plan: ShortPlan, narration: list[SceneNarration], scoped_claims: list[Claim],
    agents: ShortsPipelineAgents, budget: BudgetCounter,
) -> tuple[list[SceneNarration], list[CritiqueIssue]]:
    """CM/C2b/C1s/C4s -- everything except the deterministic duration/structure checks,
    which depend on `measured_duration_seconds` and are run separately (once cheaply
    with the WPM estimate to decide whether a rewrite is worth attempting, once for
    real with the TTS measurement on whichever narration is final).

    2026-09-16: `check_grounding_policy`/`check_numeric_fidelity` now run here too --
    confirmed live as a real, undocumented gap: long-form's own `_run_review_block`
    (orchestration/pipeline.py) has always run both (a deterministic "grounding_required
    but no grounding_refs at all" check, and a numeric-drift check against the cited
    claim), but shorts never called either -- `verification/hard/shorts.py`'s own module
    docstring lists exactly which long-form gates are deliberately switched off for
    shorts, and these two were never in that list. A short's own CM/C2b metadata could
    be internally inconsistent, or a narrated number could drift from its cited claim,
    with nothing in the shorts pipeline positioned to catch either.

    2026-09-16, found on a further review round: `check_grounding_policy`'s own
    `hook_scene_ids`/`ending_scene_ids` params (its "UNVERIFIED never in the hook /
    ... / the ending" rule, this module's own docstring) were left at their empty
    defaults, silently disabling that rule entirely -- confirmed the exact same gap
    exists in BOTH of long-form's own call sites (`orchestration/pipeline.py`), so
    this was never actually a shorts-specific oversight, just inherited unfixed when
    the rest of this check was wired in above. Unlike long-form (dynamic beat/scene
    ids need real identification logic -- out of scope for this pass), a short's
    segments are always exactly {hook, setup, mechanism, payoff}, so wiring this
    correctly here costs nothing and carries no ambiguity.

    2026-09-16, found live (v10 run): `GroundingViolation`s are now converted into
    `CritiqueIssue`s (severity="critical") and folded into the returned list, rather than
    kept as a separate, rewrite-invisible return value -- see
    `_grounding_violation_to_issue`'s own docstring for the live evidence."""
    narration = map_claims(narration, scoped_claims, agents.review_agent, budget)
    c2b_verdicts = verify_grounding(narration, scoped_claims, agents.review_agent, budget)
    narration = apply_grounding_metadata_repairs(narration, c2b_verdicts)
    grounding_issues = grounding_verdicts_to_issues(narration, c2b_verdicts)
    grounding_violations = check_grounding_policy(
        narration, scoped_claims, hook_scene_ids={"hook"}, ending_scene_ids={"payoff"},
    ) + check_numeric_fidelity(narration, scoped_claims)
    grounding_violation_issues = [_grounding_violation_to_issue(v) for v in grounding_violations]
    story_issues = critique_short(plan.micro_arc, narration, agents.review_agent, budget, bridge_mode=plan.bridge.mode)

    hook_scene = next((s for s in narration if s.scene_id == "hook"), None)
    hook_text = " ".join(s.text for s in hook_scene.sentences) if hook_scene else ""
    cold_hook_issues = critique_cold_hook(
        plan.title, hook_text, plan.hook.visual or "", agents.worker, agents.review_agent, budget,
    )
    return narration, grounding_violation_issues + grounding_issues + story_issues + cold_hook_issues


def _format_hard_failures(hard: list[ShortHardIssue], critique_issues: list[CritiqueIssue]) -> list[str]:
    hard_failures = [f"{i.code}: {i.detail}" for i in hard]
    hard_failures += [
        f"critical/{i.category} ({i.layer}) [{i.issue_id}]: {i.problem}"
        for i in critique_issues if i.severity == "critical"
    ]
    return hard_failures


def _major_issue_count(critique_issues: list[CritiqueIssue]) -> int:
    """2026-09-17: parity fix for orchestration/pipeline.py's own `_major_issue_count`
    (Phase 27 item 3) -- shorts use the identical CritiqueIssue.severity taxonomy
    (review/models.py) and review/short_critic.py's own prompt explicitly instructs
    "major = a real defect a viewer would notice," so a short can accrue uncorrected
    major issues the same way long-form can, but `run_short`'s terminal log carried zero
    visibility into that. Measurement only, same as long-form's -- never wired into
    `compute_final_status`."""
    return sum(1 for i in critique_issues if i.severity == "major")


def _badness(hard_failures: list[str], critique_issues: list[CritiqueIssue]) -> tuple[int, int]:
    """Lower is better, compared lexicographically -- fewer hard failures dominates (a
    rewrite that clears one hard failure but adds a minor issue is still real progress),
    same reasoning as orchestration/pipeline.py's own `_badness`, deliberately simpler
    (no severity/diagnostic-band breakdown) since shorts have no evidence yet that finer
    grading is needed."""
    return (len(hard_failures), len(critique_issues))


def run_short(
    plan: ShortPlan, claims: list[Claim], agents: ShortsPipelineAgents, budget: BudgetCounter,
    require_parent: bool = True, enable_tts_preview: bool = True,
) -> ShortRunResult:
    log: list[str] = []

    # Scoped to allowed_fact_ids BEFORE it ever reaches a model -- CM/C2b
    # must not even have the OPTION to ground a sentence to a claim outside
    # a derived short's verified fact set (plan §9 Factual gate, §20.7).
    # A real gap found live (2026-09-10): CM given the full registry
    # correctly-per-its-own-job picked a real, well-supported claim that
    # simply happened to sit outside this short's scope -- caught by
    # check_grounding_scope after the fact, but better prevented up front.
    allowed_ids = set(plan.parent.allowed_fact_ids) if plan.parent else {c.claim_id for c in claims}
    scoped_claims = [c for c in claims if c.claim_id in allowed_ids]

    narration = generate_short_narration(plan, claims, agents.narration_lead)
    log.append(f"B1s: {len(narration)} segments narrated")

    narration, critique_issues = _run_review(plan, narration, scoped_claims, agents, budget)
    # measured_duration_seconds=None here -- the cheap WPM estimate, not a real TTS call,
    # decides whether a rewrite is worth attempting; TTS runs once, for real, at the end.
    hard = check_short_structure(plan, narration, require_parent=require_parent, measured_duration_seconds=None)
    hard_failures = _format_hard_failures(hard, critique_issues)
    log.append(f"review: {len(hard_failures)} hard failures, {len(critique_issues)} issues")

    # STORY_IMPROVEMENT_PLAN.md Phase 20 (2026-09-15): a single bounded targeted-rewrite
    # attempt, built on six live rounds of evidence that prompt-only fixes for
    # micro_arc/ending-quality issues kept resurfacing in new shapes (see
    # editing/short_targeted_rewrite.py's own module docstring for the full reasoning).
    # 2026-09-16: now also covers grounding-policy/numeric-fidelity defects, folded into
    # `critique_issues` by `_run_review` as real critical CritiqueIssues (see
    # `_grounding_violation_to_issue`) -- previously invisible to this rewrite entirely.
    revisions_used = 0
    # PIPELINE_AUDIT_2026-09-17.md finding #4: rewritable structural hard failures (a
    # duration overrun, an out-of-scope claim citation) now reach the rewrite trigger too --
    # see `_hard_issue_to_critique_issue`'s own docstring. Kept OUT of `critique_issues`
    # itself (only added to this local list) so `_format_hard_failures` never double-counts
    # them -- `hard_failures` above already reports each one once, from `hard` directly.
    rewritable_hard_issues = [
        ci for h in hard if (ci := _hard_issue_to_critique_issue(h, narration)) is not None
    ]
    critical_issues = [i for i in critique_issues if i.severity == "critical"] + rewritable_hard_issues
    if critical_issues and revisions_used < MAX_SHORT_REVISIONS:
        rewritten = apply_short_targeted_rewrite(plan, narration, scoped_claims, critical_issues, agents.narration_lead)
        if rewritten is not narration:  # apply_short_targeted_rewrite returns the SAME
            # object, unmodified, when no critique issue named an actionable scene_id --
            # this identity check is how we tell "nothing to rewrite" from "rewrote it".
            revisions_used += 1
            new_narration, new_critique_issues = _run_review(
                plan, rewritten, scoped_claims, agents, budget,
            )
            new_hard = check_short_structure(
                plan, new_narration, require_parent=require_parent, measured_duration_seconds=None,
            )
            new_hard_failures = _format_hard_failures(new_hard, new_critique_issues)
            log.append(
                f"targeted rewrite #{revisions_used}: review: {len(new_hard_failures)} hard failures, "
                f"{len(new_critique_issues)} issues"
            )
            if _badness(new_hard_failures, new_critique_issues) <= _badness(hard_failures, critique_issues):
                narration, critique_issues, hard_failures = new_narration, new_critique_issues, new_hard_failures
                log.append("targeted rewrite kept (not worse)")
            else:
                log.append("targeted rewrite made things worse -- reverted to the pre-rewrite version")

    # V1C: a real TTS measurement replaces the WPM estimate for the duration gate, run
    # once against whichever narration (original or rewritten) is now current. Never
    # crashes the run if unavailable -- a genuinely missing capability degrades visibly
    # (plan §14) and falls back to the estimate, it does not fail the whole short.
    preview_audio: bytes | None = None
    measured_duration_seconds: float | None = None
    degraded_capabilities: list[str] = []
    if enable_tts_preview:
        try:
            from voice.tts_preview import synthesize_narration_preview

            preview = synthesize_narration_preview(_narration_script_text(narration))
            preview_audio = preview.audio_bytes
            measured_duration_seconds = preview.measured_duration_seconds
            log.append(f"TTS preview: measured {measured_duration_seconds:.1f}s")
        except ImportError:
            degraded_capabilities.append("tts_preview: edge-tts not installed")
            log.append("TTS preview: degraded (edge-tts not installed)")
        except Exception as e:  # noqa: BLE001 -- a real network/service failure must degrade, never crash the run
            degraded_capabilities.append(f"tts_preview: synthesis failed ({e})")
            log.append(f"TTS preview: degraded (synthesis failed: {e})")

    hard = check_short_structure(
        plan, narration, require_parent=require_parent, measured_duration_seconds=measured_duration_seconds,
    )
    hard_failures = _format_hard_failures(hard, critique_issues)
    diagnostics = check_short_diagnostics(plan, narration)
    log.append(f"final review: {len(hard_failures)} hard failures, {len(critique_issues)} issues")

    status = compute_final_status(hard_failures=hard_failures, diagnostics=diagnostics, revision_budget_remaining=False)
    if degraded_capabilities:
        status = apply_editorial_downgrade(status, "PASS_WARN")
    log.append(f"final status: {status} ({_major_issue_count(critique_issues)} major issue(s) uncorrected)")

    return ShortRunResult(
        plan=plan, narration=narration, hard_failures=hard_failures,
        issues=critique_issues, diagnostics=diagnostics, final_status=status, log=log,
        preview_audio=preview_audio, measured_duration_seconds=measured_duration_seconds,
        degraded_capabilities=degraded_capabilities, revisions_used=revisions_used,
    )
