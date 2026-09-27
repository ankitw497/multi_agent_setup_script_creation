"""Tests for agents/base.py -- the shared Agent shape (plan §2)."""
from pydantic import BaseModel

from agents.base import Agent
from llm.budget import BudgetCounter, DEFAULT_TIERS
from llm.client import StructuredCallResult
from llm.usage import UsageRecord


class Toy(BaseModel):
    x: int


class FakeClient:
    """Captures exactly what Agent.run() sent it, without touching a real backend."""

    def __init__(self):
        self.subscription_calls = []
        self.paid_calls = []

    def call_structured_subscription(self, **kwargs):
        self.subscription_calls.append(kwargs)
        record = UsageRecord(
            run_id="r1", agent=kwargs["agent"], pass_id=kwargs["pass_id"], mode=kwargs["mode"],
            lane="subscription", model_alias=kwargs["model_alias"], model_resolved=kwargs["model_resolved"],
        )
        return StructuredCallResult(value=Toy(x=1), usage_record=record)

    def call_structured_paid(self, **kwargs):
        self.paid_calls.append(kwargs)
        record = UsageRecord(
            run_id="r1", agent=kwargs["agent"], pass_id=kwargs["pass_id"], mode=kwargs["mode"],
            lane="paid_api", model_alias=kwargs["model_alias"], model_resolved="resolved-x",
        )
        return StructuredCallResult(value=Toy(x=2), usage_record=record)


def test_subscription_agent_calls_the_subscription_backend_and_needs_no_budget():
    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse")

    result = agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="extract things",
                        payload={"a": 1}, schema=Toy)

    assert result == Toy(x=1)
    assert len(client.subscription_calls) == 1
    call = client.subscription_calls[0]
    assert call["agent"] == "worker"
    assert "be terse" in call["system_prompt"]
    assert "extract things" in call["system_prompt"]
    assert "JSON Schema" in call["system_prompt"]  # schema_prompt() was embedded


def test_subscription_agents_default_reasoning_effort_reaches_the_backend():
    """2026-09-24: the opus alias (config/models.yaml) carries reasoning_effort: "medium",
    mapped by claude_cli.py to the CLI's own `--effort` flag -- must actually reach
    call_structured_subscription, not just sit unused on the Agent like it used to."""
    client = FakeClient()
    agent = Agent(name="story_lead", lane="subscription", client=client, model_alias="opus",
                  model_resolved="claude-opus-5-5", base_system_prompt="reason about stories",
                  default_reasoning_effort="medium")

    agent.run(pass_id="A2", mode="PLAN", task_prompt="plan it", payload={"a": 1}, schema=Toy)

    assert client.subscription_calls[0]["reasoning_effort"] == "medium"


def test_subscription_agent_with_no_default_reasoning_effort_passes_none():
    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse")

    agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="extract things", payload={"a": 1}, schema=Toy)

    assert client.subscription_calls[0]["reasoning_effort"] is None


def test_paid_agent_requires_a_budget_counter():
    import pytest

    client = FakeClient()
    agent = Agent(name="story_lead", lane="paid_api", client=client, model_alias="openai_story_mini",
                  model_resolved="gpt-4o-mini", base_system_prompt="plan the story")
    with pytest.raises(ValueError, match="require a BudgetCounter"):
        agent.run(pass_id="A2", mode="PLAN", task_prompt="x", payload={}, schema=Toy)


def test_paid_agent_calls_the_paid_backend_with_budget():
    client = FakeClient()
    agent = Agent(name="story_lead", lane="paid_api", client=client, model_alias="openai_story_mini",
                  model_resolved="gpt-4o-mini", base_system_prompt="plan the story")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    result = agent.run(pass_id="A2", mode="PLAN", task_prompt="x", payload={}, schema=Toy,
                        budget=budget, estimated_usd=0.01)

    assert result == Toy(x=2)
    assert client.paid_calls[0]["budget"] is budget


def test_timeout_s_reaches_the_paid_backend():
    """Real bug found live 2026-09-12: the paid-lane branch never forwarded
    timeout_s to call_structured_paid() at all, so it was silently dropped
    for every GPT/Gemini call -- confirmed via a real gpt-5.6-sol run that
    hung 6+ hours with no timeout to ever cut it off."""
    client = FakeClient()
    agent = Agent(name="story_lead", lane="paid_api", client=client, model_alias="openai_story_mini",
                  model_resolved="gpt-4o-mini", base_system_prompt="plan the story")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="A2", mode="PLAN", task_prompt="x", payload={}, schema=Toy,
              budget=budget, estimated_usd=0.01, timeout_s=45)

    assert client.paid_calls[0]["timeout_s"] == 45


