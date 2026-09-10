"""A1 -- source understanding (Story Lead / GPT strong) (plan §5, §8).

Answers "what does the source actually establish?" -- not yet a story
shape. Receives only VERIFIED/CONTEXT_DEPENDENT claims as established fact;
REJECTED/UNVERIFIED claims are shown too, but explicitly labelled, so A1
never treats a rejected or unconfirmed claim as ground truth (plan §6.5).
"""
from __future__ import annotations

from agents.base import Agent
from facts.models import AssumptionLedger, Claim, SourceUnit
from llm.budget import BudgetCounter

from .models import SourceBrief
from .narrative_digest import NarrativeDigest

TASK_PROMPT = """\
Build a SourceBrief from the source units and verified claim registry below.

- `topic` and `core_question` must reflect what THIS source actually teaches,
  not a generic label for the general subject area.
- `central_insight` is the single most valuable thing a viewer should walk
  away understanding -- state it as a real insight, not a topic name.
- `novelty_statement` must be concrete and specific: what does a practitioner
  at the stated audience level typically NOT know or get wrong, grounded in
  this source's own claims? A generic statement ("this topic is important")
  is not acceptable.
- `prerequisites`, `key_concepts`, and `concept_dependencies` must be
  evidenced by the source -- do not invent a prerequisite the source never
  actually relies on.
- Claims marked verification_status REJECTED must never inform any field --
  treat them as known-false. Claims marked UNVERIFIED should be treated with
  caution, not as established fact.
- `visual_opportunities` should name concrete, renderable moments the source
  actually supports (a mechanism, a comparison, a diagram-worthy structure),
  not generic suggestions.

If a `narrative_digest` is given, it is only a comprehension aid for a
long source (plan §6.3) -- the `units` and `claims` below remain the
actual source of truth; never state something the digest implies but the
units/claims don't actually support.
"""


def _unit_payload(unit: SourceUnit) -> dict:
    return {"id": unit.id, "heading": unit.heading, "text": unit.text, "equations": unit.equations}


def _claim_payload(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "type": claim.type,
        "importance": claim.importance, "verification_status": claim.verification_status,
        "source_unit": claim.source_unit,
    }


def understand_source(
    units: list[SourceUnit], claims: list[Claim], ledger: AssumptionLedger,
    story_lead: Agent, budget: BudgetCounter, audience: str = "",
    narrative_digest: NarrativeDigest | None = None,
) -> SourceBrief:
    payload = {
        "audience": audience,
        "units": [_unit_payload(u) for u in units],
        "claims": [_claim_payload(c) for c in claims],
        "assumption_ledger": ledger.model_dump(exclude_none=True),
        "narrative_digest": narrative_digest.model_dump() if narrative_digest else None,
    }
    return story_lead.run(
        pass_id="A1", mode="SOURCE_ANALYST", task_prompt=TASK_PROMPT,
        payload=payload, schema=SourceBrief, budget=budget, estimated_usd=0.08,
    )
