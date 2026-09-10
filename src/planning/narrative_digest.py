"""S1 -- narrative digest (Worker/Haiku, subscription lane) (plan §6.3, §8).

Only runs when the source exceeds ~12k tokens (plan §6.3) -- every real
source tested so far (video-01, ~3300 words) is well under this, so this
pass is usually skipped entirely. It is a comprehension aid ONLY: A1 still
receives the full claim registry and source units directly regardless
(plan §6.3's whole point -- "a detail can no longer vanish because a
summarizer dropped it before the claim pass ran"), so this digest can
never become the thing A1 or A2 actually reasons from.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import SourceUnit
from llm.budget import BudgetCounter

# ~12k tokens (plan §6.3), approximated at ~0.75 words/token -- consistent
# with how the rest of this codebase reasons in words, not tokens (e.g.
# PLANNING_WPM-based word budgets), so this stays a rough trigger, not a
# precision measurement.
NARRATIVE_DIGEST_WORD_THRESHOLD = 9000

TASK_PROMPT = """\
Summarize the narrative ARC of this source in plain prose: what it covers
and in what order, and how each part sets up the next -- not a bullet list
of facts (the claim registry already has those; this digest exists purely
to help a planner hold the whole source's shape in mind, never to replace
it as a source of truth). Keep the summary itself under 400 words
regardless of source length. Also list the source unit ids in the order
they actually build on each other, which may differ from document order if
the source itself is non-linear.
"""


class NarrativeDigest(BaseModel):
    summary: str
    section_order: list[str] = Field(default_factory=list)  # source_unit ids, in narrative order


def needs_narrative_digest(units: list[SourceUnit]) -> bool:
    total_words = sum(len(u.text.split()) for u in units)
    return total_words > NARRATIVE_DIGEST_WORD_THRESHOLD


def _unit_payload(unit: SourceUnit) -> dict:
    return {"id": unit.id, "heading": unit.heading, "text": unit.text}


def build_narrative_digest(units: list[SourceUnit], worker: Agent, budget: BudgetCounter | None = None) -> NarrativeDigest:
    payload = {"source_units": [_unit_payload(u) for u in units]}
    return worker.run(
        pass_id="S1", mode="NARRATIVE_DIGEST", task_prompt=TASK_PROMPT,
        payload=payload, schema=NarrativeDigest, budget=budget, timeout_s=300,
    )
