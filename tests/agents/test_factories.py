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


def test_story_lead_alias_override_pins_a_specific_model():
    """STORY_IMPROVEMENT_PLAN.md Phase 4: lets a live A/B comparison run
    pin story_lead to a specific alias (e.g. the reasoning-capable
    gpt-5.6-sol) without touching the tier-based default, which stays
    gpt-4o until a real comparison justifies changing it."""
    agent = make_story_lead(DummyClient(), alias_override="openai_story_strong_gpt56")
    assert agent.model_alias == "openai_story_strong_gpt56"
    assert agent.model_resolved == "gpt-5.6-sol"


def test_story_lead_default_alias_carries_its_own_max_tokens_ceiling():
    """ERR-021's fix (max_tokens=4000 for A2) moved from a hardcoded
    override in story_planner.py into per-alias config (2026-09-11) so a
    different alias can carry a different ceiling -- confirms gpt-4o keeps
    the exact same effective value as before the move."""
    agent = make_story_lead(DummyClient())
    assert agent.default_max_tokens == 4000


def test_story_lead_gpt56_alias_pins_reasoning_effort_and_a_larger_ceiling():
    """Real finding (2026-09-11, STORY_IMPROVEMENT_PLAN.md Phase 4): with
    reasoning_effort left unset and max_tokens=4000 inherited from gpt-4o's
    own value, a real A2 call against gpt-5.6-sol burned the entire ceiling
    on hidden reasoning and returned an empty StoryStructure (beats=[]) --
    max_tokens is a COMBINED budget over reasoning + visible output for a
    reasoning-capable model, not a separate reasoning allowance. Pinned
    explicitly (not left unset) and raised, pending live re-verification."""
    agent = make_story_lead(DummyClient(), alias_override="openai_story_strong_gpt56")
    assert agent.default_reasoning_effort == "medium"
    assert agent.default_max_tokens == 10000


def test_story_lead_alias_override_takes_precedence_over_tier():
    agent = make_story_lead(DummyClient(), tier="mini", alias_override="openai_story_strong_gpt56")
    assert agent.model_alias == "openai_story_strong_gpt56"


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
