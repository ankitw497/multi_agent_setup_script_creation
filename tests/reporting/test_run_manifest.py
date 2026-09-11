"""Tests for reporting/run_manifest.py (V1C's narrow degrade-visibly scope)."""
from reporting.run_manifest import build_run_manifest


def test_clean_run_still_gets_a_manifest_with_an_empty_list():
    """Absence would be ambiguous (never checked vs checked-and-clean) --
    a clean run must still produce the file, just with nothing in it."""
    manifest = build_run_manifest("v01", [])
    assert manifest.run_id == "v01"
    assert manifest.degraded_capabilities == []


def test_degraded_capabilities_are_carried_through():
    manifest = build_run_manifest("v01", ["playwright_rendered_checks: playwright not installed"])
    assert manifest.degraded_capabilities == ["playwright_rendered_checks: playwright not installed"]
