"""Tests for config/loader.py -- reads the real config/models.yaml (plan §16)."""
from config.loader import resolve_model


def test_resolve_model_returns_resolved_reasoning_effort_and_max_tokens():
    resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", "gemini_review_flash")
    assert resolved == "gemini/gemini-3.6-flash"
    assert reasoning_effort == "none"
    assert max_tokens is None  # this alias has no max_tokens override in config


def test_resolve_model_returns_none_for_an_alias_with_no_reasoning_effort_set():
    resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", "openai_story_mini")
    assert resolved == "gpt-4o-mini"
    assert reasoning_effort is None


def test_resolve_model_returns_max_tokens_when_configured():
    """STORY_IMPROVEMENT_PLAN.md Phase 4: config/models.yaml carries a
    per-alias max_tokens override (moved out of a hardcoded call-site
    literal in story_planner.py) so a different story_lead alias can carry
    a different ceiling."""
    resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", "openai_story_strong")
    assert resolved == "gpt-4o"
    assert max_tokens == 4000


def test_resolve_model_for_the_reasoning_capable_gpt56_alias():
    resolved, reasoning_effort, max_tokens = resolve_model("paid_api_lane", "openai_story_strong_gpt56")
    assert resolved == "gpt-5.6-sol"
    assert reasoning_effort == "medium"
    assert max_tokens == 10000
