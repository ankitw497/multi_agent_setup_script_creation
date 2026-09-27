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

# Raised 60s -> 120s (2026-09-16, user decision): the tight 60s cap was a real
# contributing factor to several recurring failures (duration overruns, a setup segment
# with no room left once it also had to carry its per-micro_arc required beat), not just
# the direct duration-overrun findings -- more room for the same required content
# structurally relieves multiple failure categories at once, not only this one.
MAX_SHORT_SECONDS = 122.0  # 120s hard cap; +2s slack since V1A-S measures an
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
    """2026-09-15: confirmed live -- a visual-only hook (`hook.narration` empty by
    design, plan §20.4's "a visual can carry it before narration does") used to fall
    back to comparing the title against `hook.visual` alone, a diagram-description
    sentence in a completely different vocabulary domain from a title ("Query-key
    matrix visualization expanding from 4x4 to 8x8" vs. any reasonable title) -- no
    title could realistically clear the bar against text like that. Now accepts a
    match against EITHER the hook text (narration, else visual) OR `central_insight`
    (always populated, and the one thing every short's title should arguably capture
    regardless of how the hook itself is staged) -- a title only fails if it's
    unrelated to every anchor available, not just the one that happened to be a
    visual description this time."""
    issues: list[ShortHardIssue] = []
    hook_text = plan.hook.narration or plan.hook.visual or ""
    # visual_anchor (2026-09-25, Phase 30 P1 item 3): `plan.visual.states`/`dominant_object`
    # -- the SHORT's actual concrete visual anchor (e.g. two contrasted example states) --
    # used to be entirely excluded from this check, distinct from `hook.visual` above (a
    # prose description, not the concrete states list). Confirmed live: a real title
    # ("Self-Attention and Permutation") passed this check against central_insight alone
    # while a genuinely more concrete, memorable anchor sat in `visual.states` untouched.
    visual_anchor = " ".join([plan.visual.dominant_object, *plan.visual.states]).strip()
    hook_anchors = [t for t in (hook_text, plan.central_insight, visual_anchor) if t]
    if hook_anchors and not any(_overlap(plan.title, t) >= TITLE_ALIGNMENT_THRESHOLD for t in hook_anchors):
        issues.append(ShortHardIssue(
            "title_hook_mismatch",
            f"title={plan.title!r} shares almost no content with the hook ({hook_text!r}) "
            f"or central_insight ({plan.central_insight!r})",
        ))
    payoff_anchors = [t for t in (plan.payoff_central, plan.central_insight) if t]
    if payoff_anchors and not any(_overlap(plan.title, t) >= TITLE_ALIGNMENT_THRESHOLD for t in payoff_anchors):
        issues.append(ShortHardIssue(
            "title_payoff_mismatch",
            f"title={plan.title!r} shares almost no content with payoff_central "
            f"({plan.payoff_central!r}) or central_insight ({plan.central_insight!r})",
        ))
    return issues


def check_duration_estimate(narration: list[SceneNarration]) -> list[ShortHardIssue]:
    """The WPM-based fallback, used only when a real TTS measurement isn't
    available (degraded -- see check_measured_duration, the V1C gate this
    was always meant to be superseded by)."""
    total_seconds = sum(s.est_seconds for s in narration)
    if total_seconds > MAX_SHORT_SECONDS:
        return [ShortHardIssue(
            "duration_estimate_exceeds_max",
            f"estimated {total_seconds:.1f}s exceeds the {MAX_SHORT_SECONDS:.0f}s cap "
            "(plan §20.4; an ESTIMATE -- TTS measurement was unavailable for this run)",
        )]
    return []


# No +2s slack here, unlike the estimate cap -- this is the real measured
# duration (edge-tts's own SentenceBoundary timing, plan §17/§20.4/V1C),
# not an approximation with its own error margin to buffer against.
MAX_MEASURED_SHORT_SECONDS = 120.0  # raised from 60.0, 2026-09-16 -- see MAX_SHORT_SECONDS above


def check_measured_duration(measured_seconds: float) -> list[ShortHardIssue]:
    if measured_seconds > MAX_MEASURED_SHORT_SECONDS:
        return [ShortHardIssue(
            "measured_duration_exceeds_max",
            f"measured {measured_seconds:.1f}s (real TTS audio) exceeds the "
            f"{MAX_MEASURED_SHORT_SECONDS:.0f}s cap (plan §20.4)",
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


REQUIRED_SEGMENTS = {"hook", "setup", "mechanism", "payoff"}


def check_segment_completeness(narration: list[SceneNarration]) -> list[ShortHardIssue]:
    """PIPELINE_AUDIT_2026-09-17.md: `GeneratedShortNarration.segments`/`ShortTargetedRewrite.
    segments` are plain lists with no schema-level constraint tying the list to exactly one
    entry per {hook, setup, mechanism, payoff} -- a response with two "hook" entries and no
    "payoff" is schema-valid. Nothing downstream ever noticed: `{n.scene_id: n for n in
    narration}`-style lookups elsewhere in this pipeline silently keep the LAST duplicate and
    never notice a segment is simply absent, shipping a short with up to a full quarter of
    its intended content silently missing."""
    scene_ids = [s.scene_id for s in narration]
    missing = REQUIRED_SEGMENTS - set(scene_ids)
    duplicates = {sid for sid in set(scene_ids) if scene_ids.count(sid) > 1}
    if not missing and not duplicates:
        return []
    detail = []
    if missing:
        detail.append(f"missing segment(s): {sorted(missing)}")
    if duplicates:
        detail.append(f"duplicate segment(s): {sorted(duplicates)}")
    return [ShortHardIssue("incomplete_or_duplicate_segments", "; ".join(detail))]


def check_short_structure(
    plan: ShortPlan, narration: list[SceneNarration], require_parent: bool = True,
    measured_duration_seconds: float | None = None,
) -> list[ShortHardIssue]:
    """The full short-profile hard-check pass -- every check, one call.

    `measured_duration_seconds` (V1C) is the real TTS-measured duration,
    when available -- it REPLACES the WPM estimate rather than adding to
    it (a short only ever gets one duration gate, never scored against
    both). `None` means TTS was unavailable for this run (a recorded
    degradation upstream, not silently ignored) -- the estimate is the
    honest fallback, not a first choice.
    """
    duration_issues = (
        check_measured_duration(measured_duration_seconds)
        if measured_duration_seconds is not None
        else check_duration_estimate(narration)
    )
    return (
        check_central_insight_present(plan)
        + check_title_hook_payoff_alignment(plan)
        + duration_issues
        + check_parent_reference(plan, require_parent)
        + check_grounding_scope(narration, plan)
        + check_segment_completeness(narration)
    )
