"""PipelineState — the single typed object threaded through one run (plan §5, §8).

One pydantic model, so `state.model_dump_json()` after every stage IS the
checkpoint — human-readable and diffable, and what makes a rate-limited
run resumable rather than a re-pay (plan §4.2, §17 Phase 0's "done when").
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from editing.models import RevisionPlan
from facts.models import AssumptionLedger, Claim, SourceUnit
from narration.models import SceneNarration
from planning.models import SourceBrief, StoryPlan
from planning.shorts_models import ShortPlan
from review.models import ReviewBundle
from verification.models import QualityReport


class PipelineState(BaseModel):
    # input
    run_id: str
    html_path: str
    source_hash: str = ""
    config: dict = Field(default_factory=dict)  # story.archetype override, format, duration, ...

    # deterministic extraction + facts
    source_units: list[SourceUnit] = Field(default_factory=list)
    claim_registry: list[Claim] = Field(default_factory=list)
    assumption_ledger: AssumptionLedger | None = None

    # understanding + planning
    source_brief: SourceBrief | None = None
    plan: StoryPlan | None = None

    # narration
    draft_version: int = 0
    narration: list[SceneNarration] = Field(default_factory=list)

    # review + revision
    review_bundle: ReviewBundle | None = None
    revision_plan: RevisionPlan | None = None
    revision_count: int = 0

    # shorts derived from this run, once it passes (plan §20)
    shorts: list[ShortPlan] = Field(default_factory=list)

    # final
    quality_report: QualityReport | None = None
    status: str = "running"
