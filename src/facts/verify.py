"""C2a -- source verification, before planning (plan §6.5). Runs once per source; cacheable.

Two paths, matching what kind of evidence actually settles a claim:

  numeric-linked claims  -> Python arithmetic IS the evidence (no LLM)
  everything else        -> Review Lead (Gemini, strong tier) judges it,
                             and may request evidence the Evidence Broker
                             tries to fulfil from local references (V1A)

"Technically verified" means exactly what the attached evidence supports --
never "Gemini agrees with the uploaded HTML" (plan §6.5).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter

from .evidence import fulfil_evidence_requests
from .models import Claim, EvidenceRequest, NumericClaim, VerificationEvidence
from .normalize import normalize_number
from .web_evidence import WebSearchBackend, fulfil_evidence_requests_via_web

DEFAULT_BATCH_SIZE = 40  # claims per LLM call; V1A sources fit in one batch

TASK_PROMPT = """\
You are verifying technical claims extracted from a video script source, BEFORE
any story is planned around them. For each claim below, decide:

- VERIFIED: the claim is directly supported by its cited source context AND is
  technically correct as a general or well-established fact.
- CONTEXT_DEPENDENT: the claim is true only under specific conditions/assumptions
  that are not fully stated -- note what those conditions are in `reasoning`.
