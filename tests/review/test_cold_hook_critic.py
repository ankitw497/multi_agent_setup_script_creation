"""Tests for review/cold_hook_critic.py -- C4s (plan §20.7, §20.10).

Cascade: a clean, confident Haiku pass costs nothing further (no
escalation call at all); a flagged or uncertain one escalates to Gemini
for a second, independent opinion.
"""
from review.cold_hook_critic import ColdHookCritique, ColdHookVerdict, critique_cold_hook


class FakeWorker:
    def __init__(self, response: ColdHookVerdict):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeReviewAgent:
    def __init__(self, response: ColdHookCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["short"])


def test_clean_confident_verdict_never_escalates():
    worker = FakeWorker(ColdHookVerdict(clarity="clear", creates_tension=True, curiosity_gap=True,
                                          generic_opening=False, confidence="high", flagged=False))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[]))

    issues = critique_cold_hook("t", "n", "v", worker, review_agent, make_budget())

    assert issues == []
    assert review_agent.calls == []  # no escalation call at all


def test_flagged_verdict_escalates_to_gemini():
    worker = FakeWorker(ColdHookVerdict(clarity="confusing", flagged=True, confidence="high"))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[{
        "issue_id": "I1", "severity": "major", "category": "hook", "layer": "STORY",
        "problem": "unclear opening", "why_it_matters": "x", "recommended_intent": "clarify",
        "repair_owner": "story_lead",
    }]))

    issues = critique_cold_hook("t", "n", "v", worker, review_agent, make_budget())

    assert len(review_agent.calls) == 1
    assert len(issues) == 1
    assert issues[0].category == "hook"


def test_low_confidence_escalates_even_if_not_flagged():
    worker = FakeWorker(ColdHookVerdict(flagged=False, confidence="low"))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[]))

    critique_cold_hook("t", "n", "v", worker, review_agent, make_budget())

    assert len(review_agent.calls) == 1


def test_gemini_can_clear_a_haiku_flag():
    """A flagged Haiku pass isn't automatically an issue -- Gemini's
    independent read is what actually decides."""
    worker = FakeWorker(ColdHookVerdict(flagged=True, confidence="medium"))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[]))

    issues = critique_cold_hook("t", "n", "v", worker, review_agent, make_budget())
    assert issues == []


def test_no_review_agent_falls_back_to_haiku_only_issue():
    """If no escalation agent is wired at all, a flagged Haiku verdict
    still produces a usable issue rather than being silently dropped."""
    worker = FakeWorker(ColdHookVerdict(clarity="confusing", flagged=True))
    issues = critique_cold_hook("t", "n", "v", worker)
    assert len(issues) == 1
    assert "unclear" in issues[0].problem


def test_escalation_payload_carries_the_first_pass_verdict():
    worker = FakeWorker(ColdHookVerdict(flagged=True))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[]))
    critique_cold_hook("My Title", "narration text", "visual desc", worker, review_agent, make_budget())
    payload = review_agent.calls[0]["payload"]
    assert payload["title"] == "My Title"
    assert "first_pass_verdict" in payload


def test_uses_pass_id_c4s_for_both_stages():
    worker = FakeWorker(ColdHookVerdict(flagged=True))
    review_agent = FakeReviewAgent(ColdHookCritique(issues=[]))
    critique_cold_hook("t", "n", "v", worker, review_agent, make_budget())
    assert worker.calls[0]["pass_id"] == "C4s"
    assert review_agent.calls[0]["pass_id"] == "C4s"
