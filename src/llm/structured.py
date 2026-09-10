"""Structured output: schema in prompt -> validate -> repair on Haiku <=2 -> fail loudly (plan §3.4).

Both lanes produce raw text; this module is where that text becomes a typed
pydantic object. Repair always runs on the free subscription lane (Haiku),
never on a paid model — a malformed-JSON retry should never cost money.
"""
from __future__ import annotations

import json
import re
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from .backends.claude_cli import strip_fences

T = TypeVar("T", bound=BaseModel)

MAX_SCHEMA_REPAIRS = 2  # plan §14 revision budgets


class SchemaRepairFailed(RuntimeError):
    """Malformed output survived MAX_SCHEMA_REPAIRS attempts. Fail loudly — never let it through."""


RepairFn = Callable[[str, str, str], str]
"""(raw_text, validation_error, json_schema) -> repaired raw text. Bound to a Haiku call."""


def parse_json_loose(raw: str) -> dict:
    """Strip code fences, then json.loads. Raises json.JSONDecodeError on genuine garbage."""
    return json.loads(strip_fences(raw))


def validate(raw: str, schema: type[T]) -> T:
    """Parse + pydantic-validate raw text against schema. Raises on failure; no repair here."""
    data = parse_json_loose(raw)
    return schema.model_validate(data)


def validate_with_repair(raw: str, schema: type[T], repair_fn: RepairFn) -> T:
    """Try to validate; on failure, ask repair_fn (a Haiku call) to fix it, up to MAX_SCHEMA_REPAIRS times.

    repair_fn is injected rather than hard-wired to a specific backend so this
    stays testable without a live subprocess (see tests/llm/test_structured.py).
    """
    attempt_raw = raw
    last_error: Exception | None = None

    for attempt in range(MAX_SCHEMA_REPAIRS + 1):
        try:
            return validate(attempt_raw, schema)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            if attempt == MAX_SCHEMA_REPAIRS:
                break
            attempt_raw = repair_fn(
                attempt_raw, str(e), json.dumps(schema.model_json_schema())
            )

    raise SchemaRepairFailed(
        f"{schema.__name__} failed to validate after {MAX_SCHEMA_REPAIRS} repair attempts: {last_error}"
    )
