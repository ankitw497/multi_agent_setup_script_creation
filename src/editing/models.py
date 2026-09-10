"""Revision-planning contracts (design doc §36, plan §15).

The revision planner decides WHAT changes (preserve / rewrite / correct /
delete); the narration lead decides HOW it sounds. Never the reverse.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RewriteBeat(BaseModel):
    beat_id: str
    reason: str
    intent: str  # what must change — not replacement prose


class TechnicalFix(BaseModel):
    scene_id: str
    claim_id: str | None = None
    required_change: str


class DeleteOrCompress(BaseModel):
    scene_id: str
    reason: str


class RevisionPlan(BaseModel):
    run_id: str
    revision_level: str = "targeted"  # e.g. "targeted", "major", "replan"
    preserve: list[str] = Field(default_factory=list)  # beat/scene ids or named sections
    rewrite_beats: list[RewriteBeat] = Field(default_factory=list)
    technical_fixes: list[TechnicalFix] = Field(default_factory=list)
    delete_or_compress: list[DeleteOrCompress] = Field(default_factory=list)
    story_replan_required: bool = False
