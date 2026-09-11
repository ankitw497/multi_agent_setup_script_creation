"""Tests for facts/web_evidence.py -- web retrieval fallback (plan §17, V1B).

Unit tests use a fake backend, never a real HTTP call. A separate,
deliberately isolated live check against the real Wikipedia API is not
part of this file -- see the `integration`-marked test below, run only
with `pytest -m integration`.
"""
import pytest

from facts.models import EvidenceRequest
from facts.web_evidence import WebSearchResult, fulfil_evidence_requests_via_web


class FakeBackend:
    def __init__(self, results: list[WebSearchResult]):
        self._results = results
        self.queries = []

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        self.queries.append(query)
        return self._results


def test_no_results_leaves_the_request_unfulfilled():
    backend = FakeBackend([])
    requests = [EvidenceRequest(claim_id="C001", what_would_settle_it="the exact release date of GPT-4")]
    assert fulfil_evidence_requests_via_web(requests, backend) == {}


def test_a_well_matching_result_fulfils_the_request():
    backend = FakeBackend([
        WebSearchResult(title="Transformer (deep learning)", snippet="scaling dot product attention by sqrt", url="https://en.wikipedia.org/wiki/x"),
    ])
    requests = [EvidenceRequest(claim_id="C001", what_would_settle_it="scaling dot product attention by sqrt of dimension")]
    fulfilled = fulfil_evidence_requests_via_web(requests, backend)
    assert "C001" in fulfilled
    assert fulfilled["C001"].kind == "EXTERNAL_REFERENCE"
    assert fulfilled["C001"].ref == "https://en.wikipedia.org/wiki/x"


def test_a_poorly_matching_result_below_threshold_does_not_fulfil():
    backend = FakeBackend([WebSearchResult(title="Bananas", snippet="a yellow fruit", url="https://en.wikipedia.org/wiki/Banana")])
    requests = [EvidenceRequest(claim_id="C001", what_would_settle_it="scaling dot product attention by sqrt of dimension")]
    assert fulfil_evidence_requests_via_web(requests, backend) == {}


def test_best_of_multiple_results_is_chosen():
    backend = FakeBackend([
        WebSearchResult(title="Irrelevant", snippet="nothing to do with it", url="https://en.wikipedia.org/wiki/a"),
        WebSearchResult(title="Attention mechanism", snippet="query key value scaling dot product", url="https://en.wikipedia.org/wiki/b"),
    ])
    requests = [EvidenceRequest(claim_id="C001", what_would_settle_it="query key value scaling dot product")]
    fulfilled = fulfil_evidence_requests_via_web(requests, backend)
    assert fulfilled["C001"].ref == "https://en.wikipedia.org/wiki/b"


def test_multiple_requests_are_each_queried_independently():
    backend = FakeBackend([WebSearchResult(title="x", snippet="x", url="https://en.wikipedia.org/wiki/x")])
    requests = [
        EvidenceRequest(claim_id="C001", what_would_settle_it="question one"),
        EvidenceRequest(claim_id="C002", what_would_settle_it="question two"),
    ]
    fulfil_evidence_requests_via_web(requests, backend)
    assert backend.queries == ["question one", "question two"]


def test_unfulfilled_request_never_raises():
    backend = FakeBackend([])
    requests = [EvidenceRequest(claim_id="C001", what_would_settle_it="anything")]
    result = fulfil_evidence_requests_via_web(requests, backend)
    assert result == {}


@pytest.mark.integration
def test_live_wikipedia_backend_smoke():
    """Real HTTP call, no API key, no cost. Run with: pytest -m integration"""
    from facts.web_evidence import WikipediaBackend

    backend = WikipediaBackend()
    results = backend.search("Transformer deep learning attention mechanism")
    assert len(results) > 0
    assert all(r.url.startswith("https://en.wikipedia.org/wiki/") for r in results)
