"""Tests for orchestration/shorts_pipeline.py -- the V1A-S short run (plan §20.7).

Single-pass by design (no A3/B2 revision loop for shorts in V1A-S -- see
module docstring). Uses a schema-dispatching FakeAgent, same pattern as
the long-form pipeline tests.
"""
import pytest

from narration.short_generator import GeneratedShortNarration
from orchestration.shorts_pipeline import ShortsPipelineAgents, run_short
from planning.shorts_models import HookEvent, ShortParent, ShortPlan
from review.claim_mapper import ClaimMapperOutput
from review.cold_hook_critic import ColdHookCritique, ColdHookVerdict
from review.grounding_verifier import GroundingReview
from review.short_critic import ShortCritique


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        title="Why attention needs scaling", central_insight="scaling keeps softmax stable",
        micro_arc="problem_fix",
        hook=HookEvent(narration="scores blow up without scaling", starts_at_seconds=1.0),
        payoff_central="scaling by sqrt(d_k) keeps attention scores stable",
    )
    base.update(overrides)
    return ShortPlan(**base)


def make_narration_response() -> GeneratedShortNarration:
    # "mechanism" padded to land the total within the 120-165 word advisory
    # band -- a real fixture, not a diagnostic-triggering minimal stub, so
    # "clean" tests actually land on a clean PASS, not a word-count PASS_WARN.
    mechanism_text = " ".join(["word"] * 110)
    return GeneratedShortNarration(segments=[
        {"segment": "hook", "sentences": [{"text": "scores blow up without scaling", "sentence_type": "transition"}]},
        {"segment": "setup", "sentences": [{"text": "context sentence here", "sentence_type": "transition"}]},
        {"segment": "mechanism", "sentences": [{"text": mechanism_text, "sentence_type": "technical_assertion"}]},
        {"segment": "payoff", "sentences": [{"text": "scaling by sqrt(d_k) keeps scores stable", "sentence_type": "payoff"}]},
    ])


def make_agents(review_responses=None, cold_hook_haiku=None) -> ShortsPipelineAgents:
    responses = review_responses or {}
    review_agent = FakeAgent({
        ClaimMapperOutput: responses.get("cm", [ClaimMapperOutput(sentences=[])]),
        GroundingReview: responses.get("c2b", [GroundingReview(issues=[])]),
        ShortCritique: responses.get("c1s", [ShortCritique(issues=[])]),
        ColdHookCritique: responses.get("c4s_gemini", [ColdHookCritique(issues=[])]),
    })
    worker = FakeAgent({
        GeneratedShortNarration: [make_narration_response()],
        ColdHookVerdict: [cold_hook_haiku or ColdHookVerdict(flagged=False, confidence="high")],
    })
    narration_lead = FakeAgent({GeneratedShortNarration: [make_narration_response()]})
    return ShortsPipelineAgents(narration_lead=narration_lead, worker=worker, review_agent=review_agent)


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["short"])


def test_a_clean_short_passes():
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "PASS"
    assert result.hard_failures == []


def test_missing_parent_reference_fails():
    agents = make_agents()
    result = run_short(make_plan(parent=None), [], agents, make_budget(), require_parent=True, enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("missing_parent_reference" in f for f in result.hard_failures)


def test_missing_parent_is_fine_for_a_standalone_short():
    agents = make_agents()
    result = run_short(make_plan(parent=None), [], agents, make_budget(), require_parent=False, enable_tts_preview=False)
    assert result.final_status == "PASS"


def test_critical_micro_arc_issue_becomes_a_hard_failure():
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "micro_arc", "layer": "STORY",
        "problem": "no real fix shown", "why_it_matters": "x", "recommended_intent": "add the fix",
        "repair_owner": "story_lead",
    }
    agents = make_agents(review_responses={"c1s": [ShortCritique(issues=[critical_issue])]})
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("micro_arc" in f for f in result.hard_failures)


