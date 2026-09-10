"""Source facts and the verified fact set (plan §5, §6.5).

SourceUnit is what extraction produces. Claim is what the source ASSERTS —
never treated as truth on its own (that distinction, §6.5, is the point of
`provenance_status` vs `verification_status`). NumericClaim and
AssumptionLedger are the deterministic-verification substrate (plan §6.2,
§9 Factual gate).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Claim.type — design doc §17's nine claim types.
ClaimType = Literal[
    "definition", "mechanism", "causal", "numeric", "complexity",
    "comparison", "implementation", "historical", "recommendation",
]

ClaimMode = Literal["INFERENCE", "FULL_TRAINING", "LORA", "QLORA"]
ClaimStage = Literal["prefill", "decode", "both"]
ClaimScope = Literal["UNIVERSAL", "MODEL_SPECIFIC", "EXAMPLE_SPECIFIC", "IMPLEMENTATION_DEPENDENT"]
ClaimImportance = Literal["CORE", "SUPPORTING", "OPTIONAL"]  # plan §5.1 grounding policy
ProvenanceStatus = Literal["SOURCE_EXPLICIT", "SOURCE_INFERRED", "DERIVED", "EXTERNAL"]
VerificationStatus = Literal["UNVERIFIED", "VERIFIED", "CONTEXT_DEPENDENT", "REJECTED"]
InferenceKind = Literal["NONE", "DETERMINISTIC", "EXPLANATORY"]
EvidenceKind = Literal["SOURCE", "CALCULATION", "EXTERNAL_REFERENCE"]


class SourceUnit(BaseModel):
    """One extracted content unit (plan §6.1-§6.2). Structure, not interpretation."""

    id: str
    heading: str = ""
    level: int = Field(ge=1, le=6, default=1)
    text: str = ""
    equations: list[str] = Field(default_factory=list)
    diagrams: list[str] = Field(default_factory=list)
    callouts: list[str] = Field(default_factory=list)
    code: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    js_literals: list[str] = Field(default_factory=list)  # plan §6.2, AST-parsed, never executed
    dom_path: str = ""
    structure_confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class VerificationEvidence(BaseModel):
    """One piece of evidence backing a claim's verification_status (plan §5, §6.5)."""

    kind: EvidenceKind
    ref: str = ""  # a source_unit id, a calculation description, or an external reference id
    excerpt: str = ""
    verdict: str = ""  # free text: what this evidence established


class EvidenceRequest(BaseModel):
    """C2a's request for evidence it couldn't resolve itself (plan §6.5).

    Fulfilled by the Evidence Broker (orchestration component, not an agent),
    not the LLM. An unfulfilled request leaves the claim UNVERIFIED.
    """

    claim_id: str
    what_would_settle_it: str
    suggested_sources: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    """What the source asserts (plan §5, §6.5) — NOT what has been verified true.

    `provenance_status` says how directly the source supports this claim;
    `verification_status` says what C2a/C2b established about it, with
    `evidence` backing that verdict. §5.1's grounding policy reads
    `importance` + `verification_status` together to decide whether a
    sentence may narrate this claim at all.
    """

    claim_id: str
    source_unit: str  # SourceUnit.id this claim was extracted from
    claim: str
    type: ClaimType
    numbers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)  # AssumptionLedger keys this depends on
    mode: ClaimMode | None = None
    stage: ClaimStage | None = None
    scope: ClaimScope | None = None

    importance: ClaimImportance = "SUPPORTING"
    provenance_status: ProvenanceStatus = "SOURCE_EXPLICIT"
    verification_status: VerificationStatus = "UNVERIFIED"
    evidence: list[VerificationEvidence] = Field(default_factory=list)

    derived_from_claim_ids: list[str] = Field(default_factory=list)
    inference_kind: InferenceKind = "NONE"


class NumericClaim(BaseModel):
    """A unit-aware, deterministically evaluable numeric assertion (plan §5, §6.2, Appendix G #18).

    `expression`/`variables`/`output_unit` are what verification/hard/numeric.py
    evaluates; `display_value`/`display_unit` are what the source or narration
    actually says, compared against the computed value within `tolerance`.
    Unit conversion (e.g. GB vs GiB) happens in formatting code using
    AssumptionLedger.memory_units — never inside the expression itself.
    """

    numeric_claim_id: str  # distinct from claim_id (Appendix G #12)
    claim_id: str | None = None  # parent Claim, if this number backs one
    scene_id: str | None = None
    expression: str  # e.g. "params * bytes_per_param"
    variables: dict[str, float] = Field(default_factory=dict)
    output_unit: str = ""
    display_value: str = ""
    display_unit: str = ""
    tolerance: float = 0.01
    rounding: str | None = None
    depends_on: list[str] = Field(default_factory=list)  # AssumptionLedger keys


class AssumptionLedger(BaseModel):
    """Typed scalars + source-declared constants everything derives from (plan §5, §6.2).

    Deliberately loose beyond the documented core fields (`extra="allow"`):
    a source's own constants (HIDDEN, LAYERS, KV_HEADS, ...) are seeded
    directly from JS literals per model, and the exact set of scalars is
    source-dependent.
    """

    model_config = {"extra": "allow"}

    model: str | None = None
    parameter_count: float | None = None
    weight_dtype: str | None = None
    bytes_per_weight: float | None = None
    batch_size: int | None = None
    sequence_length: int | None = None
    memory_units: Literal["GB_decimal", "GiB_binary"] | None = None
