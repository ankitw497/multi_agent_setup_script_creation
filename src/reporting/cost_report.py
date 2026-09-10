"""cost_report.json (plan §4.1, §16, §17). V1A's own "done" bar names this
file explicitly: "a cost_report.json whose totals reconcile to the
manifest." `CostReport.from_ledger()` (llm/usage.py) is already the one
deterministic path from a UsageLedger to a report -- this is just the R*
entry point that calls it, so emission code has one obvious place to go.
"""
from __future__ import annotations

from llm.usage import CostReport, UsageLedger


def build_cost_report(run_id: str, ledger: UsageLedger) -> CostReport:
    return CostReport.from_ledger(run_id, ledger)
