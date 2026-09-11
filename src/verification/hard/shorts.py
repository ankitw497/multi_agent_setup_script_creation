"""Hard gates for the `short` profile (plan §20.10). Deterministic, no LLM.

Several long-form hard gates are explicitly switched OFF for shorts (plan
§20.10): forward-driver continuity, payoff-gap valleys, the mid-video cold
viewer, the 20-40% CTA window, renderer_compat's >=1500 words. This module
only implements what's genuinely short-specific -- never long-form's
checks re-applied to a format they were never designed for.

"Any CTA after value" (a bridge only after the payoff) is satisfied by
ShortPlan's own shape: `bridge` is a single trailing field applied after
`payoff_central` is set, so there is no way to structurally place it
before the payoff -- no separate check exists for that reason.
"""
from __future__ import annotations

from dataclasses import dataclass

from narration.models import SceneNarration
from planning.shorts_models import ShortPlan

from .text_overlap import DEFAULT_OVERLAP_THRESHOLD
from .text_overlap import overlap as _overlap

MAX_SHORT_SECONDS = 62.0  # plan §20.4: 60s hard cap; +2s slack since V1A-S measures an
                           # ESTIMATE, not the measured duration V1C will eventually gate on

# Same generous, false-positive-averse word-overlap heuristic as
# verification/hard/structure.py's promise-chain gate -- title~hook~payoff
# alignment is genuinely a semantic judgement; this is a mechanical proxy
# for "these are clearly unrelated", not real understanding.
TITLE_ALIGNMENT_THRESHOLD = DEFAULT_OVERLAP_THRESHOLD


@dataclass
class ShortHardIssue:
    code: str
    detail: str


def check_central_insight_present(plan: ShortPlan) -> list[ShortHardIssue]:
    if not plan.central_insight.strip():
        return [ShortHardIssue("no_central_insight", "central_insight is empty")]
    return []


def check_title_hook_payoff_alignment(plan: ShortPlan) -> list[ShortHardIssue]:
    issues: list[ShortHardIssue] = []
    hook_text = plan.hook.narration or plan.hook.visual or ""
    if hook_text and _overlap(plan.title, hook_text) < TITLE_ALIGNMENT_THRESHOLD:
        issues.append(ShortHardIssue(
            "title_hook_mismatch", f"title={plan.title!r} shares almost no content with the hook ({hook_text!r})",
        ))
    if plan.payoff_central and _overlap(plan.title, plan.payoff_central) < TITLE_ALIGNMENT_THRESHOLD:
        issues.append(ShortHardIssue(
            "title_payoff_mismatch",
            f"title={plan.title!r} shares almost no content with payoff_central ({plan.payoff_central!r})",
        ))
    return issues


def check_duration_estimate(narration: list[SceneNarration]) -> list[ShortHardIssue]:
    total_seconds = sum(s.est_seconds for s in narration)
    if total_seconds > MAX_SHORT_SECONDS:
        return [ShortHardIssue(
            "duration_estimate_exceeds_max",
            f"estimated {total_seconds:.1f}s exceeds the {MAX_SHORT_SECONDS:.0f}s cap "
            "(plan §20.4; V1A-S measures an estimate, not yet a measured duration)",
        )]
    return []


def check_parent_reference(plan: ShortPlan, require_parent: bool) -> list[ShortHardIssue]:
    if require_parent and plan.parent is None:
        return [ShortHardIssue("missing_parent_reference", "a derived short requires plan.parent, got None")]
    return []


def check_grounding_scope(narration: list[SceneNarration], plan: ShortPlan) -> list[ShortHardIssue]:
    """Every grounded sentence's cited claims must be within the parent's
    `allowed_fact_ids` -- a derived short may not introduce a fact outside
    what the parent already verified (plan §9 Factual gate, §20.7)."""
    if plan.parent is None:
        return []  # standalone short -- no fact-set boundary to enforce
    allowed = set(plan.parent.allowed_fact_ids)
    issues: list[ShortHardIssue] = []
    for scene in narration:
        for i, sentence in enumerate(scene.sentences):
            if not sentence.grounding_required:
                continue
            for ref in sentence.grounding_refs:
                if ref not in allowed:
                    issues.append(ShortHardIssue(
                        "claim_outside_allowed_fact_set",
                        f"{scene.scene_id} sentence {i} cites {ref!r}, which is outside the parent's allowed_fact_ids",
                    ))
    return issues


def check_short_structure(
    plan: ShortPlan, narration: list[SceneNarration], require_parent: bool = True,
) -> list[ShortHardIssue]:
    """The full short-profile hard-check pass -- every check, one call."""
    return (
        check_central_insight_present(plan)
        + check_title_hook_payoff_alignment(plan)
        + check_duration_estimate(narration)
        + check_parent_reference(plan, require_parent)
        + check_grounding_scope(narration, plan)
    )
