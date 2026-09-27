"""Tests for facts/verify.py -- C2a (plan §6.5)."""
from facts.models import Claim, NumericClaim
from facts.verify import (
    ClaimVerdict, ClaimVerdicts, find_claims_with_no_verdict, verify_claims, verify_claims_with_llm,
    verify_numeric_linked_claims,
)
from facts.web_evidence import WebSearchResult


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


def test_initial_verdict_call_enables_real_web_search():
    """STORY_IMPROVEMENT_PLAN.md Phase 23: confirmed live that references_dir is always
    empty and web_backend is never passed by the real CLI, so a real, easily-verifiable
    claim had no path to ever become VERIFIED. Native Gemini web search on this call lets
    the model search for itself while forming its very first verdict."""
    claims = [make_claim("C001", claim_type="definition")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="matches source")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), __import__("pathlib").Path("/nonexistent"))

    assert review_lead.calls[0]["enable_web_search"] is True


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


# ---- web_backend fallback (plan §17, V1B) ----------------------------------------

class FakeWebBackend:
    def __init__(self, results: list[WebSearchResult]):
        self._results = results
        self.queries = []

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        self.queries.append(query)
        return self._results


def test_web_backend_is_never_tried_when_local_evidence_already_fulfilled(tmp_path):
    """Local references always go first -- the web is a fallback, never a
    replacement (plan §17's own ordering)."""
    (tmp_path / "spec.md").write_text("The A100 has 2039 GB/s of memory bandwidth.")
    claims = [make_claim("C001", "The A100 has 2039 GB/s of memory bandwidth.", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="A100 memory bandwidth spec 2039 GB/s",
        )]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="confirmed")]),
    ])
    web_backend = FakeWebBackend([WebSearchResult(title="x", snippet="x", url="https://en.wikipedia.org/wiki/x")])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path, web_backend=web_backend)
    assert web_backend.queries == []  # local evidence already fulfilled it -- web never queried


