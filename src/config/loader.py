"""Tiny YAML config loaders (plan §16). Business logic never hard-codes a
model id or a threshold -- it reads one of these."""
from __future__ import annotations

from functools import lru_cache

import yaml

from . import CONFIG_DIR


@lru_cache
def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


def models_config() -> dict:
    return load_yaml("models.yaml")


def budget_config() -> dict:
    return load_yaml("budget.yaml")


def resolve_model(lane: str, alias: str) -> tuple[str, str | None, int | None]:
    """(model_resolved, reasoning_effort, max_tokens) for one alias, e.g.
    ("paid_api_lane", "gemini_review_flash"). `max_tokens` is the per-alias
    output-token ceiling (reasoning tokens count against it for a
    reasoning-capable model, per the provider's own combined-budget
    behavior) -- None means "use the backend's own default"."""
    entry = models_config()[lane][alias]
    return entry["resolved"], entry.get("reasoning_effort"), entry.get("max_tokens")


_LANE_KEY_TO_AGENT_LANE = {"subscription_lane": "subscription", "paid_api_lane": "paid_api"}


def resolve_model_any_lane(alias: str) -> tuple[str, str, str | None, int | None]:
    """(agent_lane, model_resolved, reasoning_effort, max_tokens) for an alias whose lane
    isn't known in advance -- searches `subscription_lane` then `paid_api_lane`. Lets a
    caller (story_lead's `--story-lead-alias`) select between two aliases that live in
    DIFFERENT lanes (e.g. `opus`, subscription, vs `openai_story_strong_gpt56`, paid_api)
    through the same plain string, without the caller needing to know which lane bills it.
    `agent_lane` matches `agents.base.Agent.lane`'s own values ("subscription"/"paid_api").
    Raises KeyError (naming both lanes searched) if the alias exists in neither."""
    config = models_config()
    for lane_key, agent_lane in _LANE_KEY_TO_AGENT_LANE.items():
        entry = config.get(lane_key, {}).get(alias)
        if entry is not None:
            return agent_lane, entry["resolved"], entry.get("reasoning_effort"), entry.get("max_tokens")
    raise KeyError(f"model alias {alias!r} not found in subscription_lane or paid_api_lane")