def test_default_reasoning_effort_is_used_when_not_overridden():
    client = FakeClient()
    agent = Agent(name="review_lead", lane="paid_api", client=client, model_alias="gemini_review_flash",
                  model_resolved="gemini/gemini-3.6-flash", base_system_prompt="review",
                  default_reasoning_effort="none")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="C5", mode="STYLE", task_prompt="x", payload={}, schema=Toy, budget=budget)

    assert client.paid_calls[0]["reasoning_effort"] == "none"


def test_explicit_reasoning_effort_overrides_the_agent_default():
    client = FakeClient()
    agent = Agent(name="review_lead", lane="paid_api", client=client, model_alias="gemini_review_strong",
                  model_resolved="gemini/gemini-3.1-pro-preview", base_system_prompt="review",
                  default_reasoning_effort="none")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="C1", mode="STORY_CRITIC", task_prompt="x", payload={}, schema=Toy,
              budget=budget, reasoning_effort="high")

    assert client.paid_calls[0]["reasoning_effort"] == "high"


def test_images_are_forwarded_to_the_paid_backend_only():
    """V1C: C3's visual critic needs to send screenshots to Gemini (paid_api
    lane) -- images must reach call_structured_paid untouched."""
    client = FakeClient()
    agent = Agent(name="review_lead", lane="paid_api", client=client, model_alias="gemini_review_flash",
                  model_resolved="gemini/gemini-3.6-flash", base_system_prompt="review")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="C3", mode="VISUAL_AUDITOR", task_prompt="x", payload={}, schema=Toy,
              budget=budget, images=["data:image/png;base64,AAAA"])

    assert client.paid_calls[0]["images"] == ["data:image/png;base64,AAAA"]


def test_a_subscription_agent_rejects_images():
    """The Claude CLI backend has no multimodal support -- a caller handing
    images to a subscription-lane agent must fail loudly, not silently drop
    them."""
    import pytest

    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse")

    with pytest.raises(ValueError, match="multimodal"):
        agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="x", payload={}, schema=Toy,
                  images=["data:image/png;base64,AAAA"])


def test_enable_web_search_is_forwarded_to_the_paid_backend_only():
    """STORY_IMPROVEMENT_PLAN.md Phase 23: C2a needs real web search reaching
    call_structured_paid untouched, the same forwarding pattern already proven for images."""
    client = FakeClient()
    agent = Agent(name="review_lead", lane="paid_api", client=client, model_alias="gemini_review_strong",
                  model_resolved="gemini/gemini-3.1-pro-preview", base_system_prompt="review")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="C2a", mode="VERIFY_SOURCE_CLAIMS", task_prompt="x", payload={}, schema=Toy,
              budget=budget, enable_web_search=True)

    assert client.paid_calls[0]["enable_web_search"] is True


def test_enable_web_search_defaults_to_false():
    client = FakeClient()
    agent = Agent(name="review_lead", lane="paid_api", client=client, model_alias="gemini_review_strong",
                  model_resolved="gemini/gemini-3.1-pro-preview", base_system_prompt="review")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    agent.run(pass_id="C1", mode="STORY_CRITIC", task_prompt="x", payload={}, schema=Toy, budget=budget)

    assert client.paid_calls[0]["enable_web_search"] is False


def test_a_subscription_agent_rejects_enable_web_search():
    """The Claude CLI backend's --max-turns 1 makes real tool use non-functional -- a
    caller enabling web search on a subscription-lane agent must fail loudly, the same
    treatment as images."""
    import pytest

    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse")

    with pytest.raises(ValueError, match="max-turns"):
        agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="x", payload={}, schema=Toy,
                  enable_web_search=True)


def test_a_subscription_agent_rejects_max_tokens():
    """Real gap found live, 2026-09-27 audit: `default_max_tokens`/`call_structured_
    subscription` never actually forwarded this anywhere -- the Claude CLI backend has no
    output-token-limiting flag at all (confirmed against `claude -p --help`), unlike the
    paid-API lane. A caller (or a config default) setting max_tokens on a subscription-lane
    agent must fail loudly, the same treatment as images/enable_web_search, rather than
    silently do nothing."""
    import pytest

    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse")

    with pytest.raises(ValueError, match="output-token-limiting"):
        agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="x", payload={}, schema=Toy,
                  max_tokens=4000)


def test_a_subscription_agent_rejects_a_configured_default_max_tokens_too():
    """Same rejection must apply when max_tokens comes from the agent's own
    default_max_tokens (set from config/models.yaml), not just an explicit per-call
    argument -- a config value that silently did nothing would be just as real a gap as a
    caller's own argument being dropped."""
    import pytest

    client = FakeClient()
    agent = Agent(name="worker", lane="subscription", client=client, model_alias="haiku",
                  model_resolved="claude-haiku-4-5-20251001", base_system_prompt="be terse",
                  default_max_tokens=4000)

    with pytest.raises(ValueError, match="output-token-limiting"):
        agent.run(pass_id="S2b", mode="EXTRACT", task_prompt="x", payload={}, schema=Toy)
