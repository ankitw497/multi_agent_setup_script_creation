"""Tests for verification/hard/css_lint.py -- shared CSS custom-property validation
(2026-09-16, found via a real bug in html_synth/component_library.py's shared
BASE_STYLESHEET: `.math-block` referenced `var(--r_sm)`, underscore, while
`css_tokens()` only ever emits `--r-sm`, hyphen -- a real, silent property drop
undetected because nothing checked declared tokens against actual usage)."""
from verification.hard.css_lint import check_css_variable_references


def test_a_variable_used_but_never_declared_is_flagged():
    html = "<style>:root{--r-sm:10px;} .x{border-radius:var(--r_sm);}</style>"
    issues = check_css_variable_references(html)
    assert len(issues) == 1
    assert issues[0].code == "css_variable_never_declared"
    assert "--r_sm" in issues[0].detail


def test_the_historical_real_bug_is_caught():
    """The exact real regression this check exists for -- an underscore/hyphen
    mismatch between a declared token and its usage."""
    html = "<style>:root{--r-sm:10px;}</style><div style=\"border-radius:var(--r_sm)\"></div>"
    codes = {i.code for i in check_css_variable_references(html)}
    assert "css_variable_never_declared" in codes


def test_a_variable_declared_and_used_consistently_is_clean():
    html = "<style>:root{--r-sm:10px;} .x{border-radius:var(--r-sm);}</style>"
    assert check_css_variable_references(html) == []


def test_a_variable_declared_but_never_used_is_not_flagged():
    """This check is about usage pointing at nothing, not the reverse -- an unused
    token is dead weight at worst, never a silently-dropped style."""
    html = "<style>:root{--unused:10px; --r-sm:10px;} .x{border-radius:var(--r-sm);}</style>"
    assert check_css_variable_references(html) == []


def test_a_fallback_value_in_var_does_not_suppress_the_check():
    """var(--x, fallback) -- the fallback only applies at RUNTIME if --x is truly
    undefined anywhere in scope; a typo'd custom property name is still a real bug
    worth flagging, not silently "fine because there's a fallback"."""
    html = "<style>:root{--r-sm:10px;} .x{border-radius:var(--r_sm, 8px);}</style>"
    issues = check_css_variable_references(html)
    assert any("--r_sm" in i.detail for i in issues)


def test_multiple_undeclared_variables_are_each_reported():
    html = "<style>.x{color:var(--typo-one);background:var(--typo-two);}</style>"
    codes_detail = [i.detail for i in check_css_variable_references(html)]
    assert len(codes_detail) == 2


def test_underscored_variable_names_are_supported():
    """Custom property names can legitimately contain underscores -- the regex
    itself must not be the reason a real declaration/usage pair looks mismatched."""
    html = "<style>:root{--bg_2:white;} .x{color:var(--bg_2);}</style>"
    assert check_css_variable_references(html) == []
