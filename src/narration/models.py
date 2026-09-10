"""Narration contracts (plan §5, §5.1, §11.4).

sentence_type is writer metadata, NOT the grounding boundary — the
independent Claim Mapper sets grounding_required/grounding_refs
regardless of how the writer labelled a sentence (plan §5.1's central
rule: never let the producer define its own validation boundary).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SentenceType = Literal[
    "technical_assertion", "source_paraphrase", "explanatory_inference",
    "analogy", "transition", "question", "payoff", "cta",
]


class SentenceNarration(BaseModel):
    text: str
    sentence_type: SentenceType
    claim_refs: list[str] = Field(default_factory=list)  # writer's own attribution — metadata only
    grounding_required: bool = False  # set by the Claim Mapper (CM), never by the writer
    grounding_refs: list[str] = Field(default_factory=list)  # set by CM/C2b


class SceneNarration(BaseModel):
    scene_id: str
    sentences: list[SentenceNarration] = Field(default_factory=list)
    est_seconds: float = 0.0


class EditMapEntry(BaseModel):
    """One B4 edit (plan §11.4). change_type is deliberately open text, not a closed
    enum yet — the real vocabulary will emerge once B4's prompt is written (Phase 7)."""

    scene_id: str
    before: str
    after: str
    change_type: str = "style_only"


class EditMap(BaseModel):
    """B4's full output for one humanize pass — the artifact the number/claim diff
    guard and C6 entailment check operate on (plan §11.4)."""

    run_id: str
    revision_cycle: int = 0
    entries: list[EditMapEntry] = Field(default_factory=list)
