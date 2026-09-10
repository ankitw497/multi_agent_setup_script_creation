"""Tests for facts/claim_extract.py -- S2b (plan §6.3, §8)."""
import pytest

from facts.claim_extract import ExtractedClaims, _batch_units, extract_claims
from facts.models import SourceUnit


class FakeWorker:
    """Returns one canned ExtractedClaims per call, in call order."""

    def __init__(self, responses: list[ExtractedClaims]):
        self._responses = list(responses)
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def make_unit(id_: str, words: int) -> SourceUnit:
    return SourceUnit(id=id_, text=" ".join(["word"] * words))


def test_batches_by_word_count_not_unit_count():
    units = [make_unit("a", 4000), make_unit("b", 4000), make_unit("c", 100)]
    batches = _batch_units(units, batch_words=6000)
    assert [u.id for u in batches[0]] == ["a"]
    assert [u.id for u in batches[1]] == ["b", "c"]


def test_a_single_small_source_is_one_batch():
    units = [make_unit(f"u{i}", 100) for i in range(11)]  # like the real video-01: 11 units, ~3300 words
    batches = _batch_units(units, batch_words=6000)
    assert len(batches) == 1


def test_extract_claims_assigns_globally_unique_sequential_ids():
    """Ids are assigned by Python, never trusted from the model -- this is
    what makes them collision-free across batches by construction."""
    worker = FakeWorker([
        ExtractedClaims(claims=[
            {"source_unit": "u1", "claim": "x", "type": "definition"},
            {"source_unit": "u1", "claim": "y", "type": "mechanism"},
        ]),
    ])
    claims = extract_claims([make_unit("u1", 10)], worker, batch_words=6000)
    assert [c.claim_id for c in claims] == ["C001", "C002"]


def test_extract_claims_defaults_to_unverified_and_source_explicit():
    """Extraction only establishes what the source asserts -- verification
    is C2a's job, never assumed true here (plan §6.5)."""
    worker = FakeWorker([
        ExtractedClaims(claims=[{"source_unit": "u1", "claim": "x", "type": "numeric"}]),
    ])
    claims = extract_claims([make_unit("u1", 10)], worker)
    assert claims[0].verification_status == "UNVERIFIED"
    assert claims[0].provenance_status == "SOURCE_EXPLICIT"
    assert claims[0].evidence == []
    assert claims[0].derived_from_claim_ids == []


def test_extract_claims_across_two_batches_keeps_ids_unique():
    worker = FakeWorker([
        ExtractedClaims(claims=[{"source_unit": "a", "claim": "x", "type": "definition"}]),
        ExtractedClaims(claims=[{"source_unit": "b", "claim": "y", "type": "definition"}]),
    ])
    units = [make_unit("a", 4000), make_unit("b", 4000)]
    claims = extract_claims(units, worker, batch_words=6000)
    assert len(worker.calls) == 2
    assert [c.claim_id for c in claims] == ["C001", "C002"]


def test_extract_claims_preserves_mode_stage_scope_when_the_model_sets_them():
    worker = FakeWorker([
        ExtractedClaims(claims=[{
            "source_unit": "u1", "claim": "x", "type": "complexity",
            "mode": "INFERENCE", "stage": "decode", "scope": "MODEL_SPECIFIC",
            "importance": "CORE",
        }]),
    ])
    claims = extract_claims([make_unit("u1", 10)], worker)
    c = claims[0]
    assert (c.mode, c.stage, c.scope, c.importance) == ("INFERENCE", "decode", "MODEL_SPECIFIC", "CORE")


def test_extract_claims_handles_a_batch_with_no_claims_found():
    worker = FakeWorker([ExtractedClaims(claims=[])])
    assert extract_claims([make_unit("u1", 10)], worker) == []
