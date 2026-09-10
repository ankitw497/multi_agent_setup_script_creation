"""Tests for planning/story_planner.py -- A2 (plan §5, §9, §19)."""
import pytest

from facts.models import AssumptionLedger, Claim
from llm.budget import BudgetCounter, DEFAULT_TIERS
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from planning.story_planner import plan_story


def make_plan(archetype="build") -> StoryPlan:
    return StoryPlan(
        archetype=archetype, selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


class FakeStoryLead:
    def __init__(self, response: StoryPlan):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_passes_archetype_reference_table_to_the_model():
    """The model must see the real core/optional roles and drivers, never
    guess at them (plan §9)."""
    story_lead = FakeStoryLead(make_plan())
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600,
    )
    payload = story_lead.calls[0]["payload"]
    assert "mystery" in payload["archetype_reference"]
    assert payload["archetype_reference"]["mystery"]["driver"] == "unanswered cause"


def test_archetype_override_is_passed_through_as_a_pin():
    story_lead = FakeStoryLead(make_plan(archetype="mystery"))
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, archetype_override="mystery",
    )
    assert story_lead.calls[0]["payload"]["archetype_override"] == "mystery"


def test_raises_if_the_model_switches_away_from_a_pinned_archetype():
    """Fixed-archetype mode must never silently switch (plan §6)."""
    story_lead = FakeStoryLead(make_plan(archetype="build"))  # model ignored the pin
    from planning.models import SourceBrief

    with pytest.raises(ValueError, match="must not switch archetypes"):
        plan_story(
            SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
            [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
            target_duration_seconds=600, archetype_override="mystery",
        )


def test_auto_mode_accepts_whatever_archetype_the_model_resolves():
    story_lead = FakeStoryLead(make_plan(archetype="derivation"))
    from planning.models import SourceBrief

    result = plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600,  # archetype_override=None -> auto
    )
    assert result.archetype == "derivation"


def test_prompt_calibrates_scene_count_and_word_budget_to_target_duration():
    """Regression test for a real defect found 2026-09-10: a live run produced
    a StoryPlan with only 4 scenes totaling ~320 words against a 600s (~1670
    word) target -- the source's real depth (11 sections) was almost entirely
    unused. The prompt must give the model a concrete calibration anchor, not
    just an abstract per-scene word range."""
    from planning.story_planner import TASK_PROMPT

    assert "target_duration_seconds / 60 * 167" in TASK_PROMPT
    assert "NOT 4-6 scenes" in TASK_PROMPT or "not 4-6 scenes" in TASK_PROMPT.lower()


def test_prompt_instructs_populating_source_unit_ids():
    """Regression test for a real defect found 2026-09-10: a live run
    returned every beat with an EMPTY source_unit_ids, silently dropping
    most of an 11-section source's content. The gap was that the prompt
    never actually asked for this field to be populated."""
    from planning.story_planner import TASK_PROMPT

    assert "source_unit_ids" in TASK_PROMPT
    assert "never leave this empty" in TASK_PROMPT


def test_passes_target_duration_and_planning_wpm():
    story_lead = FakeStoryLead(make_plan())
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=900,
    )
    payload = story_lead.calls[0]["payload"]
    assert payload["target_duration_seconds"] == 900
    assert payload["planning_wpm"] == 167
