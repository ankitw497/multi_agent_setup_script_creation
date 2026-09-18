"""PipelineState — the single typed object threaded through one run (plan §5, §8).

One pydantic model, so `state.model_dump_json()` after every stage IS the
checkpoint — human-readable and diffable, and what makes a rate-limited
run resumable rather than a re-pay (plan §4.2, §17 Phase 0's "done when").

STORY_IMPROVEMENT_PLAN.md Phase 17.1: this model existed, and this exact docstring claim
("resumable rather than a re-pay") was made, since before any agent in this codebase was
implemented -- but nothing ever actually called `save_checkpoint`/`load_checkpoint` below, or
read a checkpoint back into `run_pipeline.py`, until now. Confirmed real cost during a live
verification session (2026-09-15): five relaunches in one afternoon each re-paid for claim
verification (C2a) and source understanding (A1) from scratch after a crash or
`BudgetExceeded` further downstream. `completed_stages` + the `*_spent_microusd` fields below
are what makes `run_pipeline.py`'s `--resume` flag able to skip a stage it already has a good
result for, without silently under-counting the run's true cumulative spend.

Scope note: this covers stage-level resume (claims, source_brief, the full story+narration
loop result) -- NOT resuming from partway through the loop's own bounded revision cycles,
where every real crash this session actually happened. That's Phase 17.2, deliberately
deferred pending evidence that 17.1 alone isn't enough (this project's own "don't build ahead
of evidence" discipline) -- H+HV and shorts checkpointing are similarly deferred: no real
failure this session ever reached that far, so there's no confirmed waste to fix there yet.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from editing.models import RevisionPlan
from facts.models import AssumptionLedger, Claim, SourceUnit
from narration.models import SceneNarration
from planning.models import SourceBrief, StoryPlan
from planning.shorts_models import ShortPlan
from review.models import ReviewBundle
from verification.models import QualityReport

CHECKPOINT_FILENAME = "checkpoint.json"


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

    # STORY_IMPROVEMENT_PLAN.md Phase 17.1 -- resume bookkeeping. `completed_stages` uses
    # the literal stage names `run_pipeline.py` checks against: "claims", "source_brief",
    # "story_loop". A stage's own `*_spent_microusd` is the TRUE cost already paid for it,
    # so resuming never silently resets a budget counter back to zero (which could let the
    # combined original+resumed spend quietly exceed what a cap was meant to bound).
    completed_stages: list[str] = Field(default_factory=list)
    claims_spent_microusd: int = 0
    source_brief_spent_microusd: int = 0
    loop_spent_microusd: int = 0
    story_replans_used: int = 0
    major_revisions_used: int = 0
    story_final_status: str = ""


def save_checkpoint(state: PipelineState, run_dir: str | Path) -> None:
    (Path(run_dir) / CHECKPOINT_FILENAME).write_text(state.model_dump_json(indent=2))


def load_checkpoint(run_dir: str | Path) -> PipelineState:
    """Raises FileNotFoundError with a clear message if `run_dir` never wrote a checkpoint
    (e.g. it crashed before the first stage completed, or predates Phase 17.1) -- never
    silently returns an empty/fresh state, which would look like a successful resume while
    actually redoing everything anyway."""
    path = Path(run_dir) / CHECKPOINT_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"no {CHECKPOINT_FILENAME} found in {run_dir} -- nothing to resume from "
            "(the run may have crashed before its first stage completed, or predates checkpointing)"
        )
    return PipelineState.model_validate_json(path.read_text())