def test_major_cold_hook_issue_does_not_force_a_hard_failure():
    """Cold-hook findings are feedback, not a mechanical hard gate (plan §20.10's
    hard list never mentions cold-hook strength)."""
    agents = make_agents(
        cold_hook_haiku=ColdHookVerdict(flagged=True, confidence="high"),
        review_responses={"c4s_gemini": [ColdHookCritique(issues=[{
            "issue_id": "I1", "severity": "major", "category": "hook", "layer": "STORY",
            "problem": "generic opening", "why_it_matters": "x", "recommended_intent": "make it specific",
            "repair_owner": "story_lead",
        }])]},
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "PASS"
    assert len(result.issues) == 1


def test_clean_cold_hook_never_escalates():
    agents = make_agents(cold_hook_haiku=ColdHookVerdict(flagged=False, confidence="high"))
    run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    # ColdHookCritique schema registered but never popped -- confirms no escalation call happened
    assert agents.review_agent._queues[ColdHookCritique] == [ColdHookCritique(issues=[])]


def test_grounding_scope_violation_is_a_hard_failure():
    agents = make_agents(review_responses={"cm": [ClaimMapperOutput(sentences=[
        {"scene_id": "payoff", "sentence_index": 0, "grounding_required": True, "grounding_refs": ["C999"]},
    ])]})
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("claim_outside_allowed_fact_set" in f for f in result.hard_failures)


def test_cm_and_c2b_never_see_a_claim_outside_the_allowed_scope():
    """Real gap found live (2026-09-10): CM was given the FULL claim
    registry, so it could (and did) ground a sentence to a real, correctly-
    classified claim that simply happened to sit outside this short's
    allowed_fact_ids. Fixed by scoping claims BEFORE they ever reach CM/C2b,
    not just detecting the violation after the fact."""
    from facts.models import Claim

    agents = make_agents()
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C999", source_unit="u9", claim="out of scope", type="mechanism"),
    ]
    run_short(make_plan(), claims, agents, make_budget(), enable_tts_preview=False)  # parent.allowed_fact_ids == ["C001"]

    cm_call = agents.review_agent.calls[0]  # CM is always the first review_agent call
    offered_ids = {c["claim_id"] for c in cm_call["payload"]["claim_registry"]}
    assert offered_ids == {"C001"}


def test_enable_tts_preview_false_is_an_explicit_opt_out_not_a_degradation():
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.degraded_capabilities == []
    assert result.measured_duration_seconds is None
    assert result.preview_audio is None


def test_a_successful_tts_synthesis_is_used_for_the_duration_gate_not_the_estimate(monkeypatch):
    from voice.tts_preview import TtsPreviewResult

    def fake_synthesize(text, voice=None):
        return TtsPreviewResult(audio_bytes=b"fake-mp3-bytes", measured_duration_seconds=42.0)

    import voice.tts_preview as tts_preview_module
    monkeypatch.setattr(tts_preview_module, "synthesize_narration_preview", fake_synthesize)

    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget())

    assert result.measured_duration_seconds == 42.0
    assert result.preview_audio == b"fake-mp3-bytes"
    assert result.degraded_capabilities == []


def test_a_tts_synthesis_failure_degrades_visibly_and_falls_back_to_the_estimate(monkeypatch):
    """A real network/service failure must never crash the run -- it
    degrades visibly (recorded, caps status at PASS_WARN) and falls back
    to the WPM estimate for the duration gate."""
    import voice.tts_preview as tts_preview_module

    def failing_synthesize(text, voice=None):
        raise RuntimeError("simulated: edge-tts service unreachable")

    monkeypatch.setattr(tts_preview_module, "synthesize_narration_preview", failing_synthesize)

    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget())

    assert result.measured_duration_seconds is None
    assert result.preview_audio is None
    assert any("synthesis failed" in d for d in result.degraded_capabilities)
    assert result.final_status != "PASS"  # degraded caps at PASS_WARN at best


@pytest.mark.integration
def test_live_tts_preview_produces_real_audio_and_a_measured_duration():
    """The one real end-to-end check: a real short run with the real
    edge-tts call enabled, confirming actual audio and a plausible
    measured duration come back (not just that the wiring calls a mock)."""
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=True)

    assert result.degraded_capabilities == []
    assert result.preview_audio is not None
    assert len(result.preview_audio) > 1000
    assert result.measured_duration_seconds is not None
    assert result.measured_duration_seconds > 0
