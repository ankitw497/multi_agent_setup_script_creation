"""Tests for facts/seeds.py -- S2a deterministic seeding (plan §6.3, §8).

All fixtures here are small synthetic examples, not the real corpus
(docs/corpus/ is gitignored working content) -- but every shape tested was
chosen because it mirrors a real pattern actually observed there (see the
docstring notes on each test), including a validated cross-check against
real source values.
"""
import pytest

from facts.models import AssumptionLedger, NumericClaim
from facts.seeds import find_formula_claims, parse_formula, seed_assumption_ledger


# ---- parse_formula: happy paths -------------------------------------------------

def test_parses_a_two_factor_formula_with_billion_suffix():
    """Real pattern: "7.61B × 2 bytes" -> matches the source's own claimed 15.2 GB
    (7.61e9 * 2 = 15.22e9 bytes decimal -- cross-checked against real data)."""
    r = parse_formula("7.61B × 2 bytes")
    assert r.parse_ok
    assert r.variables == {"f1": 7.61e9, "f2": 2.0}
    assert r.output_unit == "byte"
    assert r.computed_value == pytest.approx(15.22e9)
    assert r.tolerance == 0.01


def test_parses_a_long_multiplication_chain():
    """Real pattern: a KV-cache formula with six factors, no suffix on any of
    them -- cross-checked to match a real source's own ~0.12 GB claim."""
    r = parse_formula("28 × 2 × 4 × 128 × 2048 × 2 bytes")
    assert r.parse_ok
    assert r.computed_value == pytest.approx(117_440_512.0)
    assert r.output_unit == "byte"


def test_parses_million_and_thousand_suffixes():
    r = parse_formula("40.4M × 4 bytes")
    assert r.parse_ok
    assert r.variables["f1"] == pytest.approx(40.4e6)

    r2 = parse_formula("2K × 3")
    assert r2.parse_ok
    assert r2.variables["f1"] == 2000.0


def test_accepts_lowercase_and_asterisk_multiplication_signs():
    assert parse_formula("2 x 3 bytes").parse_ok
    assert parse_formula("2 * 3 bytes").parse_ok


def test_leading_tilde_is_treated_as_approximate_not_rejected():
    """Real pattern: "~40.4M × 2 bytes" -- a source author's own '~' means
    'approximately', not 'unparseable'. Parsed with a wider tolerance and a
    visible note, never silently treated as exact."""
    r = parse_formula("~40.4M × 2 bytes")
    assert r.parse_ok
    assert r.variables["f1"] == pytest.approx(40.4e6)
    assert r.tolerance == 0.05
    assert "approximate" in r.notes[0]


def test_no_trailing_unit_is_fine_too():
    r = parse_formula("3 × 4")
    assert r.parse_ok
    assert r.output_unit == ""
    assert r.computed_value == 12.0


# ---- parse_formula: fail-closed on ambiguity -------------------------------------

def test_rejects_additive_expressions():
    """Real pattern: "CUDA init + cuDNN workspace + allocator" -- an addition
    of named (non-numeric) things, never guessed at."""
    r = parse_formula("CUDA init + cuDNN workspace + allocator")
    assert not r.parse_ok
    assert r.notes


def test_rejects_a_factor_with_a_named_variable():
    """Real pattern: "batch × seq × hidden × layers, small multiplier" --
    named variables with no numeric value are not silently assumed to be 1."""
    r = parse_formula("batch × seq × hidden × layers")
    assert not r.parse_ok


def test_rejects_a_trailing_parenthetical_annotation():
    """Real pattern: "40.4M × 8 bytes (m + v)" -- the "(m + v)" annotation
    means something (first and second Adam moments) that isn't safe to
    strip automatically; correctly fails closed rather than guessing."""
    r = parse_formula("40.4M × 8 bytes (m + v)")
    assert not r.parse_ok


def test_rejects_empty_string():
    assert not parse_formula("").parse_ok


def test_rejects_a_bare_unit_with_no_factors():
    assert not parse_formula("bytes").parse_ok


