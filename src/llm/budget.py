"""Local budget policy (plan §3.2, §4, Appendix G #9).

"Budget policy is application code, not a LiteLLM helper" — this module is
the entire safety boundary. It never calls a provider; it only decides
whether a call may proceed and tracks what has actually been spent.

Three tiers per format, because one number can't be both the expected
spend and the airbag (Appendix G #9):
  target      guides tiering/escalation decisions
  warning     logged; caller should treat status as at-most PASS_WARN
  hard_cap    pre-flight: refuse to start; mid-run: stop and checkpoint
"""
from __future__ import annotations

from dataclasses import dataclass

from .usage import usd_to_microusd


@dataclass(frozen=True)
class BudgetTier:
    target_usd: float
    warning_usd: float
    hard_cap_usd: float

    def __post_init__(self) -> None:
        if not (self.target_usd <= self.warning_usd <= self.hard_cap_usd):
            raise ValueError("budget tiers must satisfy target <= warning <= hard_cap")
        if self.target_usd < 0:
            raise ValueError("budget amounts must be non-negative")


# Defaults proposed in plan §4 / Appendix G #9. Loaded from config/budget.yaml
# in practice; kept here too as the code-level fallback and for tests.
DEFAULT_TIERS: dict[str, BudgetTier] = {
    "longform": BudgetTier(target_usd=0.40, warning_usd=0.60, hard_cap_usd=1.00),
    "short": BudgetTier(target_usd=0.08, warning_usd=0.15, hard_cap_usd=0.25),
    "daily": BudgetTier(target_usd=5.00, warning_usd=5.00, hard_cap_usd=10.00),
}


class BudgetExceeded(RuntimeError):
    """A pre-flight estimate or the running spend crossed hard_cap_usd."""


class BudgetStatus:
    OK = "ok"
    WARNING = "warning"


@dataclass
class BudgetCounter:
    """Tracks spend for one run (or one day) against one tier.

    Usage:
        counter = BudgetCounter(tier=DEFAULT_TIERS["longform"])
        counter.preflight_check(estimated_usd=0.05)   # raises BudgetExceeded, or proceeds
        ... make the call ...
        status = counter.record_spend(actual_microusd)  # OK or WARNING; raises past hard_cap
    """

    tier: BudgetTier
    spent_microusd: int = 0

    def preflight_check(self, estimated_usd: float) -> None:
        estimated_microusd = usd_to_microusd(estimated_usd)
        projected = self.spent_microusd + estimated_microusd
        hard_cap_micro = usd_to_microusd(self.tier.hard_cap_usd)
        if projected > hard_cap_micro:
            raise BudgetExceeded(
                f"pre-flight estimate ${estimated_usd:.6f} would push spend to "
                f"${projected / 1_000_000:.6f}, over hard cap ${self.tier.hard_cap_usd:.2f}"
            )

    def record_spend(self, actual_microusd: int) -> str:
        if actual_microusd < 0:
            raise ValueError("spend cannot be negative")
        self.spent_microusd += actual_microusd
        hard_cap_micro = usd_to_microusd(self.tier.hard_cap_usd)
        if self.spent_microusd > hard_cap_micro:
            raise BudgetExceeded(
                f"spend ${self.spent_usd:.6f} exceeded hard cap ${self.tier.hard_cap_usd:.2f} "
                "— stop and checkpoint, do not fail over to another model (plan §3.1)"
            )
        warning_micro = usd_to_microusd(self.tier.warning_usd)
        return BudgetStatus.WARNING if self.spent_microusd > warning_micro else BudgetStatus.OK

    @property
    def spent_usd(self) -> float:
        return self.spent_microusd / 1_000_000
