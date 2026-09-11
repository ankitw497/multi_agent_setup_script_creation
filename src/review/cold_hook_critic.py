"""C4s -- cold-hook critic (Haiku -> Gemini flash cascade) (plan §20.7, §20.10).

Judges the title + first 3 seconds the way a cold viewer (no channel
context) would: clarity, immediate tension, curiosity, confusion, generic
opening. A critic, not a swipe predictor -- it never estimates retention
numbers, only diagnoses what a real viewer would actually experience.

Cascaded per plan §8/§20.7's general pattern: Haiku (subscription, free)
judges first; only an uncertain or flagged verdict escalates to Gemini
flash (paid, cheap) for a second, cross-family opinion -- a clean,
confident Haiku pass costs nothing beyond quota.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter

from .models import CritiqueIssue

_HAIKU_PROMPT = """\
You are a cold viewer -- you know nothing about this channel or video.
Judge ONLY the title and the first 3 seconds of narration/visual
description given. Would this actually stop a scroll?

- `clear`: is it immediately obvious what this is about, or is it
  confusing/ambiguous?
- `creates_tension`: does something genuinely unresolved happen, or is it
  flat/inert?
- `curiosity_gap`: is there a real reason to keep watching, or does the
  opening already give away the point?
- `generic_opening`: is this a generic pattern ("Did you know...", "Let's
  talk about...") that could open any video, rather than something
  specific to this one?
- `confidence`: how sure are you in this judgement -- low/medium/high.
- `flagged`: true if you see any real problem (unclear, flat, no
  curiosity gap, or generic) OR your confidence is not high.

Be a real skeptical viewer, not a charitable one.
"""

_GEMINI_PROMPT = """\
A first-pass reviewer flagged this short's title/hook as possibly weak or
was unsure. Give an independent, careful second opinion as a cold viewer
(no channel context) on the same title + first 3 seconds. If there is a
real problem, raise ONE concrete issue: category="hook", layer="STORY",
naming exactly what's wrong (unclear, no real tension, no curiosity gap,
or a generic opening) and what must change -- never replacement prose. If
it's actually fine on a careful look, return no issues.
"""


class ColdHookVerdict(BaseModel):
    clarity: Literal["clear", "confusing"] = "clear"
    creates_tension: bool = True
    curiosity_gap: bool = True
    generic_opening: bool = False
    confidence: Literal["low", "medium", "high"] = "high"
    reasoning: str = ""
    flagged: bool = False


class ColdHookCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _needs_escalation(verdict: ColdHookVerdict) -> bool:
    return verdict.flagged or verdict.confidence != "high"


def _issue_from_haiku_verdict(verdict: ColdHookVerdict) -> CritiqueIssue:
    problems = []
    if verdict.clarity == "confusing":
        problems.append("unclear what the short is about")
    if not verdict.creates_tension:
        problems.append("no real tension in the first 3 seconds")
    if not verdict.curiosity_gap:
        problems.append("no reason to keep watching")
    if verdict.generic_opening:
        problems.append("generic opening pattern")
    problem_text = "; ".join(problems) if problems else verdict.reasoning or "cold-hook verdict flagged with low confidence"
    return CritiqueIssue(
        issue_id="cold_hook_1", severity="major", category="hook", layer="STORY",
        problem=problem_text, why_it_matters="a weak title/hook loses the viewer before the payoff ever lands",
        recommended_intent="rework the title/hook to be specific, create real tension, and open a curiosity gap",
        repair_owner="story_lead",
    )


def critique_cold_hook(
    title: str, hook_narration: str, hook_visual: str, worker: Agent,
    review_agent: Agent | None = None, budget: BudgetCounter | None = None,
    haiku_pass_id: str = "C4s", gemini_pass_id: str = "C4s",
) -> list[CritiqueIssue]:
    """`haiku_pass_id`/`gemini_pass_id` default to "C4s" (this module's
    original shorts-only naming) so every existing caller is unaffected.
    The long-form caller passes "C4a"/"C4b" instead, matching
    `IMPLEMENTATION_PLAN.md`'s own naming for the long-form cold-viewer
    tiers -- purely a cost-report label, no behavior difference."""
    payload = {"title": title, "hook_narration": hook_narration, "hook_visual": hook_visual}
    haiku_verdict = worker.run(
        pass_id=haiku_pass_id, mode="COLD_HOOK_HAIKU", task_prompt=_HAIKU_PROMPT,
        payload=payload, schema=ColdHookVerdict, timeout_s=120,
    )

    if not _needs_escalation(haiku_verdict):
        return []

    if review_agent is None or budget is None:
        return [_issue_from_haiku_verdict(haiku_verdict)]

    escalation_payload = {**payload, "first_pass_verdict": haiku_verdict.model_dump()}
    gemini_result = review_agent.run(
        pass_id=gemini_pass_id, mode="COLD_HOOK_GEMINI", task_prompt=_GEMINI_PROMPT,
        payload=escalation_payload, schema=ColdHookCritique, budget=budget, estimated_usd=0.01, timeout_s=120,
    )
    return gemini_result.issues
