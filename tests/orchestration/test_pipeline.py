"""Tests for orchestration/pipeline.py -- the bounded revision loop (plan §8, §14, §15).

Uses a schema-dispatching FakeAgent so each of the three shared agent
identities (story_lead/narration_lead/review_lead) can serve multiple
passes (A2+A3, B1, CM+C1+C2b) the way the real pipeline shares them.
"""
from facts.models import AssumptionLedger, Claim
from narration.generator import GeneratedNarration
from orchestration.pipeline import PipelineAgents, run_story_and_narration_loop
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract,
)
from review.claim_mapper import ClaimMapperOutput
from review.grounding_verifier import GroundingReview
from review.story_critic import StoryCritique


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


def make_plan(scene_words=70, n_scenes=24, source_units=None, archetype="build") -> StoryPlan:
    source_units = source_units if source_units is not None else ["u1"]
    from planning.models import ScenePlan

    # Scenes distributed across all three beats (not all dumped on B01) so
    # the retention/CTA diagnostics (plan §10.2, §10.3) see a realistic
    # timing shape too, not just a plan that happens to pass the word-count
    # hard check. B01 (hook, ~small) + B02 (early mini-payoff, hosts the
    # CTA at a real ~20-40% mark) + B03 (the bulk of the remaining content).
    b1_n = min(3, max(1, n_scenes // 8))
    b2_n = min(4, max(1, n_scenes // 6))
    b3_n = max(0, n_scenes - b1_n - b2_n)
    scene_plan = (
        [ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=scene_words) for i in range(b1_n)]
        + [ScenePlan(scene_id=f"s{i}", beat_id="B02", word_budget=scene_words) for i in range(b1_n, b1_n + b2_n)]
        + [ScenePlan(scene_id=f"s{i}", beat_id="B03", word_budget=scene_words) for i in range(b1_n + b2_n, n_scenes)]
    )

    return StoryPlan(
        archetype=archetype, selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="understand how attention retrieves context"),
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand how attention retrieves context"),
        cta=CTAContract(primary_after_beat="B02"),  # not the first beat -- see check_cta_placement
        ending=EndingContract(resolve_hook="now you understand how attention retrieves context end to end",
                               compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=source_units,
                          archetype_stage="desired_capability", forward_driver="x", new_information=True),
               StoryBeat(beat_id="B02", purpose="x", source_unit_ids=source_units,
                          archetype_stage="problem_to_solution_pair", forward_driver="y", payoff=True),
               StoryBeat(beat_id="B03", purpose="x", source_unit_ids=source_units,
                          archetype_stage="assembled_system", forward_driver="z", new_information=True)],
        scene_plan=scene_plan,
    )


def make_empty_narration_response(n=1) -> GeneratedNarration:
    return GeneratedNarration(scenes=[{"scene_id": f"s{i}", "sentences": []} for i in range(n)])


def make_agents(story_lead_responses=None, narration_responses=None, review_responses=None) -> PipelineAgents:
    story_lead = FakeAgent({
        StoryPlan: (story_lead_responses or {}).get(StoryPlan, []),
        __import__("editing.models", fromlist=["RevisionPlan"]).RevisionPlan: (story_lead_responses or {}).get("RevisionPlan", []),
    })
    narration_lead = FakeAgent({GeneratedNarration: narration_responses or []})
    review_lead = FakeAgent({
        StoryCritique: (review_responses or {}).get("c1", []),
        GroundingReview: (review_responses or {}).get("c2b", []),
    })
    cm_agent = FakeAgent({ClaimMapperOutput: (review_responses or {}).get("cm", [])})
    return PipelineAgents(story_lead=story_lead, narration_lead=narration_lead,
                           review_lead=review_lead, cm_agent=cm_agent)


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def test_a_clean_plan_passes_with_no_revision_calls():
    plan = make_plan()
    agents = make_agents(
        narration_responses=[make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[])],
        },
    )
    result = run_story_and_narration_loop(
        source_brief=__import__("planning.models", fromlist=["SourceBrief"]).SourceBrief(
            topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )
    assert result.final_status == "PASS"
    assert result.story_replans_used == 0
    assert result.major_revisions_used == 0
    assert agents.story_lead.calls == []  # A3/A2 never called -- nothing needed fixing


def test_a_bad_plan_gets_replanned_and_then_passes():
    """The exact real scenario found live: a structurally deficient plan
    (word budget too low) gets caught, A3 calls for a replan, and a second,
    clean plan is generated and passes."""
    from editing.models import RevisionPlan

    bad_plan = make_plan(scene_words=30, n_scenes=2)  # ~20 words vs ~1670 target
    good_plan = make_plan()

    agents = make_agents(
        story_lead_responses={StoryPlan: [good_plan], "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)]},
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan,
    )
    assert result.final_status == "PASS"
    assert result.story_replans_used == 1
    assert result.plan is good_plan


def test_replan_budget_exhaustion_fails_rather_than_looping_forever():
    """MAX_STORY_REPLANS=1 -- a second consecutive bad plan must FAIL, not
    keep replanning indefinitely."""
    from editing.models import RevisionPlan

    bad_plan_1 = make_plan(scene_words=30, n_scenes=2)
    bad_plan_2 = make_plan(scene_words=30, n_scenes=2)

    agents = make_agents(
        story_lead_responses={
            StoryPlan: [bad_plan_2],
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)] * 2,
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[])] * 2,
            "c1": [StoryCritique(issues=[])] * 2,
            "c2b": [GroundingReview(issues=[])] * 2,
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan_1,
    )
    assert result.final_status == "FAIL"
    assert result.story_replans_used == 1  # never exceeds the bound
    assert any("replan budget exhausted" in line for line in result.log)


