"""Deterministic CSS custom-property validation, shared by long-form (render.py) and
shorts (vertical.py) -- both assemble pages from `html_synth/component_library.py`'s
shared `BASE_STYLESHEET` + `css_tokens()` pair, so a mismatch between the two (a
`var(--x)` reference with no matching `--x:` declaration) affects both formats equally.

Found live, 2026-09-16: `BASE_STYLESHEET`'s `.math-block` rule referenced `var(--r_sm)`
(underscore) while `css_tokens()` only ever emits `--r-sm` (hyphen, from
`name.replace('_', '-')`) -- a real, silent bug (an invalid `var()` reference just drops
the property, no visible error anywhere) that had been sitting in a page every H/short
render includes, undetected because nothing ever checked declared tokens against actual
usage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_VAR_USE_RE = re.compile(r"var\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,[^)]*)?\)")
_VAR_DECL_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:")


@dataclass
class CssLintIssue:
    code: str
    detail: str


def check_css_variable_references(html: str) -> list[CssLintIssue]:
    """Every `var(--x)` used in `html` must have a matching `--x:` declared somewhere
    in the same document -- a mechanical, false-positive-averse check (a custom
    property declared anywhere in the page's own <style> covers every use of it,
    regardless of selector scope; this doesn't model CSS cascade/inheritance, only
    "was this name ever spelled the same way twice")."""
    used = set(_VAR_USE_RE.findall(html))
    declared = set(_VAR_DECL_RE.findall(html))
    undeclared = sorted(used - declared)
    return [
        CssLintIssue(
            "css_variable_never_declared",
            f"var({name}) is used but {name} is never declared -- likely a typo against a similarly-named token",
        )
        for name in undeclared
    ]
