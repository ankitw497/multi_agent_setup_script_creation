"""C4c -- mid-video cold viewer (Haiku -> Gemini flash cascade)
(`IMPLEMENTATION_PLAN.md` §8/§10.2; STORY_IMPROVEMENT_PLAN.md Phase 8.2).

C4s/C4a already judge the OPENING the way a cold viewer would. Nothing
judges the MIDDLE of a video the same way -- a viewer who clicked in from
a recommendation partway through (or scrubbed ahead) has none of the
context the opening built, and every retention/interest complaint this
project's external reviews have raised is really asking "would a real
viewer still be following, and still want to keep watching, at this
point?" Same Haiku (subscription, free) -> Gemini flash (paid, cheap)
cascade as C4s/C4a: a clean, confident verdict costs nothing.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter
from planning.models import StoryPlan
from review.visual_sample import select_scenes_for_visual_audit

from .models import CritiqueIssue

_HAIKU_PROMPT = """\
You are a viewer who just landed on this video at THIS exact point --
you did not see anything before it, only the video's title and the one
narration snippet given here. Judge honestly, as a real cold viewer would:

- `understands_why`: from just the title and this snippet, is it clear
  WHY this is being discussed -- what question or problem it's part of?
  Or does it sound like it's mid-explanation of something you have no
  context for?
- `still_interested`: even without the earlier context, is there enough
  here to make you want to keep watching, or does it feel like dead air
  you'd skip past?
- `confidence`: how sure are you in this judgement -- low/medium/high.
- `flagged`: true if either `understands_why` or `still_interested` is
  false, OR your confidence is not high.

Be a real, easily-distracted viewer, not a charitable one.
"""

_GEMINI_PROMPT = """\
A first-pass reviewer flagged this mid-video checkpoint as possibly
losing the viewer, or was unsure. Give an independent, careful second
opinion as a viewer who just landed at this exact point with only the
title and this one narration snippet, no earlier context. If there is a
real problem, raise ONE concrete issue: `layer="STORY"`, using
`category="cognitive_load"` if a viewer landing here wouldn't understand
why this is being discussed, or `category="pacing"` if they would
understand it but have no reason to keep watching -- naming exactly
what's missing and what must change, never replacement prose. If it's
actually fine on a careful look, return no issues.
"""


class ColdViewerVerdict(BaseModel):
    understands_why: bool = True
    still_interested: bool = True
    confidence: Literal["low", "medium", "high"] = "high"
    reasoning: str = ""
    flagged: bool = False


class ColdViewerCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def select_cold_viewer_checkpoints(plan: StoryPlan, max_checkpoints: int = 3) -> list[str]:
    """A few deterministic, evenly-spaced scene ids from the MIDDLE of the
    video -- excludes the first and last beat (the opening is already C4a/
    C4b's job; the ending is a different, resolved-payoff context, not a
    "just landed here" one). Reuses C3's own evenly-spaced sampler
    (`visual_sample.py`) rather than inventing a second one."""
    if len(plan.beats) < 3:
        return []
    middle_beat_ids = {b.beat_id for b in plan.beats[1:-1]}
    middle_scene_ids = [s.scene_id for s in plan.scene_plan if s.beat_id in middle_beat_ids]
    # sample_fraction=1.0: unlike C3 (which wants "flagged + a 20% sample"),
    # here `max_images` alone is meant to be the entire bound -- a short
    # video's few middle scenes should still get at least one checkpoint,
    # not round down to zero the way a 20% sample would.
    return select_scenes_for_visual_audit(
        middle_scene_ids, flagged_scene_ids=set(), max_images=max_checkpoints, sample_fraction=1.0,
    )


def _issue_from_haiku_verdict(scene_id: str, verdict: ColdViewerVerdict) -> CritiqueIssue:
    if not verdict.understands_why:
        category, problem = "cognitive_load", "a viewer landing at this point would not know why this is being discussed"
    elif not verdict.still_interested:
        category, problem = "pacing", "a viewer landing at this point has no reason to keep watching"
    else:
        category, problem = "cognitive_load", verdict.reasoning or "mid-video cold-viewer verdict flagged with low confidence"
    return CritiqueIssue(
        issue_id=f"cold_viewer_{scene_id}", severity="major", category=category, layer="STORY",
        scene_ids=[scene_id], problem=problem,
        why_it_matters="a viewer who loses the thread or interest mid-video drops off before the payoff",
        recommended_intent="re-orient the viewer at this point (what question this answers) or tighten the pacing here",
        repair_owner="story_lead",
    )


def critique_cold_viewer(
    plan: StoryPlan, narration_text_by_scene_id: dict[str, str], worker: Agent,
    review_agent: Agent | None = None, budget: BudgetCounter | None = None,
    haiku_pass_id: str = "C4c", gemini_pass_id: str = "C4c",
) -> list[CritiqueIssue]:
    """One independent Haiku judgment per sampled checkpoint scene (each
    checkpoint stands alone -- there is no aggregate verdict to combine);
    only a flagged checkpoint escalates to Gemini, same cascade discipline
    as C4s/C4a."""
    checkpoints = select_cold_viewer_checkpoints(plan)
    issues: list[CritiqueIssue] = []
    for scene_id in checkpoints:
        payload = {"title": plan.title.chosen, "narration_snippet": narration_text_by_scene_id.get(scene_id, "")}
        verdict = worker.run(
            pass_id=haiku_pass_id, mode="COLD_VIEWER_HAIKU", task_prompt=_HAIKU_PROMPT,
            payload=payload, schema=ColdViewerVerdict, timeout_s=120,
        )
        if not (verdict.flagged or verdict.confidence != "high" or not verdict.understands_why or not verdict.still_interested):
            continue
        if review_agent is None or budget is None:
            issues.append(_issue_from_haiku_verdict(scene_id, verdict))
            continue
        escalation_payload = {**payload, "first_pass_verdict": verdict.model_dump()}
        gemini_result = review_agent.run(
            pass_id=gemini_pass_id, mode="COLD_VIEWER_GEMINI", task_prompt=_GEMINI_PROMPT,
            payload=escalation_payload, schema=ColdViewerCritique, budget=budget, estimated_usd=0.01, timeout_s=120,
        )
        issues.extend(gemini_result.issues)
    return issues
