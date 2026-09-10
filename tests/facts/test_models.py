"""Round-trip tests for facts/models.py (plan §5, §6.5)."""
from facts.models import AssumptionLedger, Claim, EvidenceRequest, NumericClaim, SourceUnit, VerificationEvidence

from tests.conftest import roundtrip, roundtrip_fixture


def test_source_unit_roundtrips():
    roundtrip_fixture(SourceUnit, "facts", "SourceUnit")


def test_source_unit_defaults_are_permissive():
    unit = SourceUnit(id="u1")
    assert unit.level == 1
    assert unit.structure_confidence == 1.0
    assert unit.equations == []


def test_claim_roundtrips_with_full_verification_fields():
    claim = roundtrip_fixture(Claim, "facts", "Claim")
    assert claim.importance == "CORE"
    assert claim.verification_status == "VERIFIED"
    assert claim.provenance_status == "SOURCE_EXPLICIT"


def test_claim_defaults_are_conservative():
    """A freshly extracted claim defaults to UNVERIFIED, not VERIFIED — the
    verified fact set is earned, never assumed (plan §6.5)."""
    claim = Claim(claim_id="C1", source_unit="u1", claim="x", type="definition")
    assert claim.verification_status == "UNVERIFIED"
    assert claim.importance == "SUPPORTING"
    assert claim.inference_kind == "NONE"


def test_claim_supports_derived_provenance_and_inference_kind():
    """A materialized derivation/inference is a real Claim with provenance back
    to its parents (plan §5 Appendix G #4 — a provenance graph, not an informal verdict)."""
    claim = roundtrip(
        Claim,
        {
            "claim_id": "C031", "source_unit": "u1", "claim": "154 additional tokens",
            "type": "numeric", "provenance_status": "DERIVED",
            "verification_status": "VERIFIED", "derived_from_claim_ids": ["C004", "C005"],
            "inference_kind": "DETERMINISTIC",
        },
    )
    assert claim.derived_from_claim_ids == ["C004", "C005"]
    assert claim.inference_kind == "DETERMINISTIC"


def test_verification_evidence_roundtrips():
    roundtrip(VerificationEvidence, {"kind": "CALCULATION", "ref": "N001", "excerpt": "", "verdict": "matches"})


def test_evidence_request_roundtrips():
    roundtrip(
        EvidenceRequest,
        {"claim_id": "C009", "what_would_settle_it": "the model's exact FFN width",
         "suggested_sources": ["official config.json"]},
    )


def test_numeric_claim_roundtrips_and_is_unit_aware():
    nc = roundtrip_fixture(NumericClaim, "facts", "NumericClaim")
    assert nc.numeric_claim_id != nc.claim_id  # Appendix G #12: distinct ids
    assert nc.output_unit == "byte"
    assert "memory_units" in nc.depends_on


def test_assumption_ledger_roundtrips_and_allows_source_declared_constants():
    ledger = roundtrip_fixture(AssumptionLedger, "facts", "AssumptionLedger")
    assert ledger.model == "Qwen2.5-7B"
    # extra="allow": source-declared constants beyond the typed core fields
    assert ledger.model_dump()["hidden_size"] == 3584
