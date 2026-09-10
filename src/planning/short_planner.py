"""A2s -- short story planner (Story Lead / GPT mini) (plan §20.6).

Selects the top `shorts.count` candidates from SC's shortlist (default 3;
fewer if fewer are genuinely self-contained -- must not pad to the count)
and designs each as its own ShortPlan. `parent` linkage (`final_plan_hash`,
`allowed_fact_ids`) is deliberately NOT the model's job -- it's exact
bookkeeping computed in Python from the selected candidate's own
`beat_ids`, the same "arithmetic is deterministic, not model-voted"
principle applied to fact-set scoping (plan §9's Factual gate: a derived
short may not introduce a fact outside its allowed set).
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from planning.models import StoryPlan

from .shorts_models import (
    HookEvent, MicroArc, ShortBridge, ShortGoal, ShortNarration, ShortParent, ShortPlan,
    ShortsCandidate, ShortVisual,
)

DEFAULT_SHORTS_COUNT = 3  # plan §20.6: a ceiling, not a quota

TASK_PROMPT = """\
From the candidate shortlist below, select up to `shorts_count` candidates
that would genuinely make strong, self-contained shorts -- fewer is fine
and expected if fewer are genuinely self-contained; never pad the count
with a weak candidate just to fill it. Candidate quality is multi-factor,
not knowledge gain alone: instant intelligibility, hookability, surprise
or contrast, self-containedness, low prerequisite burden, visual
singularity, payoff strength, relevance, bridge potential. The best
long-form insight is often a poor short; a side observation is sometimes
the strongest one.

Design each selected candidate as its own short:
- `title`: a short, concrete title -- must be semantically the same
  promise as the hook event and the central payoff (never a mismatch
  between what the title promises and what the short actually delivers).
- `goal`: DISCOVERY (new-viewer reach), BRIDGE (payoff opens onto the
  parent's larger question), or SERIES (recognisably one piece of a
  larger series) -- pick whichever this candidate genuinely serves best.
- `central_insight`: the ONE thing this short teaches.
- `micro_arc`: contradiction_resolution / problem_fix / before_after /
  question_answer / prediction_explanation / myth_correction /
  mini_derivation -- may differ from the candidate's own suggestion if a
  different arc fits better.
- `hook`: the interesting thing happening in the first 0-3 seconds
  (`starts_at_seconds` must be within that window) -- a visual may carry
  it before narration does.
- `setup`: the minimum context needed (should read as roughly a 3-10
  second beat, not a preamble).
- `mechanism`: ONE mechanism, not a tour of several.
- `payoff_central`: the central payoff; `micro_payoffs` for any smaller
  ones along the way.
- `bridge`: PLATFORM_LINK / ONSCREEN / SPOKEN / NONE -- NONE is a valid
  and often correct choice; do not force a bridge that weakens the ending.
- `visual`: the dominant object, its states, and safe zones to keep clear
  of platform UI overlays.
- `source_beat_ids`: the exact beat id(s) (from the ones given) this
  design is actually built from -- never invent a beat id.

A derived short's every factual claim must trace back to the source
beats' own claims -- never introduce a technical fact the parent content
doesn't already support.
"""


class ShortPlanDraft(BaseModel):
    """A2s's actual output -- everything in a ShortPlan except `parent`,
    which Python assembles afterward from `source_beat_ids` (see module
    docstring)."""

    title: str = ""
    goal: ShortGoal = "DISCOVERY"
    central_insight: str
    micro_arc: MicroArc
    hook: HookEvent
    setup: str = ""
    mechanism: str = ""
    payoff_central: str = ""
    micro_payoffs: list[str] = Field(default_factory=list)
    bridge: ShortBridge = Field(default_factory=ShortBridge)
    visual: ShortVisual = Field(default_factory=ShortVisual)
    narration: ShortNarration = Field(default_factory=ShortNarration)
    source_beat_ids: list[str] = Field(default_factory=list)


class ShortPlanSelection(BaseModel):
    shorts: list[ShortPlanDraft] = Field(default_factory=list)


def _candidate_payload(candidate: ShortsCandidate) -> dict:
    return candidate.model_dump()


def _plan_hash(plan: StoryPlan) -> str:
    return "sha256:" + hashlib.sha256(plan.model_dump_json().encode("utf-8")).hexdigest()


def plan_shorts(
    candidates: list[ShortsCandidate], plan: StoryPlan, claims: list[Claim],
    story_lead: Agent, budget: BudgetCounter, run_id: str,
    shorts_count: int = DEFAULT_SHORTS_COUNT,
) -> list[ShortPlan]:
    if not candidates:
        return []

    known_beat_ids = {b.beat_id for b in plan.beats}
    payload = {
        "candidates": [_candidate_payload(c) for c in candidates],
        "shorts_count": shorts_count,
        "known_beat_ids": sorted(known_beat_ids),
    }
    selection = story_lead.run(
        pass_id="A2s", mode="SHORT_PLANNER", task_prompt=TASK_PROMPT,
        payload=payload, schema=ShortPlanSelection, budget=budget, estimated_usd=0.04,
    )

    final_plan_hash = _plan_hash(plan)
    claims_by_source_unit: dict[str, list[str]] = {}
    for c in claims:
        claims_by_source_unit.setdefault(c.source_unit, []).append(c.claim_id)

    plans: list[ShortPlan] = []
    for draft in selection.shorts[:shorts_count]:
        source_beat_ids = [bid for bid in draft.source_beat_ids if bid in known_beat_ids]
        if not source_beat_ids:
            continue  # every referenced beat was invalid -- nothing real to scope this short to
        source_unit_ids = {
            uid for bid in source_beat_ids for uid in next(b for b in plan.beats if b.beat_id == bid).source_unit_ids
        }
        allowed_fact_ids = sorted({cid for uid in source_unit_ids for cid in claims_by_source_unit.get(uid, [])})

        plans.append(ShortPlan(
            parent=ShortParent(
                run_id=run_id, final_plan_hash=final_plan_hash,
                source_beat_ids=source_beat_ids, allowed_fact_ids=allowed_fact_ids,
            ),
            title=draft.title, goal=draft.goal, central_insight=draft.central_insight,
            micro_arc=draft.micro_arc, hook=draft.hook, setup=draft.setup,
            mechanism=draft.mechanism, payoff_central=draft.payoff_central,
            micro_payoffs=draft.micro_payoffs, bridge=draft.bridge,
            visual=draft.visual, narration=draft.narration,
        ))
    return plans
