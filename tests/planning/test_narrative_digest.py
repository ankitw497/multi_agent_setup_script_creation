"""Tests for planning/narrative_digest.py -- S1 (plan §6.3, §8)."""
from facts.models import SourceUnit
from planning.narrative_digest import (
    NARRATIVE_DIGEST_WORD_THRESHOLD, NarrativeDigest, build_narrative_digest, needs_narrative_digest,
)


class FakeWorker:
    def __init__(self, response: NarrativeDigest):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_short_source_does_not_need_a_digest():
    units = [SourceUnit(id="u1", text="a short section with only a few words")]
    assert needs_narrative_digest(units) is False


def test_source_over_the_word_threshold_needs_a_digest():
    long_text = " ".join(["word"] * (NARRATIVE_DIGEST_WORD_THRESHOLD + 1))
    units = [SourceUnit(id="u1", text=long_text)]
    assert needs_narrative_digest(units) is True


def test_threshold_sums_across_all_units_not_just_one():
    half = NARRATIVE_DIGEST_WORD_THRESHOLD // 2 + 100
    units = [
        SourceUnit(id="u1", text=" ".join(["word"] * half)),
        SourceUnit(id="u2", text=" ".join(["word"] * half)),
    ]
    assert needs_narrative_digest(units) is True


def test_build_narrative_digest_passes_all_units():
    worker = FakeWorker(NarrativeDigest(summary="x", section_order=["u1", "u2"]))
    units = [SourceUnit(id="u1", heading="First", text="a"), SourceUnit(id="u2", heading="Second", text="b")]

    result = build_narrative_digest(units, worker)

    payload = worker.calls[0]["payload"]
    assert [u["id"] for u in payload["source_units"]] == ["u1", "u2"]
    assert result.summary == "x"
    assert result.section_order == ["u1", "u2"]


def test_uses_pass_id_s1_and_narrative_digest_mode():
    worker = FakeWorker(NarrativeDigest(summary="x"))
    build_narrative_digest([], worker)
    call = worker.calls[0]
    assert call["pass_id"] == "S1"
    assert call["mode"] == "NARRATIVE_DIGEST"
    assert call["schema"] is NarrativeDigest
