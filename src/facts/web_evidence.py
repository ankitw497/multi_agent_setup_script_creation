"""Web retrieval for evidence requests (plan §17, V1B), extending the
local-only Evidence Broker (facts/evidence.py, V1A scope) to the web.

Order of operations in facts/verify.py's two-pass loop: a request always
tries local `config/references/` FIRST (free, offline, instant) -- only a
request that stays unfulfilled locally ever reaches a `WebSearchBackend`.

Uses Wikipedia's public REST/Action API by default: free, keyless, no
budget/cost tracking needed (there's no dollar cost to a request). This is
a genuinely LIMITED backend -- general encyclopedic facts, not deep
technical papers, vendor spec sheets, or version-pinned library docs --
documented honestly as that, not oversold as full web search. The
`WebSearchBackend` protocol exists so a real search API (Google/Bing/
Brave, whichever gets configured later) can be substituted without
touching `facts/verify.py`'s calling code at all.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .evidence import _score, _words
from .models import EvidenceRequest, VerificationEvidence

_USER_AGENT = "multi-agent-setup-script/1.0 (research/testing; contact: ankitw497@gmail.com)"
_WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class WebSearchResult:
    title: str
    snippet: str
    url: str


class WebSearchBackend(Protocol):
    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


class WikipediaBackend:
    """Real HTTP calls to Wikipedia's public search API. Network failures
    (offline, timeout, rate limit) are caught and treated as "nothing
    found" -- same as an empty local references directory (plan §6.5: an
    unfulfilled evidence request is never treated as a failure of the
    broker, only as "no evidence exists yet")."""

    def __init__(self, timeout_s: float = 8.0):
        self.timeout_s = timeout_s

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        params = urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": limit,
        })
        req = urllib.request.Request(
            f"{_WIKIPEDIA_SEARCH_URL}?{params}", headers={"User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            return []

        results = []
        for item in data.get("query", {}).get("search", []):
            title = item.get("title", "")
            snippet = _strip_html(item.get("snippet", ""))
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            results.append(WebSearchResult(title=title, snippet=snippet, url=url))
        return results


def fulfil_evidence_requests_via_web(
    requests: list[EvidenceRequest], backend: WebSearchBackend, min_score: float = 0.3,
) -> dict[str, VerificationEvidence]:
    """Same shape and scoring philosophy as facts.evidence.fulfil_evidence_requests
    -- one best-matching web result per request, if any clears `min_score`
    word-overlap with the request's own text. Requests with no match simply
    don't appear in the result; never a failure, never a raised exception."""
    fulfilled: dict[str, VerificationEvidence] = {}
    for request in requests:
        request_words = _words(f"{request.what_would_settle_it} {' '.join(request.suggested_sources)}")
        results = backend.search(request.what_would_settle_it)

        best_result, best_score = None, 0.0
        for result in results:
            score = _score(request_words, _words(f"{result.title} {result.snippet}"))
            if score > best_score:
                best_result, best_score = result, score

        if best_result is not None and best_score >= min_score:
            fulfilled[request.claim_id] = VerificationEvidence(
                kind="EXTERNAL_REFERENCE", ref=best_result.url, excerpt=best_result.snippet,
                verdict=f"web reference (word-overlap score {best_score:.2f}): {best_result.title}",
            )
    return fulfilled
