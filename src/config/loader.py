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


def resolve_model(lane: str, alias: str) -> tuple[str, str | None]:
    """(model_resolved, reasoning_effort) for one alias, e.g. ("paid_api_lane", "gemini_review_flash")."""
    entry = models_config()[lane][alias]
    return entry["resolved"], entry.get("reasoning_effort")
