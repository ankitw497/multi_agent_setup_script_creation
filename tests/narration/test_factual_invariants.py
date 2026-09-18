"""Tests for narration/factual_invariants.py -- the shared fragment injected into every
narration-writing pass (B1, B2, and the shorts narrator), STORY_IMPROVEMENT_PLAN.md Phase 12.
"""
from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS


def test_covers_the_never_upgrade_certainty_direction():
    assert "NEVER UPGRADE" in NARRATION_FACTUAL_INVARIANTS
    assert "possible" in NARRATION_FACTUAL_INVARIANTS and "actual" in NARRATION_FACTUAL_INVARIANTS


def test_covers_the_never_hedge_a_verified_claim_direction():
    """2026-09-16, found on review: this module's own docstring claims it gives B2/shorts
    "equivalent language" to B1's own hedge/verification-status rules
    (narration/generator.py) -- but the actual fragment only ever ported the overclaim
    direction, never B1's "never hedge a verified technical claim with 'is believed to'"
    rule. B2 and the shorts narrator could silently under-claim a settled fact just as
    easily as they could over-claim one, with nothing here to catch it."""
    assert "is believed to" in NARRATION_FACTUAL_INVARIANTS
    assert "VERIFIED" in NARRATION_FACTUAL_INVARIANTS


def test_covers_explanatory_elaboration_as_needing_grounding_too():
    """STORY_IMPROVEMENT_PLAN.md Phase 25 (mitigation only): confirmed live -- narration
    can invent a WHY/HOW explanation that never passed through claim extraction/C2a
    verification at all, catchable only by a critic's judgment, never a deterministic
    check. This is a prompt-only nudge, not a new mechanism -- revisit with a real
    deterministic check only if this recurs."""
    assert "An EXPLANATION of why or how a mechanism behaves" in NARRATION_FACTUAL_INVARIANTS
    assert "not a free-form elaboration exempt from grounding" in NARRATION_FACTUAL_INVARIANTS
