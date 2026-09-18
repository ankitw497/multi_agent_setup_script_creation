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

import threading
from dataclasses import dataclass, field

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
#
# longform raised 2x (2026-09-15): the original $1.00 hard cap was set before
# STORY_IMPROVEMENT_PLAN.md Phase 10 (C2b's sparse-issues -> dense per-sentence
# verdicts, a deliberate ~3-5x cost increase for a real fail-closed correctness
# win) and Phase 13 (C4d, a second full cold/continuing-viewer cascade at the
# same checkpoints as the pre-existing C4c). ERR-046 (2026-09-12) already
# established $1.00 was tight for a reasoning-capable story_lead alias but left
# the DEFAULT (gpt-4o) path alone because it "still completes fine" then --
# confirmed no longer true: a survey of every run's usage.jsonl since Phase 10
# landed shows the DEFAULT gpt-4o loop alone routinely costs $1.0-$1.6 (C2b's
# own share alone: $0.46-$0.79, vs. $0.08-$0.20 before Phase 10), so the
# unmodified default now hits BudgetExceeded on the FIRST review cycle of an
# ordinary run, not just a reasoning-tier comparison. Doubling gives headroom
# above the observed range without requiring --loop-budget-usd on every run.
DEFAULT_TIERS: dict[str, BudgetTier] = {
    "longform": BudgetTier(target_usd=0.80, warning_usd=1.20, hard_cap_usd=2.00),
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
    # 2026-09-15: a single BudgetCounter is now shared across concurrently-running batch
    # calls (review/claim_mapper.py, review/grounding_verifier.py -- see llm/concurrency.py)
    # to cut wall-clock time. `self.spent_microusd += x` is a read-modify-write, not atomic
    # under the GIL across threads -- without this lock two concurrent calls could each read
    # the same stale total and one update would be silently lost, undercounting real spend
    # past hard_cap. Excluded from repr/eq -- a Lock has no meaningful value equality and
    # existing tests/callers construct/compare BudgetCounter by its tier/spent_microusd only.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def preflight_check(self, estimated_usd: float) -> None:
        estimated_microusd = usd_to_microusd(estimated_usd)
        with self._lock:
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
        with self._lock:
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
