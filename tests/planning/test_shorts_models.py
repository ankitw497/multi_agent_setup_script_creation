"""Round-trip tests for planning/shorts_models.py (plan §20.5)."""
import pytest
from pydantic import ValidationError

from planning.shorts_models import HookEvent, ShortBridge, ShortPlan, ShortsCandidate

from tests.conftest import roundtrip, roundtrip_fixture


def test_hook_event_roundtrips():
    event = roundtrip(
        HookEvent,
        {"narration": "3,847 tokens: fine.", "visual": "counter", "starts_at_seconds": 1.0, "tension": "x"},
    )
    assert event.starts_at_seconds <= 3.0


def test_hook_event_rejects_start_after_three_seconds():
    """Plan §20.4: the interesting thing must happen in 0-3s."""
    with pytest.raises(ValidationError):
        HookEvent(starts_at_seconds=5.0)


def test_shorts_candidate_roundtrips_with_multi_factor_scores():
    """Knowledge gain is one input, not the dominant one (plan §20.6) — scores
    is an open dict precisely so no single factor is hard-coded as primary."""
    candidate = roundtrip(
        ShortsCandidate,
        {
            "beat_ids": ["B02"], "insight": "x", "micro_arc_suggestion": "contradiction_resolution",
            "scores": {"intelligibility": 0.9, "hookability": 0.8, "self_containedness": 0.7},
        },
    )
    assert set(candidate.scores) == {"intelligibility", "hookability", "self_containedness"}


def test_short_bridge_defaults_to_none_mode():
    """Parent linkage is required for a derived short; the spoken bridge is not —
    sometimes the strongest ending is the payoff (plan §20.5)."""
    bridge = ShortBridge()
    assert bridge.mode == "NONE"


def test_short_plan_roundtrips_full_nested_structure():
    plan = roundtrip_fixture(ShortPlan, "planning", "ShortPlan")
    assert plan.goal == "BRIDGE"
    assert plan.micro_arc == "contradiction_resolution"
    assert plan.parent.allowed_fact_ids == ["C004", "C005"]
    assert plan.hook.starts_at_seconds <= 3.0


def test_short_plan_does_not_inherit_a_long_form_archetype():
    """Structural guarantee, not just a design intent: ShortPlan has no
    `archetype` field at all (plan §20 — "derive the knowledge, not the
    storytelling")."""
    assert "archetype" not in ShortPlan.model_fields
