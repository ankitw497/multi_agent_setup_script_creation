"""Render-report and final-status contracts (plan §12.0, §13, §14).

QualityReport.final_status follows the ordered policy from plan §14
exactly: FAIL > REVISE > PASS_WARN > PASS, first match wins. It is a
deterministic function of hard-gate failures and diagnostic bands, never
something A4 decides on its own (A4 may only downgrade, never clear a
failure or upgrade a status — plan §9, §14).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from review.models import DiagnosticResult

FinalStatus = Literal["FAIL", "REVISE", "PASS_WARN", "PASS"]


class RenderReport(BaseModel):
    """Stage HV's output (plan §12.0, §13) — static checks first, rendered checks second."""

    run_id: str
    scene_order_ok: bool = True
    duplicate_ids: list[str] = Field(default_factory=list)
    numeric_claim_mismatches: list[str] = Field(default_factory=list)  # "<id>: dom=X registry=Y"
    narration_hash_match: bool = True
    deictic_unresolved: list[str] = Field(default_factory=list)
    renderer_compat_ok: bool = True  # >=3 sections, >=1500 claim-backed words, no empty sections
    reader_standalone_ok: bool = True  # plan §12.0: page.html passes an article check on its own
    page_parity_ok: bool = True  # plan §12.0: video_script.html and page.html render pixel-identical
    screenshots: list[str] = Field(default_factory=list)
    visual_flags: list[str] = Field(default_factory=list)  # sparse scene, layout repetition, ...
    issues: list[str] = Field(default_factory=list)


class ApprovalQuestion(BaseModel):
    """Playbook's ten approval questions, shipped as a checklist (plan §14).
    Questions 3, 4, 7, 9 map to hard gates; the rest are advisory."""

    index: int = Field(ge=1, le=10)
    question: str
    passed: bool
    is_hard_gate: bool = False


class QualityReport(BaseModel):
    run_id: str
    final_status: FinalStatus
    hard_gate_failures: list[str] = Field(default_factory=list)
    diagnostics: list[DiagnosticResult] = Field(default_factory=list)
    amber_count: int = 0
    red_count: int = 0
    pass_amber_allowance: int = 3  # plan §14 default
    archetype_input: str = "auto"
    archetype_resolved: str | None = None
    revisions: int = 0
    approval_checklist: list[ApprovalQuestion] = Field(default_factory=list)
    editorial_summary: str | None = None  # A4's addition — may explain a downgrade, never a clear
