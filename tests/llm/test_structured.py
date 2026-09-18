"""Unit tests for llm/structured.py — plan §3.4 (validate -> repair on Haiku <=2 -> fail loudly)."""
import pytest
from pydantic import BaseModel

from llm.structured import (
    MAX_SCHEMA_REPAIRS,
    SchemaRepairFailed,
    parse_json_loose,
    validate,
    validate_with_repair,
)


class Toy(BaseModel):
    name: str
    count: int


class ToyWithList(BaseModel):
    name: str
    items: list[str] = []


def test_parse_json_loose_strips_fences():
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_validate_succeeds_on_well_formed_output():
    obj = validate('{"name": "x", "count": 3}', Toy)
    assert obj == Toy(name="x", count=3)


def test_validate_raises_on_malformed_json():
    with pytest.raises(Exception):
        validate("not json at all", Toy)


def test_validate_raises_on_schema_violation():
    with pytest.raises(Exception):
        validate('{"name": "x"}', Toy)  # missing required field "count"


def test_validate_with_repair_succeeds_immediately_when_valid():
    calls = []

    def repair_fn(raw, error, schema):
        calls.append(raw)
        return raw  # should never be reached

    obj = validate_with_repair('{"name": "x", "count": 1}', Toy, repair_fn)
    assert obj == Toy(name="x", count=1)
    assert calls == []


def test_validate_with_repair_fixes_malformed_json_on_first_attempt():
    def repair_fn(raw, error, schema):
        return '{"name": "x", "count": 1}'

    obj = validate_with_repair("garbage", Toy, repair_fn)
    assert obj == Toy(name="x", count=1)


def test_validate_with_repair_stops_at_max_attempts_and_fails_loudly():
    """Malformed data must never quietly reach a later stage (plan §3.4)."""
    call_count = {"n": 0}

    def always_broken_repair_fn(raw, error, schema):
        call_count["n"] += 1
        return "still garbage"

    with pytest.raises(SchemaRepairFailed):
        validate_with_repair("garbage", Toy, always_broken_repair_fn)

    assert call_count["n"] == MAX_SCHEMA_REPAIRS


def test_repair_fn_receives_the_validation_error_and_schema():
    seen = {}

    def repair_fn(raw, error, schema):
        seen["error"] = error
        seen["schema"] = schema
        return '{"name": "x", "count": 1}'

    validate_with_repair("garbage", Toy, repair_fn)
    assert "count" in seen["schema"] or "name" in seen["schema"]
    assert seen["error"]


# ---- warn_fn / content-fidelity check (PIPELINE_AUDIT_2026-09-17.md finding #10) ----------

def test_warn_fn_is_never_called_when_no_repair_was_needed():
    warnings = []
    obj = validate_with_repair(
        '{"name": "x", "items": ["a", "b", "c"]}', ToyWithList, lambda *a: "should not run",
        warn_fn=warnings.append,
    )
    assert obj.items == ["a", "b", "c"]
    assert warnings == []


def test_warn_fn_fires_when_a_repair_shrinks_a_list_field():
    """The real failure shape this check exists for: a repair that fixes the actual
    validation problem (a missing required field) but ALSO silently drops list items along
    the way -- syntactically valid and schema-correct, but the original's own 5 "items"
    quietly became 2. The original here is valid JSON (so it's ValidationError, not
    JSONDecodeError, that triggers the repair) -- a genuinely truncated, unparseable
    original has nothing for this heuristic to compare against at all (see the dedicated
    "unparseable original" test below)."""
    def repair_fn(raw, error, schema):
        return '{"name": "x", "items": ["a", "b"]}'  # adds the missing "name", but also drops 3 items

    warnings = []
    obj = validate_with_repair(
        '{"items": ["a", "b", "c", "d", "e"]}', ToyWithList, repair_fn,  # valid JSON, missing required "name"
        warn_fn=warnings.append,
    )
    assert obj.items == ["a", "b"]
    assert len(warnings) == 1
    assert "items" in warnings[0]
    assert "ToyWithList" in warnings[0]


def test_warn_fn_stays_silent_when_a_repair_does_not_shrink_anything():
    def repair_fn(raw, error, schema):
        return '{"name": "x", "items": ["a", "b", "c"]}'  # adds "name", same list length

    warnings = []
    validate_with_repair('{"items": ["a", "b", "c"]}', ToyWithList, repair_fn, warn_fn=warnings.append)
    assert warnings == []


def test_warn_fn_is_opt_in_and_defaults_to_no_check_at_all():
    """Backward compatible by construction -- every existing caller that never passes
    warn_fn must see byte-for-byte the same behavior as before this fix."""
    def repair_fn(raw, error, schema):
        return '{"name": "x", "items": ["a"]}'  # would shrink from an original of 5

    # no warn_fn given -- must not raise, must not attempt the comparison at all
    obj = validate_with_repair('{"name": "x", "items": ["a", "b", "c", "d", "e"', ToyWithList, repair_fn)
    assert obj.items == ["a"]


def test_warn_fn_handles_an_unparseable_original_gracefully():
    """The original raw text might not be parseable JSON at all (genuine garbage, not just
    truncated) -- there's nothing meaningful to compare against, so this must never crash."""
    def repair_fn(raw, error, schema):
        return '{"name": "x", "items": ["a", "b"]}'

    warnings = []
    obj = validate_with_repair("not json at all, just garbage", ToyWithList, repair_fn, warn_fn=warnings.append)
    assert obj.items == ["a", "b"]
    assert warnings == []  # nothing to compare the repaired result against