- REJECTED: the claim contradicts the source context, or is technically wrong.
- UNVERIFIED: you cannot confirm this from the source or general technical
  knowledge. If a specific reference (a model card, a spec sheet, official
  documentation) would settle it, describe exactly what in `needs_evidence`.
  If nothing would help (it's just an unprovable value judgement), leave
  `needs_evidence` null.

Be adversarial, not charitable. Do not assume a claim is correct because it
sounds plausible or is commonly repeated -- verify it against what you actually
know and against the source context given.
"""

RE_VERIFY_WITH_EVIDENCE_PROMPT = """\
You previously marked each of these claims UNVERIFIED and asked for evidence.
That evidence has now been found (or, if absent, none was available). Re-decide
the verification_status for each, using this evidence: VERIFIED if it confirms
the claim, CONTEXT_DEPENDENT if it confirms it only under conditions, REJECTED
if it contradicts the claim, or UNVERIFIED again if the evidence is present but
inconclusive. Never leave `needs_evidence` set on this pass.
"""

VerificationStatusLiteral = Literal["VERIFIED", "CONTEXT_DEPENDENT", "UNVERIFIED", "REJECTED"]


class ClaimVerdict(BaseModel):
    claim_id: str
    verification_status: VerificationStatusLiteral
    reasoning: str
    needs_evidence: str | None = None


class ClaimVerdicts(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)


def _close(a: float, b: float, tolerance: float) -> bool:
    if b == 0:
        return abs(a - b) < tolerance
    return abs(a - b) / abs(b) <= tolerance


def verify_numeric_linked_claims(
    claims: list[Claim], numeric_claims: list[NumericClaim],
) -> tuple[list[Claim], list[Claim]]:
    """Claims linked to a NumericClaim (plan §6.3 S2c) are verified by Python
    arithmetic alone -- no LLM call, no judgement, just a computed product
    compared against what the claim actually says. Returns
    (resolved_claims, remaining_claims_for_llm_review)."""
    numeric_by_claim_id = {nc.claim_id: nc for nc in numeric_claims if nc.claim_id}
    resolved: list[Claim] = []
    remaining: list[Claim] = []

    for claim in claims:
        nc = numeric_by_claim_id.get(claim.claim_id)
        if nc is None:
            remaining.append(claim)
            continue

        computed = 1.0
        for v in nc.variables.values():
            computed *= v

        matches = any(
            (n := normalize_number(raw)) is not None and _close(n, computed, nc.tolerance)
            for raw in claim.numbers
        )
        status: VerificationStatusLiteral = "VERIFIED" if matches else "REJECTED"
        verdict_text = (
            f"computed {computed:,.4g} {nc.output_unit} from '{nc.expression}' "
            f"{'matches' if matches else 'does NOT match'} the claim's stated number(s)"
        )
        resolved.append(
            claim.model_copy(update={
                "verification_status": status,
                "evidence": [VerificationEvidence(
                    kind="CALCULATION", ref=nc.numeric_claim_id, excerpt=nc.expression, verdict=verdict_text,
                )],
            })
        )
    return resolved, remaining


def _batch_claims(claims: list[Claim], batch_size: int) -> list[list[Claim]]:
    return [claims[i : i + batch_size] for i in range(0, len(claims), batch_size)]


def _claim_payload(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "type": claim.type,
        "numbers": claim.numbers, "assumptions": claim.assumptions,
        "source_unit": claim.source_unit,
    }


def _apply_verdict(claim: Claim, verdict: ClaimVerdict, evidence: list[VerificationEvidence]) -> Claim:
    return claim.model_copy(update={"verification_status": verdict.verification_status, "evidence": evidence})


def verify_claims_with_llm(
    claims: list[Claim], review_lead: Agent, budget: BudgetCounter,
    references_dir: Path, batch_size: int = DEFAULT_BATCH_SIZE,
    web_backend: WebSearchBackend | None = None,
) -> list[Claim]:
    """The LLM path for claims arithmetic can't settle. Runs the two-pass
    evidence loop: verdicts -> evidence requests -> broker -> re-verdict on
    whatever was actually found. If nothing was found, nothing is re-asked
    (no wasted call) and those claims stay UNVERIFIED with their request
    visible for the report (plan §6.5).

    `web_backend` (plan §17, V1B) is tried only for requests local
    `references_dir` couldn't fulfil -- local evidence is free and instant,
    so it always goes first; the web is a fallback, not a replacement.
    Omit it (the default) to keep V1A's exact local-only behavior."""
    resolved: dict[str, Claim] = {}
    pending_requests: list[EvidenceRequest] = []
    claims_by_id = {c.claim_id: c for c in claims}

    for batch in _batch_claims(claims, batch_size):
        payload = {"claims": [_claim_payload(c) for c in batch]}
        verdicts = review_lead.run(
            pass_id="C2a", mode="VERIFY_SOURCE_CLAIMS", task_prompt=TASK_PROMPT,
            payload=payload, schema=ClaimVerdicts, budget=budget, estimated_usd=0.05,
        )
        for verdict in verdicts.verdicts:
            claim = claims_by_id.get(verdict.claim_id)
            if claim is None:
                continue
            evidence = [VerificationEvidence(kind="SOURCE", ref=claim.source_unit, excerpt="", verdict=verdict.reasoning)]
            resolved[claim.claim_id] = _apply_verdict(claim, verdict, evidence)
            if verdict.verification_status == "UNVERIFIED" and verdict.needs_evidence:
                pending_requests.append(EvidenceRequest(claim_id=claim.claim_id, what_would_settle_it=verdict.needs_evidence))

    if pending_requests:
        fulfilled = fulfil_evidence_requests(pending_requests, references_dir)
        if web_backend is not None:
            still_pending = [r for r in pending_requests if r.claim_id not in fulfilled]
            if still_pending:
                fulfilled = {**fulfilled, **fulfil_evidence_requests_via_web(still_pending, web_backend)}
        if fulfilled:
            re_verify_batch = [claims_by_id[cid] for cid in fulfilled if cid in claims_by_id]
            payload = {
                "claims": [_claim_payload(c) for c in re_verify_batch],
                "evidence": {cid: ev.model_dump() for cid, ev in fulfilled.items()},
            }
            verdicts = review_lead.run(
                pass_id="C2a", mode="VERIFY_WITH_EVIDENCE", task_prompt=RE_VERIFY_WITH_EVIDENCE_PROMPT,
                payload=payload, schema=ClaimVerdicts, budget=budget, estimated_usd=0.03,
            )
            for verdict in verdicts.verdicts:
                claim = claims_by_id.get(verdict.claim_id)
                if claim is None:
                    continue
                resolved[claim.claim_id] = _apply_verdict(claim, verdict, [fulfilled[claim.claim_id]])

    # Anything neither arithmetic-resolved nor LLM-resolved (shouldn't normally
    # happen, but never drop a claim silently) stays exactly as it arrived.
    return [resolved.get(c.claim_id, c) for c in claims]


def verify_claims(
    claims: list[Claim], numeric_claims: list[NumericClaim], review_lead: Agent,
    budget: BudgetCounter, references_dir: Path, web_backend: WebSearchBackend | None = None,
) -> list[Claim]:
    """The full C2a entry point: arithmetic first, LLM for the rest."""
    arithmetic_resolved, remaining = verify_numeric_linked_claims(claims, numeric_claims)
    llm_resolved = (
        verify_claims_with_llm(remaining, review_lead, budget, references_dir, web_backend=web_backend)
        if remaining else []
    )
    by_id = {c.claim_id: c for c in arithmetic_resolved + llm_resolved}
    return [by_id.get(c.claim_id, c) for c in claims]
