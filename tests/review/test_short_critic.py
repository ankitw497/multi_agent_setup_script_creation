"""Tests for review/short_critic.py -- C1s (plan §20.7)."""
from narration.models import SceneNarration, SentenceNarration
from review.short_critic import ShortCritique, critique_short


def make_narration() -> list[SceneNarration]:
    return [SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="x", sentence_type="transition")])]


class FakeReviewAgent:
    def __init__(self, response: ShortCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_no_issues_is_a_valid_clean_result():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[]))
    issues = critique_short("problem_fix", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]))
    assert issues == []


def test_returns_a_micro_arc_issue():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[{
        "issue_id": "I1", "severity": "critical", "category": "micro_arc", "layer": "STORY",
        "problem": "no real naive attempt shown before the fix", "why_it_matters": "breaks problem_fix's own shape",
        "recommended_intent": "add the naive attempt before the fix", "repair_owner": "story_lead",
    }]))
    issues = critique_short("problem_fix", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]))
    assert len(issues) == 1
    assert issues[0].category == "micro_arc"


def test_micro_arc_is_passed_through():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[]))
    critique_short("mini_derivation", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]))
    assert review_agent.calls[0]["payload"]["micro_arc"] == "mini_derivation"


def test_uses_pass_id_c1s_and_short_critic_mode():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[]))
    critique_short("problem_fix", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]))
    call = review_agent.calls[0]
    assert call["pass_id"] == "C1s"
    assert call["mode"] == "SHORT_CRITIC"


def test_bridge_mode_defaults_to_none_and_reaches_the_payload():
    """2026-09-15: confirmed live -- every one of 5 real shorts got a critical
    RESERVED_OUTRO finding even though narration/short_generator.py's own prompt REQUIRES
    a follow-up sentence when bridge.mode is SPOKEN. Root cause: this pass never received
    bridge_mode at all, so its own unconditional "no reserved outro" rule couldn't tell a
    required follow-up line from an unprompted one."""
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[]))
    critique_short("problem_fix", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]))
    assert review_agent.calls[0]["payload"]["bridge_mode"] == "NONE"


def test_bridge_mode_is_passed_through_when_given():
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_agent = FakeReviewAgent(ShortCritique(issues=[]))
    critique_short(
        "problem_fix", make_narration(), review_agent, BudgetCounter(tier=DEFAULT_TIERS["short"]),
        bridge_mode="SPOKEN",
    )
    assert review_agent.calls[0]["payload"]["bridge_mode"] == "SPOKEN"


def test_prompt_explains_bridge_mode_gates_the_reserved_outro_rule():
    from review.short_critic import TASK_PROMPT

    assert "bridge_mode" in TASK_PROMPT
    assert "SPOKEN" in TASK_PROMPT
    assert "REQUIRED" in TASK_PROMPT
