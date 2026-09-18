"""Unit tests for llm/budget.py — plan §3.2, Appendix G #9 (three-tier local budget policy)."""
import pytest

from llm.budget import BudgetCounter, BudgetExceeded, BudgetStatus, BudgetTier, DEFAULT_TIERS
from llm.usage import usd_to_microusd


def test_default_tiers_are_internally_ordered():
    for name, tier in DEFAULT_TIERS.items():
        assert tier.target_usd <= tier.warning_usd <= tier.hard_cap_usd, name


def test_tier_rejects_out_of_order_bounds():
    with pytest.raises(ValueError, match="target <= warning <= hard_cap"):
        BudgetTier(target_usd=0.60, warning_usd=0.40, hard_cap_usd=1.00)


def test_tier_rejects_negative_amounts():
    with pytest.raises(ValueError):
        BudgetTier(target_usd=-0.1, warning_usd=0.1, hard_cap_usd=1.0)


def test_preflight_allows_a_call_within_budget():
    counter = BudgetCounter(tier=DEFAULT_TIERS["short"])
    counter.preflight_check(estimated_usd=0.05)  # must not raise


def test_preflight_refuses_a_call_that_would_exceed_hard_cap():
    counter = BudgetCounter(tier=DEFAULT_TIERS["short"])  # hard_cap = 0.25
    with pytest.raises(BudgetExceeded):
        counter.preflight_check(estimated_usd=0.30)


def test_record_spend_returns_ok_under_warning():
    counter = BudgetCounter(tier=DEFAULT_TIERS["longform"])  # warning = 0.60
    status = counter.record_spend(usd_to_microusd(0.10))
    assert status == BudgetStatus.OK


def test_record_spend_returns_warning_once_past_warning_threshold():
    counter = BudgetCounter(tier=DEFAULT_TIERS["longform"])  # warning = 1.20, hard_cap = 2.00
    status = counter.record_spend(usd_to_microusd(1.30))
    assert status == BudgetStatus.WARNING


def test_record_spend_raises_past_hard_cap():
    """A run at $0.90 needing one more legitimate revision should still proceed under the cap;
    only crossing the hard cap itself must stop the run (Appendix G #9)."""
    counter = BudgetCounter(tier=DEFAULT_TIERS["longform"])  # hard_cap = 2.00
    counter.record_spend(usd_to_microusd(0.90))  # fine, under target even
    counter.record_spend(usd_to_microusd(1.00))  # 1.90 total, still under hard cap -> proceeds
    with pytest.raises(BudgetExceeded):
        counter.record_spend(usd_to_microusd(0.20))  # 2.10 total -> over hard cap


def test_record_spend_rejects_negative_amounts():
    counter = BudgetCounter(tier=DEFAULT_TIERS["short"])
    with pytest.raises(ValueError):
        counter.record_spend(-1)


def test_spent_usd_property_matches_accumulated_microusd():
    counter = BudgetCounter(tier=DEFAULT_TIERS["short"])
    counter.record_spend(usd_to_microusd(0.05))
    counter.record_spend(usd_to_microusd(0.02))
    assert counter.spent_usd == pytest.approx(0.07)
