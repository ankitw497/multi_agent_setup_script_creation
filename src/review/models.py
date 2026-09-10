"""Review contracts (plan §5, §10, design doc §28, §49).

CritiqueIssue is what every critic/verifier emits: a problem plus a
`recommended_intent` — never replacement prose (the critic never rewrites;
the editor decides how it sounds). DiagnosticResult is the banded
GREEN/AMBER/RED evidence format from plan §10 — the mechanism that keeps
heuristics advisory rather than silent hard gates.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "major", "minor"]

# design doc §28's nine categories. Expected to grow as review passes are
# implemented (Phase 4+) — kept open rather than over-fitted to what's
# named in the frozen plan today.
Category = Literal[
    "hook", "archetype", "causal_flow", "clarity", "pacing",
    "mini_payoff", "cognitive_load", "ending", "repetition",
    "micro_arc",  # short-format analogue of "archetype" (plan §20.3) -- shorts have no archetype
]

Layer = Literal["SOURCE", "STORY", "NARRATION", "VOICE", "VISUAL", "RENDERER", "TECHNICAL"]

# Only the agents that actually rewrite content ever own a repair (critics
# never rewrite; "producer != validator", plan Appendix G #3/#5).
RepairOwner = Literal["story_lead", "narration_lead", "html_author"]

Band = Literal["GREEN", "AMBER", "RED"]


class CritiqueIssue(BaseModel):
    issue_id: str
    severity: Severity
    category: Category
    layer: Layer
    scene_ids: list[str] = Field(default_factory=list)
    problem: str
    why_it_matters: str
    recommended_intent: str  # what must change — never replacement prose
    repair_owner: RepairOwner


class DiagnosticResult(BaseModel):
    """One banded, evidence-backed diagnostic (plan §10, §11.3).

    Never a silent gate on its own — see verification/models.py's status
    policy for how AMBER/RED accumulate into a final status.
    """

    dimension: str  # e.g. "burstiness", "payoff_gap", "cta_position"
    band: Band
    evidence: str  # e.g. "burstiness 0.31 vs band 0.47-0.63; scenes 7-11"
    value: float | str | None = None
    target: str | None = None


class ReviewBundle(BaseModel):
    """The review aggregator's output (plan §8): hard failures + graded diagnostics,
    never raw comments dumped straight into the editor."""

    run_id: str
    hard_failures: list[str] = Field(default_factory=list)  # gate names that failed
    issues: list[CritiqueIssue] = Field(default_factory=list)
    diagnostics: list[DiagnosticResult] = Field(default_factory=list)