# ---- seed_assumption_ledger: conservative, no renaming or scaling ---------------

def test_seed_ledger_passes_scalars_through_unchanged_and_lowercased():
    """Real pattern: JS constants HIDDEN=3584, LAYERS=28, PARAMS=7.61 --
    passed through as-is, NOT renamed to hidden_size/parameter_count and
    NOT scaled (PARAMS=7.61 stays 7.61, never guessed to mean 7.61e9)."""
    ledger = seed_assumption_ledger({"HIDDEN": 3584, "LAYERS": 28, "PARAMS": 7.61})
    dumped = ledger.model_dump(exclude_none=True)
    assert dumped["hidden"] == 3584
    assert dumped["layers"] == 28
    assert dumped["params"] == 7.61  # NOT 7.61e9 -- no scaling guess
    assert "parameter_count" not in dumped  # NOT auto-mapped to the typed field


def test_seed_ledger_skips_nested_objects_and_arrays():
    """A `modes` config object (nested dict) is structured data for
    find_formula_claims, not a ledger scalar -- must not leak in."""
    ledger = seed_assumption_ledger({
        "HIDDEN": 3584,
        "modes": {"inference": {"label": "Inference"}},
        "items": [1, 2, 3],
    })
    dumped = ledger.model_dump(exclude_none=True)
    assert "modes" not in dumped
    assert "items" not in dumped
    assert dumped["hidden"] == 3584


def test_seed_ledger_returns_a_valid_assumption_ledger_instance():
    ledger = seed_assumption_ledger({"model": "Qwen2.5-7B"})
    assert isinstance(ledger, AssumptionLedger)
    assert ledger.model == "Qwen2.5-7B"


def test_seed_ledger_handles_empty_literals():
    ledger = seed_assumption_ledger({})
    assert ledger.model is None


# ---- find_formula_claims: recursive, shape-agnostic -----------------------------

def test_finds_a_formula_at_any_nesting_depth():
    literals = {
        "modes": {
            "inference": {
                "rows": [
                    {"comp": "weights", "formula": "7.61B × 2 bytes", "size": "15.2 GB"},
                ]
            }
        }
    }
    claims, unparsed = find_formula_claims(literals)
    assert len(claims) == 1
    assert unparsed == []
    assert isinstance(claims[0], NumericClaim)
    assert claims[0].display_value == "15.2 GB"


def test_finds_multiple_formulas_across_sibling_and_nested_structures():
    literals = {
        "a": {"formula": "2 × 3"},
        "b": [{"formula": "4 × 5"}, {"formula": "not a formula at all + x"}],
    }
    claims, unparsed = find_formula_claims(literals)
    assert len(claims) == 2
    assert len(unparsed) == 1
    assert unparsed[0]["path"] == "b[1]"


def test_numeric_claim_ids_are_unique_and_sequential():
    literals = {"rows": [{"formula": "1 × 1"}, {"formula": "2 × 2"}, {"formula": "3 × 3"}]}
    claims, _ = find_formula_claims(literals)
    assert [c.numeric_claim_id for c in claims] == ["N001", "N002", "N003"]


def test_claim_id_prefix_is_configurable():
    literals = {"formula": "1 × 1"}
    claims, _ = find_formula_claims(literals, claim_id_prefix="SHORT_N")
    assert claims[0].numeric_claim_id == "SHORT_N001"


def test_no_formulas_anywhere_returns_empty_not_an_error():
    claims, unparsed = find_formula_claims({"a": 1, "b": [1, 2, {"c": 3}]})
    assert claims == []
    assert unparsed == []


def test_display_value_best_effort_falls_back_across_common_key_names():
    literals = {"x": {"formula": "1 × 1", "value": "1 byte"}}
    claims, _ = find_formula_claims(literals)
    assert claims[0].display_value == "1 byte"

    literals2 = {"x": {"formula": "1 × 1"}}  # no display key at all
    claims2, _ = find_formula_claims(literals2)
    assert claims2[0].display_value == ""
