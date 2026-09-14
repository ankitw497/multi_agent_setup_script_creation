"""Tests for review/story_critic.py -- C1 (plan §5, §10, design doc §27-28)."""
from narration.models import SceneNarration, SentenceNarration
from planning.models import CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract
from review.story_critic import StoryCritique, critique_story


def make_plan(archetype="foundation") -> StoryPlan:
    return StoryPlan(
        archetype=archetype, selection_reason="dependency-driven concepts", story_promise="x",
        central_question="x", rejected_archetypes={"build": "no problem/fix chain found"},
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x")],
    )


def make_narration() -> list[SceneNarration]:
    return [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="x", sentence_type="technical_assertion")])]


class FakeReviewLead:
    def __init__(self, response: StoryCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_passes_resolved_archetype_and_rejection_reasons_to_the_critic():
    """The critic must be able to see WHY alternatives were rejected, so it
    can judge whether that reasoning actually holds up (plan §10.2, playbook
    'Foundation Became the Lazy Default')."""
    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])

    payload = review_lead.calls[0]["payload"]
    assert payload["archetype"] == "foundation"
    assert payload["rejected_archetypes"]["build"] == "no problem/fix chain found"


def test_returns_a_critical_archetype_issue_when_the_critic_challenges_the_resolution():
    """The real scenario this locks in: an A2 run resolved 'foundation' for a
    source whose own structure (explicit 'problem -> new problem' framing)
    plausibly fits 'build' better. C1 must be ABLE to raise exactly this --
    this test proves the plumbing carries that verdict through correctly."""
    review_lead = FakeReviewLead(StoryCritique(issues=[{
        "issue_id": "I001", "severity": "critical", "category": "archetype", "layer": "STORY",
        "scene_ids": ["s1"],
        "problem": "The source explicitly frames each step as solving a new problem "
                   "(scaling fixes the magnitude problem, softmax fixes normalization, "
                   "multi-head fixes the single-projection limitation) -- this is a build "
                   "arc, not a foundation/dependency arc.",
        "why_it_matters": "Foundation framing makes each mechanism feel like arbitrary "
                           "curriculum order instead of a necessary fix, weakening causal flow.",
        "recommended_intent": "Re-plan as build: desired capability -> problem -> fix -> "
                               "new problem -> fix -> assembled system.",
        "repair_owner": "story_lead",
    }]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])

    assert len(issues) == 1
    assert issues[0].category == "archetype"
    assert issues[0].severity == "critical"
    assert issues[0].repair_owner == "story_lead"  # routes to A2 re-plan, per plan §15


def test_critic_never_returns_replacement_prose_only_intent():
    review_lead = FakeReviewLead(StoryCritique(issues=[{
        "issue_id": "I001", "severity": "minor", "category": "repetition", "layer": "NARRATION",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "compress this",
        "repair_owner": "narration_lead",
    }]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])
    assert "replacement_text" not in type(issues[0]).model_fields


def test_uses_pass_id_c1_and_story_critic_mode():
    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])
    call = review_lead.calls[0]
    assert call["pass_id"] == "C1"
    assert call["mode"] == "STORY_CRITIC"


def test_passes_real_source_units_so_the_critic_can_cross_check_the_archetype():
    """Real gap found 2026-09-10: C1 never saw any source content at all --
    only the plan's own self-description -- so it could only judge internal
    consistency, never independently re-test the archetype against the
    actual material (e.g. an author's own production notes)."""
    from facts.models import SourceUnit
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    units = [SourceUnit(id="production_notes", heading="Production notes",
                         text="[0:00] Problem: ... [4:15] Score creates a new problem: ...")]

    critique_story(make_plan(), make_narration(), review_lead,
                    BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=units)

    payload = review_lead.calls[0]["payload"]
    assert payload["source_units"][0]["id"] == "production_notes"
    assert "Score creates a new problem" in payload["source_units"][0]["text"]


def test_prompt_instructs_weighing_production_notes_as_direct_evidence():
    from review.story_critic import TASK_PROMPT

    assert "source_units" in TASK_PROMPT
    assert "production notes" in TASK_PROMPT.lower()


def test_no_issues_is_a_valid_clean_result():
    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])
    assert issues == []


def test_prompt_instructs_checking_for_cross_scene_repetition():
    """V2 narrative-continuity fix (STORY_IMPROVEMENT_PLAN.md Phase 3):
    reuses the existing `category="repetition"` value in review/models.py's
    Category literal -- this check was never asked for before, even though
    the schema already supported it."""
    from review.story_critic import TASK_PROMPT

    assert "REPETITION" in TASK_PROMPT
    assert "category: repetition" in TASK_PROMPT


