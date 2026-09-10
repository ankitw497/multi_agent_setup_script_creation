"""Tests for planning/source_understanding.py -- A1 (plan §5, §8)."""
from facts.models import AssumptionLedger, Claim, SourceUnit
from planning.models import SourceBrief
from planning.source_understanding import understand_source


class FakeStoryLead:
    def __init__(self, response: SourceBrief):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_brief() -> SourceBrief:
    return SourceBrief(
        topic="Scaled dot-product attention", core_question="Why divide by sqrt(d_k)?",
        viewer_problem="x", central_insight="y", novelty_statement="z",
    )


def test_passes_units_claims_and_ledger_to_the_story_lead():
    story_lead = FakeStoryLead(make_brief())
    units = [SourceUnit(id="u1", text="x")]
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]
    ledger = AssumptionLedger(model="Qwen2.5-7B")

    from llm.budget import BudgetCounter, DEFAULT_TIERS
    result = understand_source(units, claims, ledger, story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))

    assert result == make_brief()
    payload = story_lead.calls[0]["payload"]
    assert payload["units"][0]["id"] == "u1"
    assert payload["claims"][0]["claim_id"] == "C001"
    assert payload["assumption_ledger"]["model"] == "Qwen2.5-7B"


def test_claim_payload_includes_verification_status_so_a1_can_distinguish_confidence():
    """A rejected claim must be visibly labelled, never presented as fact
    indistinguishable from a verified one (plan §6.5)."""
    story_lead = FakeStoryLead(make_brief())
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="true thing", type="mechanism", verification_status="VERIFIED"),
        Claim(claim_id="C002", source_unit="u1", claim="false thing", type="numeric", verification_status="REJECTED"),
    ]
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    understand_source([], claims, AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))

    payload_claims = story_lead.calls[0]["payload"]["claims"]
    statuses = {c["claim_id"]: c["verification_status"] for c in payload_claims}
    assert statuses == {"C001": "VERIFIED", "C002": "REJECTED"}


def test_uses_pass_id_a1_and_source_analyst_mode():
    story_lead = FakeStoryLead(make_brief())
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    understand_source([], [], AssumptionLedger(), story_lead, BudgetCounter(tier=DEFAULT_TIERS["longform"]))
    call = story_lead.calls[0]
    assert call["pass_id"] == "A1"
    assert call["mode"] == "SOURCE_ANALYST"
    assert call["schema"] is SourceBrief
