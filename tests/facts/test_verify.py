"""Tests for facts/verify.py -- C2a (plan §6.5)."""
from facts.models import Claim, NumericClaim
from facts.verify import (
    ClaimVerdict, ClaimVerdicts, verify_claims, verify_claims_with_llm, verify_numeric_linked_claims,
)


def make_claim(claim_id, text="x", numbers=None, claim_type="numeric") -> Claim:
    return Claim(claim_id=claim_id, source_unit="u1", claim=text, type=claim_type, numbers=numbers or [])


def make_numeric(claim_id, variables) -> NumericClaim:
    return NumericClaim(numeric_claim_id=f"N_{claim_id}", claim_id=claim_id, expression="x", variables=variables)


class FakeReviewLead:
    def __init__(self, responses: list[ClaimVerdicts]):
        self._responses = list(responses)
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


# ---- verify_numeric_linked_claims: pure Python, no LLM ---------------------------

def test_matching_computed_value_verifies_the_claim():
    claims = [make_claim("C001", "That's 30.44 billion bytes.", numbers=["30.44 billion"])]
    numeric = [make_numeric("C001", {"f1": 7.61e9, "f2": 4.0})]  # = 3.044e10

    resolved, remaining = verify_numeric_linked_claims(claims, numeric)
    assert remaining == []
    assert resolved[0].verification_status == "VERIFIED"
    assert resolved[0].evidence[0].kind == "CALCULATION"


def test_mismatching_computed_value_rejects_the_claim():
    claims = [make_claim("C001", "That's 99 billion bytes.", numbers=["99 billion"])]
    numeric = [make_numeric("C001", {"f1": 7.61e9, "f2": 4.0})]  # = 3.044e10, not 99e9

    resolved, remaining = verify_numeric_linked_claims(claims, numeric)
    assert resolved[0].verification_status == "REJECTED"


def test_a_claim_with_no_linked_numeric_claim_passes_through_untouched():
    claims = [make_claim("C001", "Bahdanau et al. published in 2014.", claim_type="historical")]
    resolved, remaining = verify_numeric_linked_claims(claims, [])
    assert resolved == []
    assert remaining == claims


# ---- verify_claims_with_llm: the evidence-request loop ---------------------------

def test_all_verified_needs_only_one_call_no_evidence_loop():
    claims = [make_claim("C001", claim_type="definition")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="matches source")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_references := __import__("pathlib").Path("/nonexistent"))
    assert len(review_lead.calls) == 1  # no second pass -- nothing needed evidence
    assert result[0].verification_status == "VERIFIED"


def test_unverified_with_no_local_evidence_stays_unverified_without_a_second_call(tmp_path):
    claims = [make_claim("C001", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="the exact GPU model's memory bandwidth",
        )]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path)
    assert len(review_lead.calls) == 1  # empty references dir -> nothing fulfilled -> no 2nd call
    assert result[0].verification_status == "UNVERIFIED"


def test_unverified_claim_gets_re_verified_once_local_evidence_is_found(tmp_path):
    (tmp_path / "spec.md").write_text("The A100 has 80GB of HBM2e memory and 2039 GB/s of bandwidth.")
    claims = [make_claim("C001", "The A100 has 2039 GB/s of memory bandwidth.", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="A100 memory bandwidth spec 2039 GB/s HBM2e",
        )]),
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="VERIFIED", reasoning="confirmed by the spec sheet",
        )]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path)
    assert len(review_lead.calls) == 2
    assert result[0].verification_status == "VERIFIED"
    assert result[0].evidence[0].kind == "EXTERNAL_REFERENCE"


def test_batches_claims_by_batch_size():
    claims = [make_claim(f"C{i:03d}") for i in range(5)]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id=f"C{i:03d}", verification_status="VERIFIED", reasoning="ok") for i in range(2)]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id=f"C{i:03d}", verification_status="VERIFIED", reasoning="ok") for i in range(2, 4)]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C004", verification_status="VERIFIED", reasoning="ok")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                      __import__("pathlib").Path("/nonexistent"), batch_size=2)
    assert len(review_lead.calls) == 3
    assert len(result) == 5


def test_a_claim_the_model_never_returned_a_verdict_for_is_not_silently_dropped():
    claims = [make_claim("C001"), make_claim("C002")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                      __import__("pathlib").Path("/nonexistent"))
    assert len(result) == 2
    assert result[1].claim_id == "C002"
    assert result[1].verification_status == "UNVERIFIED"  # untouched default


# ---- verify_claims: full pipeline, arithmetic + LLM together --------------------

def test_verify_claims_routes_numeric_linked_to_python_and_rest_to_llm():
    numeric_claim = make_claim("C001", "That's 15.22 billion bytes.", numbers=["15.22 billion"])
    text_claim = make_claim("C002", "This is a historical claim.", claim_type="historical")
    numeric = [make_numeric("C001", {"f1": 7.61e9, "f2": 2.0})]

    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C002", verification_status="VERIFIED", reasoning="ok")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims(
        [numeric_claim, text_claim], numeric, review_lead,
        BudgetCounter(tier=DEFAULT_TIERS["longform"]), __import__("pathlib").Path("/nonexistent"),
    )
    by_id = {c.claim_id: c for c in result}
    assert by_id["C001"].verification_status == "VERIFIED"
    assert by_id["C001"].evidence[0].kind == "CALCULATION"
    assert by_id["C002"].verification_status == "VERIFIED"
    assert by_id["C002"].evidence[0].kind == "SOURCE"
    assert len(review_lead.calls) == 1  # only the non-numeric claim went to the LLM


def test_verify_claims_with_all_claims_numeric_linked_never_calls_the_llm():
    claim = make_claim("C001", "15.22 billion", numbers=["15.22 billion"])
    numeric = [make_numeric("C001", {"f1": 7.61e9, "f2": 2.0})]
    review_lead = FakeReviewLead([])  # would raise IndexError if called

    result = verify_claims(
        [claim], numeric, review_lead,
        __import__("llm.budget", fromlist=["BudgetCounter"]).BudgetCounter(
            tier=__import__("llm.budget", fromlist=["DEFAULT_TIERS"]).DEFAULT_TIERS["longform"]
        ),
        __import__("pathlib").Path("/nonexistent"),
    )
    assert result[0].verification_status == "VERIFIED"
    assert review_lead.calls == []
