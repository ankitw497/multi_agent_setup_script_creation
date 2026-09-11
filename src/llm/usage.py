"""Per-call usage/cost ledger (plan §4.1, Appendix G #8).

One UsageRecord per model call, on either lane, written to <run_dir>/usage.jsonl.
Money is integer microdollars, never float, so the reconciliation invariant
(sum(records) == manifest == budget counter) can be exact rather than
approximately true.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Lane = Literal["paid_api", "subscription"]

VALID_AGENTS = {"story_lead", "narration_lead", "review_lead", "html_author", "worker"}


def usd_to_microusd(usd: float) -> int:
    """Convert a float USD amount to integer microdollars (nearest micro-unit)."""
    return round(usd * 1_000_000)


def microusd_to_usd(microusd: int) -> float:
    return microusd / 1_000_000


@dataclass
class UsageRecord:
    run_id: str
    agent: str  # one of VALID_AGENTS
    pass_id: str  # e.g. "A1", "B1", "S2b" (plan §2.2)
    mode: str
    lane: Lane
    model_alias: str
    model_resolved: str
    revision_cycle: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # subset of output_tokens a reasoning-capable model spent on hidden reasoning
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    billed_microusd: int = 0  # paid lane only
    notional_microusd: int = 0  # subscription lane only — never billed
    cache_hit: bool = False
    saved_usd_estimate_microusd: int = 0
    latency_ms: int = 0
    attempt: int = 1
    transport_retries: int = 0
    schema_repairs: int = 0
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.agent not in VALID_AGENTS:
            raise ValueError(f"unknown agent {self.agent!r}; expected one of {sorted(VALID_AGENTS)}")
        if self.lane == "subscription" and self.billed_microusd != 0:
            raise ValueError("subscription-lane records must never carry billed_microusd > 0")
        if self.lane == "paid_api" and self.notional_microusd != 0:
            raise ValueError("paid-lane records must never carry a notional cost")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> "UsageRecord":
        return cls(**json.loads(line))


class ReconciliationError(RuntimeError):
    """The ledger's totals don't match what the caller expected.

    This must never happen silently — it means a call spent money without a
    matching record (plan §4.1: "the one failure a cost system must not have").
    """


class UsageLedger:
    """Appends UsageRecords to a JSONL file and reconciles totals against it."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: UsageRecord) -> None:
        with self.path.open("a") as f:
            f.write(record.to_json() + "\n")

    def read_all(self) -> list[UsageRecord]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [UsageRecord.from_json(line) for line in f if line.strip()]

    def total_billed_microusd(self) -> int:
        return sum(r.billed_microusd for r in self.read_all())

    def total_notional_microusd(self) -> int:
        return sum(r.notional_microusd for r in self.read_all())

    def by_agent(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.read_all():
            row = out.setdefault(
                r.agent, {"billed_microusd": 0, "notional_microusd": 0, "calls": 0}
            )
            row["billed_microusd"] += r.billed_microusd
            row["notional_microusd"] += r.notional_microusd
            row["calls"] += 1
        return out

    def reconcile(self, expected_billed_microusd: int) -> None:
        actual = self.total_billed_microusd()
        if actual != expected_billed_microusd:
            raise ReconciliationError(
                f"ledger sum={actual} microusd but expected={expected_billed_microusd} microusd "
                f"(ledger: {self.path})"
            )


class AgentCostSummary(BaseModel):
    """One row of CostReport.by_agent (plan §4.1's illustrative table)."""

    billed_microusd: int = 0
    notional_microusd: int = 0
    calls: int = 0
    cache_saved_microusd: int = 0


class CostReport(BaseModel):
    """The per-script cost breakdown (plan §4.1) — what review_summary.md's cost
    table and cost_report.json are built from. Built from a UsageLedger by
    reporting/cost_report.py::build_cost_report()."""

    run_id: str
    billed_usd: float = 0.0
    target_usd: float | None = None
    hard_cap_usd: float | None = None
    estimate_usd: float | None = None
    by_agent: dict[str, AgentCostSummary] = Field(default_factory=dict)
    by_stage: dict[str, int] = Field(default_factory=dict)  # stage group -> microusd
    by_revision_cycle: dict[int, int] = Field(default_factory=dict)  # cycle -> microusd
    cache_saved_microusd: int = 0
    escalations: list[str] = Field(default_factory=list)  # e.g. "C5 -> gemini_review_strong (voice AMBER)"

    @classmethod
    def from_ledger(cls, run_id: str, ledger: "UsageLedger") -> "CostReport":
        """The one deterministic path from records to a report — no other code
        should hand-aggregate a ledger (plan §4.1's reconciliation invariant)."""
        by_agent_raw = ledger.by_agent()
        by_agent = {
            agent: AgentCostSummary(
                billed_microusd=row["billed_microusd"],
                notional_microusd=row["notional_microusd"],
                calls=row["calls"],
            )
            for agent, row in by_agent_raw.items()
        }
        return cls(
            run_id=run_id,
            billed_usd=microusd_to_usd(ledger.total_billed_microusd()),
            by_agent=by_agent,
        )
