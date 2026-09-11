"""Deterministic revision routing (plan §15). No model chooses the next step.

A3's own output already IS the routing decision at the finding level
(story_replan_required, or specific rewrite/fix/delete targets) -- this
module just turns that into one of three actions the orchestrator executes,
so the decision logic lives in one place rather than being re-derived at
each call site.
"""
from __future__ import annotations

from enum import Enum

from editing.models import RevisionPlan


class RevisionAction(str, Enum):
    REPLAN = "replan"  # back to A2 (plan §15: bounded, MAX_STORY_REPLANS=1)
    TARGETED_REWRITE = "targeted_rewrite"  # B2, scoped to what A3 named
    NONE = "none"  # nothing to do -- skip B2/B3/B4 entirely (plan: "nothing runs because it exists")


def decide_action(revision_plan: RevisionPlan) -> RevisionAction:
    if revision_plan.story_replan_required:
        return RevisionAction.REPLAN
    if (
        revision_plan.rewrite_beats or revision_plan.rewrite_scenes
        or revision_plan.technical_fixes or revision_plan.delete_or_compress
    ):
        return RevisionAction.TARGETED_REWRITE
    return RevisionAction.NONE
