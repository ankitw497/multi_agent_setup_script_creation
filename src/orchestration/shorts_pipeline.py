"""The V1A-S short run (plan §20.7). Single-pass by design.

Unlike the long-form loop, this does NOT include an A3/B2 revision cycle
-- V1A-S's own "done when" bar (plan §20: "a short derived from a
successful V1A output is grounded within the parent's fact set, has one
central insight, and its hook event lands <=3s") is achievable through one
clean pass; a failing run reports FAIL with specific reasons via the same
policy-gate discipline as long-form, rather than silently shipping. A
bounded rewrite loop for shorts can be added later if real runs show it's
needed -- the same way the long-form loop only grew a revision cycle after
real failures demonstrated one was necessary (plan §15 still lists
rewrite_beats/B4 as conditional, never built ahead of evidence).

Three agents cover the whole short run at flash/mini/subscription cost
(plan §20.7's ~$0.65-for-long-form-plus-3-shorts budget): `worker` (Haiku,
subscription) for C4s's cheap first pass, `narration_lead` (Sonnet,
subscription) for B1s, and one `review_agent` (Gemini flash, paid) shared
across CM, C1s, C2b, and C4s's escalation -- no strong tier needed
anywhere in a short run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from narration.models import SceneNarration
from narration.short_generator import generate_short_narration
from planning.shorts_models import ShortPlan
from review.claim_mapper import map_claims
from review.cold_hook_critic import critique_cold_hook
from review.grounding_verifier import verify_grounding
from review.models import CritiqueIssue, DiagnosticResult
from review.short_critic import critique_short
from verification.diagnostics.shorts import check_short_diagnostics
from verification.hard.shorts import check_short_structure

from .policy_gate import FinalStatus, apply_editorial_downgrade, compute_final_status


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


_SEGMENT_ORDER = ("hook", "setup", "mechanism", "payoff")


def _narration_script_text(narration: list[SceneNarration]) -> str:
    by_id = {n.scene_id: n for n in narration}
    return " ".join(
        " ".join(s.text for s in by_id[seg].sentences)
        for seg in _SEGMENT_ORDER if seg in by_id
    )


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

    narration = map_claims(narration, scoped_claims, agents.review_agent, budget)
    grounding_issues = verify_grounding(narration, scoped_claims, agents.review_agent, budget)
    story_issues = critique_short(plan.micro_arc, narration, agents.review_agent, budget)

    hook_scene = next((s for s in narration if s.scene_id == "hook"), None)
    hook_text = " ".join(s.text for s in hook_scene.sentences) if hook_scene else ""
    cold_hook_issues = critique_cold_hook(
        plan.title, hook_text, plan.hook.visual or "", agents.worker, agents.review_agent, budget,
    )

    # V1C: a real TTS measurement replaces the WPM estimate for the duration
    # gate. Never crashes the run if unavailable -- a genuinely missing
    # capability degrades visibly (plan §14) and falls back to the estimate,
    # it does not fail the whole short.
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
        except Exception as e:  # noqa: BLE001 -- a real network/service failure must degrade, never crash the run
            degraded_capabilities.append(f"tts_preview: synthesis failed ({e})")

    hard = check_short_structure(
        plan, narration, require_parent=require_parent, measured_duration_seconds=measured_duration_seconds,
    )
    diagnostics = check_short_diagnostics(plan, narration)

    hard_failures = [f"{i.code}: {i.detail}" for i in hard]
    critique_issues = grounding_issues + story_issues + cold_hook_issues
    hard_failures += [
        f"critical/{i.category} ({i.layer}) [{i.issue_id}]: {i.problem}"
        for i in critique_issues if i.severity == "critical"
    ]
    log.append(f"review: {len(hard_failures)} hard failures, {len(critique_issues)} issues")

    status = compute_final_status(hard_failures=hard_failures, diagnostics=diagnostics, revision_budget_remaining=False)
    if degraded_capabilities:
        status = apply_editorial_downgrade(status, "PASS_WARN")
    log.append(f"final status: {status}")

    return ShortRunResult(
        plan=plan, narration=narration, hard_failures=hard_failures,
        issues=critique_issues, diagnostics=diagnostics, final_status=status, log=log,
        preview_audio=preview_audio, measured_duration_seconds=measured_duration_seconds,
        degraded_capabilities=degraded_capabilities,
    )
