"""Tests for review/style_critic.py -- C5 (plan §8, §11.5)."""
from narration.models import SceneNarration, SentenceNarration
from review.style_critic import StyleCritique, critique_style


def make_narration() -> list[SceneNarration]:
    return [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="x", sentence_type="transition")])]


class FakeReviewAgent:
    def __init__(self, response: StyleCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_no_issues_is_a_valid_clean_result():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(StyleCritique(issues=[]))
    issues = critique_style(make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert issues == []


def test_returns_a_repetition_issue_routed_to_narration_lead():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(StyleCritique(issues=[{
        "issue_id": "I1", "severity": "minor", "category": "repetition", "layer": "VOICE",
        "scene_ids": ["s1"], "problem": "every sentence is the same length",
        "why_it_matters": "reads as robotic", "recommended_intent": "vary sentence length",
        "repair_owner": "narration_lead",
    }]))
    issues = critique_style(make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert len(issues) == 1
    assert issues[0].layer == "VOICE"
    assert issues[0].repair_owner == "narration_lead"


def test_uses_pass_id_c5_and_style_critic_mode():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(StyleCritique(issues=[]))
    critique_style(make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    call = review_agent.calls[0]
    assert call["pass_id"] == "C5"
    assert call["mode"] == "STYLE_CRITIC"


def test_never_returns_replacement_prose_only_intent():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(StyleCritique(issues=[{
        "issue_id": "I1", "severity": "minor", "category": "repetition", "layer": "VOICE",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "vary rhythm",
        "repair_owner": "narration_lead",
    }]))
    issues = critique_style(make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert "replacement_text" not in type(issues[0]).model_fields
