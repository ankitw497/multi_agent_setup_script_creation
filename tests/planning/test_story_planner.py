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
        target_duration_seconds=600, source_units=[],
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
        target_duration_seconds=600, source_units=[], archetype_override="mystery",
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
            target_duration_seconds=600, source_units=[], archetype_override="mystery",
        )


def test_auto_mode_accepts_whatever_archetype_the_model_resolves():
    story_lead = FakeStoryLead(make_plan(archetype="derivation"))
    from planning.models import SourceBrief

    result = plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, source_units=[],  # archetype_override=None -> auto
    )
    assert result.archetype == "derivation"


def test_prompt_no_longer_asks_a2_to_calibrate_scene_word_budgets_itself():
    """Superseded regression test for the real defect found 2026-09-10 (a
    live run produced only 4 scenes / ~320 words against a ~1670-word
    target): asking A2 to also correctly sum a whole-plan word budget in
    one shot was itself unreliable (ERR-010/ERR-023). The fix moved that
    aggregate math to deterministic Python (beat_word_budget.py) plus a
    small per-beat call (scene_expander.py) -- A2's own prompt must no
    longer ask it to produce or calibrate a scene_plan at all."""
    from planning.story_planner import TASK_PROMPT

    assert "scene_plan" not in TASK_PROMPT
    assert "A2b" in TASK_PROMPT


def test_prompt_instructs_populating_source_unit_ids():
    """Regression test for a real defect found 2026-09-10: a live run
    returned every beat with an EMPTY source_unit_ids, silently dropping
    most of an 11-section source's content. The gap was that the prompt
    never actually asked for this field to be populated."""
    from planning.story_planner import TASK_PROMPT

    assert "source_unit_ids" in TASK_PROMPT
    assert "never leave this empty" in TASK_PROMPT


def test_prompt_instructs_populating_archetype_role_with_the_render_vocabulary():
    """Real gap found 2026-09-11 (user-reported missing figures/visualizations):
    `html_synth/synthesizer.py` gates a beat's allowed visual components on
    `StoryBeat.archetype_role`, but the prompt only ever explained
    `archetype_stage` (a DIFFERENT field, holding the resolved archetype's
    OWN vocabulary, e.g. "organizing_principle" for framework) -- so across
    every real run checked (v01/v09/v10/v11), `archetype_role` was either
    left blank or filled with `archetype_stage`-shaped values that don't
    match any story_roles key, and EVERY beat silently fell back to the
    same generic (grid_3, defbox) component set regardless of content --
    diagram_card/math_block/callout_*/metric_table/step_list/hero (beyond
    page 1) were never reachable in any real run to date."""
    from planning.story_planner import TASK_PROMPT

    assert "archetype_role" in TASK_PROMPT
    assert "archetype_stage" in TASK_PROMPT
    for role in ("hook", "contradiction", "investigation", "problem_fix", "mechanism", "comparison", "derivation", "observations", "payoff"):
        assert role in TASK_PROMPT


def test_passes_real_source_units_not_just_the_compressed_brief():
    """Real gap found 2026-09-10: A2 only ever saw A1's lossy SourceBrief
    summary, never the source's real content -- so it had no way to weigh an
    author's own production notes as direct archetype evidence (the user's
    own separate render pipeline had already correctly resolved this source
    as 'build' from exactly that content). A2 must now receive the raw
    source_units alongside the brief."""
    from facts.models import SourceUnit
    from planning.models import SourceBrief

    story_lead = FakeStoryLead(make_plan())
    units = [SourceUnit(id="production_notes", heading="Production notes",
                         text="[0:00] Problem: ... [0:35] Mini payoff: ...")]

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, source_units=units,
    )
    payload = story_lead.calls[0]["payload"]
    assert payload["source_units"][0]["id"] == "production_notes"
    assert "Mini payoff" in payload["source_units"][0]["text"]


def test_prompt_instructs_weighing_production_notes_as_direct_evidence():
    from planning.story_planner import TASK_PROMPT

    assert "source_units" in TASK_PROMPT
    assert "production notes" in TASK_PROMPT.lower()


def test_passes_target_duration_and_planning_wpm():
    story_lead = FakeStoryLead(make_plan())
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=900, source_units=[],
    )
    payload = story_lead.calls[0]["payload"]
    assert payload["target_duration_seconds"] == 900
    assert payload["planning_wpm"] == 167


def test_replan_feedback_defaults_to_none_on_a_first_attempt():
    story_lead = FakeStoryLead(make_plan())
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, source_units=[],
    )
    assert story_lead.calls[0]["payload"]["replan_feedback"] is None


def test_replan_feedback_is_passed_through_on_a_replan():
    """Real gap found 2026-09-10: the replan call used to rerun plan_story()
    with the exact same inputs as the first attempt -- A2 never learned WHY
    its previous plan was rejected, so a second wrong answer was just as
    likely as a corrected one. A2 must now see the critic's and A3's actual
    reasoning."""
    from planning.models import ReplanFeedback, SourceBrief

    story_lead = FakeStoryLead(make_plan(archetype="build"))
    feedback = ReplanFeedback(
        previous_archetype="foundation",
        critique_issues=[{"severity": "critical", "category": "archetype",
                           "problem": "explicit problem->fix chain", "recommended_intent": "replan as build"}],
        structural_issues=[{"code": "word_budget_mismatch", "detail": "480 vs 1670 words"}],
    )

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, source_units=[], replan_feedback=feedback,
    )
    payload = story_lead.calls[0]["payload"]
    assert payload["replan_feedback"]["previous_archetype"] == "foundation"
    assert payload["replan_feedback"]["critique_issues"][0]["category"] == "archetype"
    assert payload["replan_feedback"]["structural_issues"][0]["code"] == "word_budget_mismatch"


def test_prompt_instructs_addressing_replan_feedback():
    from planning.story_planner import TASK_PROMPT

    assert "replan_feedback" in TASK_PROMPT
    assert "previous_archetype" in TASK_PROMPT


def test_requests_a_generous_max_tokens_override():
    """Real bug found 2026-09-10 (ERR-021): a full multi-scene StoryPlan was
    truncated mid-string at the shared 2048-token default. Now that
    scene_plan is a separate pass (ERR-010/ERR-023), A2's own call is much
    smaller, but it still gets an explicit override rather than relying on
    the shared default alone -- cheap insurance for a plan with many beats."""
    story_lead = FakeStoryLead(make_plan())  # make_plan() has no beats -> only the A2 call happens
    from planning.models import SourceBrief

    plan_story(
        SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]),
        target_duration_seconds=600, source_units=[],
    )
    assert story_lead.calls[0]["max_tokens"] >= 4000
