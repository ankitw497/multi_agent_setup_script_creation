"""Tests for facts/normalize.py -- S2c (plan §6.3, §9 traceability)."""
from facts.models import Claim, NumericClaim
from facts.normalize import dedupe_claims, link_numeric_claims, normalize_number


# ---- normalize_number: the exact plan §9 traceability example -------------------

def test_the_three_canonical_forms_from_the_plan_all_normalize_equal():
    """plan §9: "175B" <-> "175 billion" <-> "175,000,000,000" must compare
    equal under normalized comparison, or an invented statistic slips past."""
    assert normalize_number("175B") == normalize_number("175 billion") == normalize_number("175,000,000,000")
    assert normalize_number("175B") == 1.75e11


def test_million_and_thousand_suffixes():
    assert normalize_number("40.4M") == 40_400_000.0
    assert normalize_number("2K") == 2000.0
    assert normalize_number("2 thousand") == 2000.0


def test_bare_number_with_a_byte_unit_normalizes_to_its_own_magnitude():
    """The GB suffix is a physical unit, not a magnitude word -- normalize_number
    only cares about the number itself; unit conversion is a separate concern."""
    assert normalize_number("175 GB") == 175.0


def test_commas_are_stripped():
    assert normalize_number("175,000,000,000") == 1.75e11


def test_case_insensitive():
    assert normalize_number("7.61b") == normalize_number("7.61B") == 7.61e9


def test_unparseable_returns_none():
    assert normalize_number("approximately a lot") is None
    assert normalize_number("") is None


# ---- dedupe_claims ---------------------------------------------------------------

def make_claim(claim_id: str, text: str, numbers=None) -> Claim:
    return Claim(claim_id=claim_id, source_unit="u1", claim=text, type="definition", numbers=numbers or [])


def test_dedupe_keeps_the_first_occurrence_and_reports_the_dropped_id():
    claims = [
        make_claim("C001", "Attention divides by the square root of d_k."),
        make_claim("C002", "attention divides by the square root of d_k."),  # same, different case
        make_claim("C003", "A different claim entirely."),
    ]
    deduped, dropped = dedupe_claims(claims)
    assert [c.claim_id for c in deduped] == ["C001", "C003"]
    assert dropped == ["C002"]


def test_dedupe_is_a_no_op_when_nothing_repeats():
    claims = [make_claim("C001", "x"), make_claim("C002", "y")]
    deduped, dropped = dedupe_claims(claims)
    assert len(deduped) == 2
    assert dropped == []


def test_dedupe_ignores_whitespace_differences():
    claims = [make_claim("C001", "a   b   c"), make_claim("C002", "a b c")]
    deduped, dropped = dedupe_claims(claims)
    assert len(deduped) == 1
    assert dropped == ["C002"]


# ---- link_numeric_claims ----------------------------------------------------------

def make_numeric(numeric_claim_id: str, variables: dict, claim_id=None) -> NumericClaim:
    return NumericClaim(
        numeric_claim_id=numeric_claim_id, claim_id=claim_id,
        expression=" * ".join(variables), variables=variables,
    )


def test_links_a_numeric_claim_to_the_semantic_claim_that_mentions_its_value():
    claims = [make_claim("C001", "The model has 7.61 billion parameters.", numbers=["7.61 billion"])]
    numeric = [make_numeric("N001", {"f1": 7.61e9, "f2": 2.0})]  # computes to 1.522e10

    # The claim's number (7.61e9) doesn't match the numeric claim's PRODUCT
    # (1.522e10) -- no link expected here; see the matching-product test below.
    linked = link_numeric_claims(claims, numeric)
    assert linked[0].claim_id is None


def test_links_when_the_claims_number_matches_the_computed_product():
    claims = [make_claim("C001", "That's 15.2 billion bytes of weights.", numbers=["15.2 billion"])]
    numeric = [make_numeric("N001", {"f1": 7.6e9, "f2": 2.0})]  # 7.6e9 * 2 = 1.52e10

    linked = link_numeric_claims(claims, numeric, tolerance=0.01)
    assert linked[0].claim_id == "C001"


def test_does_not_overwrite_an_already_linked_numeric_claim():
    claims = [make_claim("C001", "x", numbers=["999"])]
    numeric = [make_numeric("N001", {"f1": 999.0}, claim_id="C999")]  # already linked elsewhere

    linked = link_numeric_claims(claims, numeric)
    assert linked[0].claim_id == "C999"  # untouched


def test_no_match_leaves_claim_id_none_without_raising():
    claims = [make_claim("C001", "unrelated", numbers=["1"])]
    numeric = [make_numeric("N001", {"f1": 42.0})]

    linked = link_numeric_claims(claims, numeric)
    assert linked[0].claim_id is None
    assert len(linked) == 1  # nothing lost
