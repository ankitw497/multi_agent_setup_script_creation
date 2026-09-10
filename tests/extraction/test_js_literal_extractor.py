"""Unit tests for the Acorn bridge wrapper (plan §6.2, Appendix G #1).

These call the real `node` binary (it's a project dependency, not a mock) --
still fast and free, just not a pure-Python unit test.
"""
import pytest

from extraction.js_literal_extractor import extract_literals, extract_literals_from_scripts


def test_extracts_scalar_and_nested_object_literals():
    result = extract_literals("const HIDDEN=3584, LAYERS=28; const cfg={a:{b:[1,2,3]}};")
    assert result.parse_ok
    assert result.literals == {"HIDDEN": 3584, "LAYERS": 28, "cfg": {"a": {"b": [1, 2, 3]}}}
    assert result.rejected == []


def test_rejects_function_calls_without_executing_them():
    result = extract_literals('const x = 5; const y = fetch("http://evil.example");')
    assert result.literals == {"x": 5}
    assert result.rejected[0].name == "y"
    assert result.rejected[0].kind == "CallExpression"


def test_rejects_require_and_never_executes_it():
    """Proves the earlier node:vm risk is gone: this must reject, not run, a
    line that would otherwise shell out."""
    result = extract_literals('const z = require("child_process").execSync("echo pwned");')
    assert "z" not in result.literals
    assert any(r.name == "z" for r in result.rejected)


def test_handles_empty_script_gracefully():
    result = extract_literals("")
    assert result.parse_ok
    assert result.literals == {}


def test_handles_genuinely_malformed_js():
    result = extract_literals("const x = ;;; this is not valid js {{{")
    assert result.parse_ok is False
    assert result.error


def test_negative_numeric_literals_are_supported():
    result = extract_literals("const offset = -12.5;")
    assert result.literals["offset"] == -12.5


def test_extract_literals_from_scripts_merges_multiple_blocks():
    result = extract_literals_from_scripts([
        "const A = 1;",
        "const B = 2;",
    ])
    assert result.literals == {"A": 1, "B": 2}


def test_extract_literals_from_scripts_keeps_rejections_from_every_block():
    result = extract_literals_from_scripts([
        'const ok1 = 1; const bad1 = fetch("x");',
        'const ok2 = 2; const bad2 = fetch("y");',
    ])
    assert result.literals == {"ok1": 1, "ok2": 2}
    assert {r.name for r in result.rejected} == {"bad1", "bad2"}