def test_a2_replan_receives_the_prior_rejection_reason_not_a_blind_retry():
    """Real gap found 2026-09-10: the replan call used to rerun plan_story()
    with the exact same inputs as the first attempt -- A2 never learned WHY
    its plan was rejected. This proves the orchestrator now builds and
    passes a ReplanFeedback carrying the previous archetype, C1's critique,
    and the structural findings into the replan call."""
    from editing.models import RevisionPlan

    bad_plan = make_plan(scene_words=30, n_scenes=2, archetype="foundation")
    good_plan = make_plan(archetype="build")
    archetype_issue = {
        "issue_id": "I1", "severity": "critical", "category": "archetype", "layer": "STORY",
        "problem": "explicit problem->fix chain suggests build",
        "why_it_matters": "x", "recommended_intent": "replan as build", "repair_owner": "story_lead",
    }

    agents = make_agents(
        story_lead_responses={StoryPlan: [good_plan], "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)]},
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[archetype_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan,
    )

    a2_call = next(c for c in agents.story_lead.calls if c["pass_id"] == "A2")
    feedback = a2_call["payload"]["replan_feedback"]
    assert feedback["previous_archetype"] == "foundation"
    assert feedback["critique_issues"][0]["category"] == "archetype"
    assert feedback["critique_issues"][0]["recommended_intent"] == "replan as build"
    assert any(i["code"] == "word_budget_mismatch" for i in feedback["structural_issues"])


def test_source_units_reach_both_a2_replan_and_c1_critique():
    """Real gap found 2026-09-10: neither A2 nor C1 ever saw the source's
    real content (e.g. an author's own production notes) -- only A1's
    compressed brief. This proves the plumbing carries source_units through
    the orchestrator to both the A2 replan call and the C1 critique call."""
    from editing.models import RevisionPlan
    from facts.models import SourceUnit

    bad_plan = make_plan(scene_words=30, n_scenes=2)
    good_plan = make_plan()
    units = [SourceUnit(id="production_notes", heading="Production notes", text="Problem -> Mini payoff")]

    agents = make_agents(
        story_lead_responses={StoryPlan: [good_plan], "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)]},
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(),
        source_units=units, initial_plan=bad_plan,
    )

    a2_call = next(c for c in agents.story_lead.calls if c["pass_id"] == "A2")
    assert a2_call["payload"]["source_units"][0]["id"] == "production_notes"

    c1_call = next(c for c in agents.review_lead.calls if c["pass_id"] == "C1")
    assert c1_call["payload"]["source_units"][0]["id"] == "production_notes"


def test_a_critical_non_archetype_issue_routes_to_targeted_rewrite_not_replan():
    """A critical issue that ISN'T structural (e.g. a grounding fidelity
    problem) should let A3 choose targeted rewrite over a full replan."""
    from editing.models import RewriteBeat, RevisionPlan

    plan = make_plan()
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "clarity", "layer": "TECHNICAL",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "z", "repair_owner": "narration_lead",
    }
    agents = make_agents(
        story_lead_responses={
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=False,
                                            rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])],
        },
        # Two narration_lead calls now happen: B1's initial draft, then B2's
        # targeted rewrite (real gap fixed 2026-09-10 -- TARGETED_REWRITE used
        # to be a no-op and never called narration_lead a second time at all).
        narration_responses=[make_empty_narration_response(), GeneratedNarration(scenes=[])],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[critical_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )
    assert result.final_status == "PASS"
    assert result.major_revisions_used == 1
    assert result.story_replans_used == 0  # replan was never triggered
    assert any("targeted rewrite" in line for line in result.log)


def test_targeted_rewrite_actually_calls_b2_with_the_named_beat_not_a_no_op():
    """Real gap found 2026-09-10: TARGETED_REWRITE used to just log the
    intent and re-verify the same narration -- narration_lead was never
    called a second time at all. This proves the second call actually
    happens and carries the named beat's scope."""
    from editing.models import RewriteBeat, RevisionPlan

    plan = make_plan()
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "clarity", "layer": "TECHNICAL",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "z", "repair_owner": "narration_lead",
    }
    agents = make_agents(
        story_lead_responses={
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=False,
                                            rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten it")])],
        },
        narration_responses=[make_empty_narration_response(), GeneratedNarration(scenes=[])],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[critical_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    b2_call = next(c for c in agents.narration_lead.calls if c["pass_id"] == "B2")
    assert b2_call["mode"] == "TARGETED_REWRITE"
    assert all("tighten it" == s["required_intent"] for s in b2_call["payload"]["scenes"])
