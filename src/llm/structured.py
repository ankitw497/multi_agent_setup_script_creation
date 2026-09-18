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


def schema_prompt(schema: type[BaseModel]) -> str:
    """Renders instructions + a schema's JSON Schema for in-prompt structured
    output (plan §3.4: "schema in prompt on both lanes"). Both backends see
    the same instruction shape regardless of lane."""
    return (
        "Respond with ONLY a single JSON object matching this schema — no "
        "prose, no markdown fences, no explanation before or after it.\n\n"
        f"JSON Schema:\n{schema.model_json_schema()}"
    )


class SchemaRepairFailed(RuntimeError):
    """Malformed output survived MAX_SCHEMA_REPAIRS attempts. Fail loudly — never let it through."""


RepairFn = Callable[[str, str, str], str]
"""(raw_text, validation_error, json_schema) -> repaired raw text. Bound to a Haiku call."""

WarnFn = Callable[[str], None]
"""A caller-supplied sink for a non-fatal repair-fidelity warning (see `validate_with_repair`)."""


def _list_field_lengths(data: object) -> dict[str, int]:
    if not isinstance(data, dict):
        return {}
    return {k: len(v) for k, v in data.items() if isinstance(v, list)}


def parse_json_loose(raw: str) -> dict:
    """Strip code fences, then json.loads. Raises json.JSONDecodeError on genuine garbage."""
    return json.loads(strip_fences(raw))


def validate(raw: str, schema: type[T]) -> T:
    """Parse + pydantic-validate raw text against schema. Raises on failure; no repair here."""
    data = parse_json_loose(raw)
    return schema.model_validate(data)


def validate_with_repair(raw: str, schema: type[T], repair_fn: RepairFn, warn_fn: WarnFn | None = None) -> T:
    """Try to validate; on failure, ask repair_fn (a Haiku call) to fix it, up to MAX_SCHEMA_REPAIRS times.

    repair_fn is injected rather than hard-wired to a specific backend so this
    stays testable without a live subprocess (see tests/llm/test_structured.py).

    PIPELINE_AUDIT_2026-09-17.md finding #10: repair success was judged ONLY by schema
    validity, never by whether the repair actually preserved content -- a plausible "repair"
    of a truncated response (the exact failure mode `litellm_backend.py`'s own docstring
    documents: a large list-typed field like `StoryPlan.scene_plan` cut off mid-array by a
    `max_tokens` ceiling) is to close the array early rather than regenerate it fully --
    syntactically valid, silently missing trailing items, and nothing here would ever notice.
    `warn_fn` is opt-in (default `None`, a no-op) -- this is a best-effort, shallow, top-
    level-only heuristic (comparing list-field lengths between the ORIGINAL response and the
    final repaired one), not a guarantee, so it's a caller-visible signal to log, never a
    reason to fail a call that otherwise validated correctly.
    """
    original_lengths: dict[str, int] = {}
    if warn_fn is not None:
        try:
            original_lengths = _list_field_lengths(parse_json_loose(raw))
        except Exception:
            original_lengths = {}  # the original was unparseable -- nothing to compare against

    attempt_raw = raw
    last_error: Exception | None = None

    for attempt in range(MAX_SCHEMA_REPAIRS + 1):
        try:
            result = validate(attempt_raw, schema)
            if warn_fn is not None and attempt > 0 and original_lengths:
                final_lengths = _list_field_lengths(result.model_dump())
                shrunk = {
                    k: (n, final_lengths[k]) for k, n in original_lengths.items()
                    if k in final_lengths and final_lengths[k] < n
                }
                if shrunk:
                    warn_fn(
                        f"{schema.__name__} repair may have silently dropped content -- "
                        f"list field(s) shrank from the original response (field: (original, repaired)): {shrunk}"
                    )
            return result
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
