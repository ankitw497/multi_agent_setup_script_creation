"""Tests for the 5 concrete agent factories (plan §2) -- read real config/models.yaml."""
from agents.html_author import make_html_author
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


def test_html_author_is_sonnet_on_the_subscription_lane():
    """STORY_IMPROVEMENT_PLAN.md Phase 14: this identity was always part of the original
    design (`agents/__init__.py`'s own docstring listed it from the start) but was never
    actually built -- H/H-repair ran under narration_lead instead, whose own base prompt
    ("write natural spoken narration... for listening") directly contradicted H's own task
    prompt ("NOT spoken narration"). Same model/lane as narration_lead, distinct identity."""
    agent = make_html_author(DummyClient())
    assert agent.name == "html_author"
    assert agent.lane == "subscription"
    assert agent.model_resolved == "claude-sonnet-5"


def test_story_lead_defaults_to_the_strong_tier():
    """2026-09-16 (explicit user decision, STORY_IMPROVEMENT_PLAN.md Phase 4): the "strong"
    tier now resolves to openai_story_strong_gpt56 (gpt-5.6-sol), not openai_story_strong
    (gpt-4o). This OVERRIDES Phase 4's own completed comparison, which found gpt-5.6-sol
    produced a structurally LESS coherent plan (2 genuine coherence hard failures gpt-4o
    didn't have) for 65% MORE cost, and explicitly recommended against promoting it -- the
    user was shown that finding directly and chose to proceed anyway. gpt-4o remains
    available via `alias_override="openai_story_strong"` for rollback."""
    agent = make_story_lead(DummyClient())
    assert agent.name == "story_lead"
    assert agent.lane == "paid_api"
    assert agent.model_alias == "openai_story_strong_gpt56"
    assert agent.model_resolved == "gpt-5.6-sol"


def test_story_lead_mini_tier_is_selectable():
    agent = make_story_lead(DummyClient(), tier="mini")
    assert agent.model_alias == "openai_story_mini"
    assert agent.model_resolved == "gpt-4o-mini"


def test_story_lead_alias_override_pins_a_specific_model():
    """`alias_override` still lets a caller pin any alias explicitly -- e.g. gpt-4o
    (`openai_story_strong`) for a rollback, now that the tier default is gpt-5.6-sol."""
    agent = make_story_lead(DummyClient(), alias_override="openai_story_strong")
    assert agent.model_alias == "openai_story_strong"
    assert agent.model_resolved == "gpt-4o"


def test_story_lead_default_alias_carries_its_own_max_tokens_ceiling():
    """ERR-021's fix (max_tokens per-alias, not hardcoded in story_planner.py) means each
    alias carries its own ceiling -- confirms the current default (gpt-5.6-sol) resolves to
    its own pinned 10000, not gpt-4o's 4000 (see the override test below for that value)."""
    agent = make_story_lead(DummyClient())
    assert agent.default_max_tokens == 10000


def test_story_lead_gpt4o_alias_override_keeps_its_own_max_tokens_ceiling():
    agent = make_story_lead(DummyClient(), alias_override="openai_story_strong")
    assert agent.default_max_tokens == 4000


def test_story_lead_gpt56_alias_pins_reasoning_effort_and_a_larger_ceiling():
    """Real finding (2026-09-11, STORY_IMPROVEMENT_PLAN.md Phase 4): with
    reasoning_effort left unset and max_tokens=4000 inherited from gpt-4o's
    own value, a real A2 call against gpt-5.6-sol burned the entire ceiling
    on hidden reasoning and returned an empty StoryStructure (beats=[]) --
    max_tokens is a COMBINED budget over reasoning + visible output for a
    reasoning-capable model, not a separate reasoning allowance. Pinned
    explicitly (not left unset) and raised -- now the live default, not just
    an override."""
    agent = make_story_lead(DummyClient())
    assert agent.default_reasoning_effort == "medium"
    assert agent.default_max_tokens == 10000


def test_story_lead_alias_override_takes_precedence_over_tier():
    agent = make_story_lead(DummyClient(), tier="mini", alias_override="openai_story_strong")
    assert agent.model_alias == "openai_story_strong"


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


def test_all_five_agents_have_distinct_base_prompts():
    """Sanity check that the identities are actually different, not copies
    of one generic prompt (plan §2 -- five distinct identities). Confirms
    Phase 14's html_author isn't just narration_lead's prompt copied over --
    the exact contradiction (narration_lead's "write for listening" vs. H's
    own "NOT spoken narration" task prompt) this identity split fixes."""
    prompts = {
        make_worker(DummyClient()).base_system_prompt,
        make_story_lead(DummyClient()).base_system_prompt,
        make_narration_lead(DummyClient()).base_system_prompt,
        make_review_lead(DummyClient()).base_system_prompt,
        make_html_author(DummyClient()).base_system_prompt,
    }
    assert len(prompts) == 5
