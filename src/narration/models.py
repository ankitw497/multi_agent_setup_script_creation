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
    # STORY_IMPROVEMENT_PLAN.md Phase 10: a stable id CM/C2b key their verdicts to, so a
    # missing verdict can be detected as missing rather than silently defaulting to "not
    # factual" (the confirmed bug this phase fixes). Left blank by every narration-producing
    # pass (B1/B2/short_generator/humanize) -- `stamp_sentence_ids()` below fills it in
    # defensively at the one place it's actually needed (CM/C2b), so no producer has to
    # remember to set it.
    sentence_id: str = ""


class SceneNarration(BaseModel):
    scene_id: str
    sentences: list[SentenceNarration] = Field(default_factory=list)
    est_seconds: float = 0.0


def stamp_sentence_ids(narration: list[SceneNarration]) -> list[SceneNarration]:
    """Assigns a stable `{scene_id}:{index}` id to every sentence that doesn't already
    have one (STORY_IMPROVEMENT_PLAN.md Phase 10). Called defensively by CM and C2b rather
    than trusted to every narration-producing call site -- a builder that forgets to set it
    can never silently break the coverage invariant those two passes enforce."""
    return [
        scene.model_copy(update={
            "sentences": [
                s if s.sentence_id else s.model_copy(update={"sentence_id": f"{scene.scene_id}:{i}"})
                for i, s in enumerate(scene.sentences)
            ],
        })
        for scene in narration
    ]


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
