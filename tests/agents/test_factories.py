"""Tests for the 4 concrete agent factories (plan §2) -- read real config/models.yaml."""
from agents.narration_lead import make_narration_lead
from agents.review_lead import make_review_lead
from agents.story_lead import make_story_lead
from agents.worker import make_worker


class DummyClient:
    pass


def test_worker_is_haiku_on_the_subscription_lane():
    agent = make_worker(DummyClient())
    assert agent.name == "worker"
    assert agent.lane == "subscription"
    assert agent.model_resolved == "claude-haiku-4-5-20251001"


def test_narration_lead_is_sonnet_on_the_subscription_lane():
    agent = make_narration_lead(DummyClient())
    assert agent.name == "narration_lead"
    assert agent.lane == "subscription"
    assert agent.model_resolved == "claude-sonnet-5"


def test_story_lead_defaults_to_the_strong_tier():
    agent = make_story_lead(DummyClient())
    assert agent.name == "story_lead"
    assert agent.lane == "paid_api"
    assert agent.model_alias == "openai_story_strong"


def test_story_lead_mini_tier_is_selectable():
    agent = make_story_lead(DummyClient(), tier="mini")
    assert agent.model_alias == "openai_story_mini"
    assert agent.model_resolved == "gpt-4o-mini"


def test_review_lead_strong_tier_caps_reasoning_to_low():
    """Cost-discipline fix (2026-09-10): the strong-tier Gemini model reasons
    by default and, left unset, burned $0.218/11 calls on hidden reasoning
    tokens alone. "low" was verified live to keep full-quality output while
    bounding the reasoning-token spend."""
    agent = make_review_lead(DummyClient(), tier="strong")
    assert agent.model_resolved == "gemini/gemini-3.1-pro-preview"
    assert agent.default_reasoning_effort == "low"


def test_review_lead_flash_tier_defaults_reasoning_to_none():
    """This is the real cost-trap fix from Phase 0 -- the flash tier must
    default to reasoning_effort="none" or a cheap call becomes expensive."""
    agent = make_review_lead(DummyClient(), tier="flash")
    assert agent.model_resolved == "gemini/gemini-3.6-flash"
    assert agent.default_reasoning_effort == "none"


def test_all_four_agents_have_distinct_base_prompts():
    """Sanity check that the identities are actually different, not copies
    of one generic prompt (plan §2 -- five distinct identities)."""
    prompts = {
        make_worker(DummyClient()).base_system_prompt,
        make_story_lead(DummyClient()).base_system_prompt,
        make_narration_lead(DummyClient()).base_system_prompt,
        make_review_lead(DummyClient()).base_system_prompt,
    }
    assert len(prompts) == 4
