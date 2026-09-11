"""Tests for narration/short_generator.py -- B1 short rhythm (plan §20.7, §20.8)."""
from facts.models import Claim
from narration.short_generator import GeneratedShortNarration, generate_short_narration
from planning.shorts_models import HookEvent, ShortParent, ShortPlan


class FakeNarrationLead:
    def __init__(self, response: GeneratedShortNarration):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0),
    )
    base.update(overrides)
    return ShortPlan(**base)


def test_prompt_requires_a_spoken_bridge_line_when_mode_is_spoken():
    """Real gap found 2026-09-11 (user-reported): a real short with
    `bridge.mode="SPOKEN"` produced a clean payoff with no follow-up/
    subscribe line at all -- the prompt's blanket "no reserved subscribe
    slot" framing evidently outweighed the later conditional instruction.
    Tightened to make the SPOKEN case explicitly REQUIRED and to scope the
    "don't invent one" rule to only the other three modes."""
    from narration.short_generator import TASK_PROMPT

    assert "REQUIRED" in TASK_PROMPT
    assert "SPOKEN" in TASK_PROMPT
    assert "NONE" in TASK_PROMPT


def test_returns_one_scene_per_segment():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[
        {"segment": "hook", "sentences": [{"text": "x", "sentence_type": "transition"}]},
        {"segment": "setup", "sentences": []},
        {"segment": "mechanism", "sentences": []},
        {"segment": "payoff", "sentences": []},
    ]))
    result = generate_short_narration(make_plan(), [], narration_lead)
    assert [s.scene_id for s in result] == ["hook", "setup", "mechanism", "payoff"]


def test_only_claims_within_allowed_fact_ids_are_offered():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="allowed", type="mechanism"),
        Claim(claim_id="C002", source_unit="u1", claim="not allowed", type="mechanism"),
    ]
    generate_short_narration(make_plan(), claims, narration_lead)
    offered = {c["claim_id"] for c in narration_lead.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_no_parent_offers_all_claims():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]
    generate_short_narration(make_plan(parent=None), claims, narration_lead)
    offered = {c["claim_id"] for c in narration_lead.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_uses_pass_id_b1s_and_short_first_draft_mode():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    generate_short_narration(make_plan(), [], narration_lead)
    call = narration_lead.calls[0]
    assert call["pass_id"] == "B1s"
    assert call["mode"] == "SHORT_FIRST_DRAFT"
