"""S2b -- claim extraction over ALL source units, batched, on the Worker (Haiku) (plan §6.3, §8).

The LLM does judgement (which sentences are factual claims, what type/mode/
stage/scope/importance they have); Python owns bookkeeping (claim ids are
assigned here, globally unique across batches, never trusted from the
model -- removes a whole class of id-collision bugs by construction).

Everything here defaults to UNVERIFIED/SOURCE_EXPLICIT -- extraction only
establishes "the source asserts this" (plan §6.5); C2a decides what's true.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim, ClaimImportance, ClaimMode, ClaimScope, ClaimStage, ClaimType, SourceUnit

DEFAULT_BATCH_WORDS = 6000  # plan §6.3: "batched by unit group", not one call per unit

TASK_PROMPT = """\
Extract every discrete factual claim from the source units below.

A claim is one specific, checkable assertion: a definition, a mechanism, a
causal relationship, a number, a complexity statement, a comparison, an
implementation detail, a historical fact, or a recommendation.

Rules:
- Extract ONLY what the text actually asserts. Never infer, extrapolate, or
  add a claim the text does not support.
- Tag each claim's `source_unit` with the exact unit id it came from.
- Set `type` to the single best-fitting category.
- Set `mode` (INFERENCE/FULL_TRAINING/LORA/QLORA), `stage` (prefill/decode/
  both), and `scope` (UNIVERSAL/MODEL_SPECIFIC/EXAMPLE_SPECIFIC/
  IMPLEMENTATION_DEPENDENT) ONLY when the text is actually about that
  distinction -- leave them null otherwise. Do not guess.
- Set `importance` to CORE only for claims essential to the central
  explanation; SUPPORTING for claims that matter but aren't load-bearing;
  OPTIONAL for incidental detail.
- List any concrete numbers the claim depends on in `numbers`, and any named
  assumptions (e.g. "sequence_length", "batch_size") in `assumptions`.
- Do not assign an id -- ids are assigned separately.
"""


class ExtractedClaim(BaseModel):
    source_unit: str
    claim: str
    type: ClaimType
    numbers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    mode: ClaimMode | None = None
    stage: ClaimStage | None = None
    scope: ClaimScope | None = None
    importance: ClaimImportance = "SUPPORTING"


class ExtractedClaims(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


def _batch_units(units: list[SourceUnit], batch_words: int) -> list[list[SourceUnit]]:
    batches: list[list[SourceUnit]] = []
    current: list[SourceUnit] = []
    current_words = 0
    for unit in units:
        words = len(unit.text.split())
        if current and current_words + words > batch_words:
            batches.append(current)
            current, current_words = [], 0
        current.append(unit)
        current_words += words
    if current:
        batches.append(current)
    return batches


def _unit_payload(unit: SourceUnit) -> dict:
    return {
        "id": unit.id, "heading": unit.heading, "text": unit.text,
        "equations": unit.equations, "callouts": unit.callouts,
        "code": unit.code, "numbers": unit.numbers,
    }


def extract_claims(
    units: list[SourceUnit], worker: Agent, batch_words: int = DEFAULT_BATCH_WORDS,
) -> list[Claim]:
    claims: list[Claim] = []
    counter = 0

    for batch in _batch_units(units, batch_words):
        payload = {"units": [_unit_payload(u) for u in batch]}
        extracted = worker.run(
            pass_id="S2b", mode="CLAIM_EXTRACT", task_prompt=TASK_PROMPT,
            payload=payload, schema=ExtractedClaims,
        )
        for ec in extracted.claims:
            counter += 1
            claims.append(
                Claim(
                    claim_id=f"C{counter:03d}",
                    source_unit=ec.source_unit,
                    claim=ec.claim,
                    type=ec.type,
                    numbers=ec.numbers,
                    assumptions=ec.assumptions,
                    mode=ec.mode,
                    stage=ec.stage,
                    scope=ec.scope,
                    importance=ec.importance,
                    provenance_status="SOURCE_EXPLICIT",
                    verification_status="UNVERIFIED",
                )
            )
    return claims