def test_web_backend_is_tried_for_requests_local_evidence_could_not_fulfil(tmp_path):
    claims = [make_claim("C001", "Attention scales scores by sqrt of dimension.", claim_type="mechanism")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="attention scaling by sqrt of dimension",
        )]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="confirmed by web reference")]),
    ])
    web_backend = FakeWebBackend([
        WebSearchResult(title="Attention scaling", snippet="attention scaling by sqrt of dimension", url="https://en.wikipedia.org/wiki/x"),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(
        claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path, web_backend=web_backend,
    )
    assert web_backend.queries == ["attention scaling by sqrt of dimension"]
    assert result[0].verification_status == "VERIFIED"
    assert result[0].evidence[0].kind == "EXTERNAL_REFERENCE"


def test_no_web_backend_given_keeps_v1a_exact_local_only_behavior(tmp_path):
    claims = [make_claim("C001", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="something with no local reference",
        )]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path)
    assert len(review_lead.calls) == 1  # no web_backend given -- exact V1A behavior, no 2nd call
    assert result[0].verification_status == "UNVERIFIED"


def test_a_claim_the_model_never_returned_a_verdict_for_is_not_silently_dropped():
    """2026-09-25: a missing verdict is now retried (MAX_VERDICT_RETRIES=2 extra attempts,
    3 total) -- this test confirms the ORIGINAL fallback still holds once retries are
    genuinely exhausted (all 3 attempts omit C002), not that retrying was removed."""
    claims = [make_claim("C001"), make_claim("C002")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok")]),
        ClaimVerdicts(verdicts=[]),
        ClaimVerdicts(verdicts=[]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                      __import__("pathlib").Path("/nonexistent"))
    assert len(result) == 2
    assert result[1].claim_id == "C002"
    assert result[1].verification_status == "UNVERIFIED"  # untouched default
    assert len(review_lead.calls) == 3  # first attempt + 2 retries, all for the shrinking missing set


def test_a_missing_verdict_is_recovered_on_retry():
    """The real new behavior: a batch that comes back count-incomplete (2026-09-25's
    confirmed live bug -- schema-valid, nowhere near the token ceiling, just missing
    entries) gets the missing claim re-asked, and a verdict that arrives on the retry is
    used, not discarded."""
    claims = [make_claim("C001"), make_claim("C002")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok")]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C002", verification_status="VERIFIED", reasoning="recovered")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                      __import__("pathlib").Path("/nonexistent"))

    by_id = {c.claim_id: c for c in result}
    assert by_id["C002"].verification_status == "VERIFIED"
    assert by_id["C002"].evidence[0].verdict == "recovered"
    assert len(review_lead.calls) == 2  # first attempt (missed C002) + one retry (recovered it)


def test_retry_only_re_asks_the_missing_claims_not_the_whole_batch():
    """A retry must never re-send a claim that already got a verdict -- confirms the
    second call's payload contains only the missing subset."""
    claims = [make_claim("C001"), make_claim("C002"), make_claim("C003")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[
            ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok"),
            ClaimVerdict(claim_id="C003", verification_status="VERIFIED", reasoning="ok"),
        ]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C002", verification_status="VERIFIED", reasoning="ok")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                            __import__("pathlib").Path("/nonexistent"))

    retry_payload_ids = [c["claim_id"] for c in review_lead.calls[1]["payload"]["claims"]]
    assert retry_payload_ids == ["C002"]


def test_initial_verdict_call_uses_a_generous_max_tokens():
    """Found live, 2026-09-16: enabling web search (see the test above) made verdicts
    verbose enough that a real 40-claim batch hit LiteLLMBackend's hardcoded 4096-token
    default and silently truncated, dropping 21/80 claims. Raised explicitly on this call."""
    claims = [make_claim("C001", claim_type="definition")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                            __import__("pathlib").Path("/nonexistent"))

    assert review_lead.calls[0]["max_tokens"] >= 8000


def test_re_verify_with_evidence_call_also_uses_a_generous_max_tokens(tmp_path):
    (tmp_path / "spec.md").write_text("The A100 has 80GB of HBM2e memory.")
    claims = [make_claim("C001", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm",
            needs_evidence="the A100's memory size",
        )]),
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="confirmed")]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), tmp_path)

    assert len(review_lead.calls) == 2
    assert review_lead.calls[1]["max_tokens"] >= 8000


# ---- find_claims_with_no_verdict -------------------------------------------------

def test_finds_a_claim_that_never_got_a_verdict():
    claims = [make_claim("C001"), make_claim("C002")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(claim_id="C001", verification_status="VERIFIED", reasoning="ok")]),
        ClaimVerdicts(verdicts=[]),
        ClaimVerdicts(verdicts=[]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                     __import__("pathlib").Path("/nonexistent"))

    assert find_claims_with_no_verdict(result) == ["C002"]


def test_a_legitimate_unverified_verdict_is_not_flagged():
    """A real UNVERIFIED verdict always carries evidence (the model's own reasoning,
    attached as a SOURCE entry) -- only a claim with BOTH fields still at Claim's own
    pristine defaults means no verdict was ever recorded, distinguishing a real "the model
    couldn't confirm this" outcome from "the model never even saw this claim's tail end"."""
    claims = [make_claim("C001", claim_type="implementation")]
    review_lead = FakeReviewLead([
        ClaimVerdicts(verdicts=[ClaimVerdict(
            claim_id="C001", verification_status="UNVERIFIED", reasoning="can't confirm from source",
        )]),
    ])
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    result = verify_claims_with_llm(claims, review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
                                     __import__("pathlib").Path("/nonexistent"))

    assert find_claims_with_no_verdict(result) == []


def test_a_verified_claim_is_not_flagged():
    assert find_claims_with_no_verdict([make_claim("C001").model_copy(update={
        "verification_status": "VERIFIED",
    })]) == []  # has no evidence attached in this bare model_copy, but isn't UNVERIFIED


def test_no_claims_is_an_empty_list():
    assert find_claims_with_no_verdict([]) == []


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
