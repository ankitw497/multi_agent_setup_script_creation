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
