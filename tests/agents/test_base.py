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
