"""Shared test helpers (Phase 1: contract round-trip testing).

Golden-fixture strategy (see BUILD_PLAN.md Phase 1): substantial/aggregate
contracts get a real JSON fixture file under tests/fixtures/<package>/ that
can be inspected and reused later; simple "leaf" models are round-tripped
from an inline literal in their test file instead of a one-line fixture
file each. Every model in plan §5 gets at least one round-trip test either
way — see each package's test_models.py for its own inventory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

FIXTURES = Path(__file__).parent / "fixtures"

T = TypeVar("T", bound=BaseModel)


def load_fixture(package: str, name: str) -> dict:
    return json.loads((FIXTURES / package / f"{name}.json").read_text())


def roundtrip(model_cls: type[T], data: dict) -> T:
    """validate -> dump to JSON -> re-validate -> assert the two are equal.

    This is the contract test itself: if a model can't survive this, its
    schema doesn't actually round-trip, which is Phase 1's "done when".
    """
    first = model_cls.model_validate(data)
    dumped = json.loads(first.model_dump_json())
    second = model_cls.model_validate(dumped)
    assert first == second
    return first


def roundtrip_fixture(model_cls: type[T], package: str, name: str) -> T:
    return roundtrip(model_cls, load_fixture(package, name))
