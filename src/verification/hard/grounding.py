"""The §5.1 grounding policy, mechanically enforced (plan §5.1, §9 Factual gate). No LLM.

Once a sentence is marked grounding_required (by CM) and a claim's
verification_status/importance are known (from C2a), whether that sentence
is ALLOWED to be narrated is a pure function of those three facts -- not a
judgement call. This is the actual "Factual" hard gate from plan §9:

  CORE       -> VERIFIED or CONTEXT_DEPENDENT (hedge present) only
  SUPPORTING -> VERIFIED or CONTEXT_DEPENDENT by default
  OPTIONAL   -> additionally UNVERIFIED, only with an explicit hedge
  always     -> REJECTED is never narrated; UNVERIFIED never in the
                hook / central insight / a payoff / the ending / an
                important numeric result

C2b's own (LLM) job is different: checking whether CM missed a factual
proposition, and whether a grounded sentence actually says what its cited
claim says -- both genuine judgement calls, not policy application.
"""
from __future__ import annotations

from dataclasses import dataclass

from extraction.profiles.base import sweep_numbers
from facts.models import Claim
from facts.normalize import normalize_number
from narration.models import SceneNarration

_HEDGE_WORDS = ("approximately", "roughly", "typically", "can", "may", "often", "in this example", "under these assumptions")

# Generous relative tolerance -- narration is allowed to round a precise
# source figure for speech ("roughly 40M" for a claim's "40.4M"); this
# exists to catch genuine drift (a different order of magnitude, or a
# figure that doesn't match the cited claim at all), not to punish
# reasonable compression of a number into spoken language.
NUMERIC_DRIFT_TOLERANCE = 0.10


def _numbers_roughly_match(a: float, b: float) -> bool:
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(abs(a), abs(b)) <= NUMERIC_DRIFT_TOLERANCE


@dataclass
class GroundingViolation:
    scene_id: str
    sentence_index: int
    code: str
    detail: str


def _has_hedge(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _HEDGE_WORDS)


def _claim_allows_narration(claim: Claim, sentence_text: str) -> tuple[bool, str]:
    if claim.verification_status == "REJECTED":
        return False, f"claim {claim.claim_id} is REJECTED and must never be narrated"

    if claim.verification_status in ("VERIFIED", "CONTEXT_DEPENDENT"):
        return True, ""

    # UNVERIFIED from here on.
    if claim.importance != "OPTIONAL":
        return False, (
            f"claim {claim.claim_id} is UNVERIFIED but importance={claim.importance!r} "
            "-- only OPTIONAL claims may be narrated UNVERIFIED, and only with a hedge"
        )
    if not _has_hedge(sentence_text):
        return False, f"claim {claim.claim_id} is UNVERIFIED (OPTIONAL) but the sentence carries no hedge"
    return True, ""


def check_grounding_policy(
    narration: list[SceneNarration], claims: list[Claim],
    hook_scene_ids: set[str] | None = None, ending_scene_ids: set[str] | None = None,
) -> list[GroundingViolation]:
    claims_by_id = {c.claim_id: c for c in claims}
    hook_scene_ids = hook_scene_ids or set()
    ending_scene_ids = ending_scene_ids or set()
    violations: list[GroundingViolation] = []

    for scene in narration:
        for i, sentence in enumerate(scene.sentences):
            if not sentence.grounding_required:
                continue

            if not sentence.grounding_refs:
                violations.append(GroundingViolation(
                    scene.scene_id, i, "ungrounded_factual_sentence",
                    "marked grounding_required but has no grounding_refs at all",
                ))
                continue

            for claim_id in sentence.grounding_refs:
                claim = claims_by_id.get(claim_id)
                if claim is None:
                    violations.append(GroundingViolation(
                        scene.scene_id, i, "grounding_ref_unknown_claim",
                        f"grounding_refs cites {claim_id!r}, which is not in the claim registry",
                    ))
                    continue

                allowed, reason = _claim_allows_narration(claim, sentence.text)
                if not allowed:
                    violations.append(GroundingViolation(scene.scene_id, i, "grounding_policy_violation", reason))
                    continue

                if claim.verification_status == "UNVERIFIED" and (
                    scene.scene_id in hook_scene_ids or scene.scene_id in ending_scene_ids
                ):
                    violations.append(GroundingViolation(
                        scene.scene_id, i, "unverified_in_hook_or_ending",
                        f"claim {claim.claim_id} is UNVERIFIED and must never appear in the hook or ending",
                    ))

    return violations


def check_numeric_fidelity(narration: list[SceneNarration], claims: list[Claim]) -> list[GroundingViolation]:
    """plan §9 Factual gate's "assumption/unit mismatch": a number that
    drifted between the verified claim registry and the final narration --
    e.g. a claim says "175 billion" but the narrated sentence says "175
    million" while still citing the same claim id. Pure magnitude
    comparison (extraction.profiles.base.sweep_numbers +
    facts.normalize.normalize_number) -- the same traceability primitive
    plan §9 requires for "175B" <-> "175 billion" equivalence, run here to
    catch drift instead of confirm equivalence. Only checked for sentences
    already marked grounding_required with real grounding_refs -- this is
    a fidelity check, not a substitute for check_grounding_policy."""
    claims_by_id = {c.claim_id: c for c in claims}
    violations: list[GroundingViolation] = []

    for scene in narration:
        for i, sentence in enumerate(scene.sentences):
            if not sentence.grounding_required or not sentence.grounding_refs:
                continue
            sentence_numbers = {n for n in (normalize_number(m) for m in sweep_numbers(sentence.text)) if n is not None}
            if not sentence_numbers:
                continue

            for claim_id in sentence.grounding_refs:
                claim = claims_by_id.get(claim_id)
                if claim is None:
                    continue  # already reported by check_grounding_policy
                claim_numbers = {n for n in (normalize_number(m) for m in sweep_numbers(claim.claim)) if n is not None}
                if not claim_numbers:
                    continue  # the cited claim makes no numeric assertion itself -- nothing to compare

                if not any(_numbers_roughly_match(sn, cn) for sn in sentence_numbers for cn in claim_numbers):
                    violations.append(GroundingViolation(
                        scene.scene_id, i, "numeric_drift",
                        f"sentence cites {claim_id!r} but its number(s) {sorted(sentence_numbers)} don't "
                        f"match the claim's own {sorted(claim_numbers)}",
                    ))

    return violations