def test_prompt_instructs_checking_hook_pacing():
    from review.story_critic import TASK_PROMPT

    assert "PACING" in TASK_PROMPT
    assert "category: pacing" in TASK_PROMPT


def test_prompt_instructs_checking_technical_overclaims():
    """feedback (multi_agent_script_and_model_feedback.md §8): hard-selection
    language for a soft/weighted mechanism, claiming a distributed behavior
    is fully resolved by one component, architecture-specific-as-universal
    claims, and overstated motivation/limitation claims. Phrased generically
    (no hardcoded topic vocabulary) so it applies to any video's subject,
    not just the one the original feedback was about -- see
    STORY_IMPROVEMENT_PLAN.md's overfitting note."""
    from review.story_critic import TASK_PROMPT

    assert "OVERCLAIM" in TASK_PROMPT
    assert "soft/weighted or probabilistic" in TASK_PROMPT
    assert "universal to every" in TASK_PROMPT
    assert "underlying general idea" in TASK_PROMPT


def test_scene_plan_and_running_example_reach_the_payload():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    from planning.models import RunningExample, ScenePlan

    plan = make_plan()
    plan.scene_plan = [ScenePlan(
        scene_id="s1", beat_id="B01", scene_function="derivation",
        must_not_repeat=["Q/K/V roles"], new_concepts=[],
    )]
    plan.running_example = RunningExample(label="trophy/suitcase", values={"trophy": "9.6"})
    review_lead = FakeReviewLead(StoryCritique(issues=[]))

    critique_story(plan, make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])

    payload = review_lead.calls[0]["payload"]
    assert payload["scene_plan"] == [{
        "scene_id": "s1", "beat_id": "B01", "scene_function": "derivation",
        "must_not_repeat": ["Q/K/V roles"], "new_concepts": [], "mechanism_scope": {},
    }]
    assert payload["running_example"]["label"] == "trophy/suitcase"


def test_prompt_instructs_treating_a_must_not_repeat_violation_as_confirmed():
    from review.story_critic import TASK_PROMPT

    assert "scene_plan" in TASK_PROMPT
    assert "must_not_repeat" in TASK_PROMPT
    assert "CONFIRMED" in TASK_PROMPT


def test_mechanism_scope_reaches_the_payload():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    from planning.models import ScenePlan

    plan = make_plan()
    plan.scene_plan = [ScenePlan(scene_id="s1", beat_id="B01", mechanism_scope={"causal_mask_required": True})]
    review_lead = FakeReviewLead(StoryCritique(issues=[]))

    critique_story(plan, make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])

    sent = review_lead.calls[0]["payload"]["scene_plan"][0]
    assert sent["mechanism_scope"] == {"causal_mask_required": True}


def test_prompt_instructs_treating_a_scoped_mechanism_stated_as_universal_as_confirmed_overclaim():
    from review.story_critic import TASK_PROMPT

    assert "mechanism_scope" in TASK_PROMPT
    assert "CONFIRMED overclaim" in TASK_PROMPT


def test_prompt_instructs_checking_running_example_fidelity():
    from review.story_critic import TASK_PROMPT

    assert "running_example" in TASK_PROMPT


def test_prompt_has_no_hardcoded_topic_vocabulary():
    """Overfitting guard (user-flagged, STORY_IMPROVEMENT_PLAN.md): C1 runs
    on every video's narration regardless of topic -- the REPETITION/
    PACING/OVERCLAIM checks must be phrased generically, not via
    attention/Q-K-V-specific examples baked in from the one video the
    original feedback was diagnosed against."""
    from review.story_critic import TASK_PROMPT

    lowered = TASK_PROMPT.lower()
    for term in ("q/k/v", "softmax", "multi-head", "highest-matching"):
        assert term not in lowered, f"found topic-specific term {term!r} in a generic per-video prompt"


def test_returns_a_repetition_issue_when_the_critic_flags_one():
    review_lead = FakeReviewLead(StoryCritique(issues=[{
        "issue_id": "I001", "severity": "major", "category": "repetition", "layer": "NARRATION",
        "scene_ids": ["s3", "s7", "s9"],
        "problem": "Q/K/V roles are fully re-derived three separate times.",
        "why_it_matters": "The viewer re-learns the same mechanism instead of the story advancing.",
        "recommended_intent": "Keep the first full explanation; compress the other two to a one-clause reference.",
        "repair_owner": "narration_lead",
    }]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]), source_units=[])

    assert len(issues) == 1
    assert issues[0].category == "repetition"
    assert issues[0].scene_ids == ["s3", "s7", "s9"]
