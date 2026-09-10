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

    critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))

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

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))

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

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert "replacement_text" not in type(issues[0]).model_fields


def test_uses_pass_id_c1_and_story_critic_mode():
    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    call = review_lead.calls[0]
    assert call["pass_id"] == "C1"
    assert call["mode"] == "STORY_CRITIC"


def test_no_issues_is_a_valid_clean_result():
    review_lead = FakeReviewLead(StoryCritique(issues=[]))
    from llm.budget import BudgetCounter, DEFAULT_TIERS

    issues = critique_story(make_plan(), make_narration(), review_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    assert issues == []
