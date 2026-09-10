"""Shorts contracts (plan §20.5) — kept separate from long-form planning models.

A short derives the parent's KNOWLEDGE, never its STORY SHAPE (plan §20).
Nothing here inherits Archetype from planning/models.py on purpose.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MicroArc = Literal[
    "contradiction_resolution", "problem_fix", "before_after", "question_answer",
    "prediction_explanation", "myth_correction", "mini_derivation",
]
ShortGoal = Literal["DISCOVERY", "BRIDGE", "SERIES"]
BridgeMode = Literal["PLATFORM_LINK", "ONSCREEN", "SPOKEN", "NONE"]


class HookEvent(BaseModel):
    """The interesting thing must HAPPEN in 0-3s; a visual can carry it before narration (plan §20.4)."""

    narration: str | None = None
    visual: str | None = None
    starts_at_seconds: float = Field(default=0.0, ge=0.0, le=3.0)
    tension: str = ""


class ShortsCandidate(BaseModel):
    """One beat-derived candidate, ranked by multi-factor judgement, not knowledge gain alone (plan §20.6)."""

    beat_ids: list[str]
    insight: str
    hook_material: str = ""
    micro_arc_suggestion: MicroArc | None = None
    prerequisites: list[str] = Field(default_factory=list)
    visual_object: str = ""
    bridge_question: str = ""
    scores: dict[str, float] = Field(default_factory=dict)  # e.g. intelligibility, hookability, ...


class ShortParent(BaseModel):
    run_id: str
    final_plan_hash: str
    source_beat_ids: list[str] = Field(default_factory=list)
    allowed_fact_ids: list[str] = Field(default_factory=list)  # claim_ids + derivations/inferences over them


class ShortBridge(BaseModel):
    mode: BridgeMode = "NONE"
    parent_video_id: str | None = None


class ShortVisual(BaseModel):
    dominant_object: str = ""
    states: list[str] = Field(default_factory=list)
    safe_zones: list[str] = Field(default_factory=list)  # plan §20.9 vertical-safe composition


class ShortNarration(BaseModel):
    target_duration_seconds: float = Field(default=52.0, ge=45.0, le=60.0)
    word_band: tuple[int, int] = (120, 165)  # advisory only (plan §20.4) — never a hard gate


class ShortPlan(BaseModel):
    """A2s's output (plan §20.5). Parent linkage is required for a derived short;
    the spoken bridge is not — sometimes the strongest ending is the payoff."""

    parent: ShortParent | None = None  # required for derived; None only for a standalone short
    title: str = ""  # plan §20.6/§20.10: A2s's design output, checked for title~hook~payoff alignment
    goal: ShortGoal = "DISCOVERY"
    central_insight: str
    micro_arc: MicroArc
    hook: HookEvent
    setup: str = ""  # minimum_context
    mechanism: str = ""
    payoff_central: str = ""
    micro_payoffs: list[str] = Field(default_factory=list)
    bridge: ShortBridge = Field(default_factory=ShortBridge)
    visual: ShortVisual = Field(default_factory=ShortVisual)
    narration: ShortNarration = Field(default_factory=ShortNarration)
