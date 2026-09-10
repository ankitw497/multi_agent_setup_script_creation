"""S2a — deterministic seeds: numbers, equations, JS constants, formulas (plan §6.3, §8).

No LLM anywhere in this module. Two things it deliberately does NOT do:

1. It does not rename or unit-scale a JS scalar into a typed AssumptionLedger
   field (e.g. a constant named PARAMS is not assumed to be "billions" and
   multiplied by 1e9). That is a semantic judgement about what a source's
   naming convention means, not a deterministic fact -- guessing it wrong
   would silently corrupt the ledger. Scalars are passed through as-is,
   under their own (lowercased) name, via AssumptionLedger's `extra="allow"`.
   Typed core fields get populated later, from explicit context (S2b/A1) or
   an explicit per-source mapping -- never inferred here.

2. It does not force a parse on a formula it can't parse cleanly. A messy
   real-world formula string ("~10 saved tensors", "+ scales/metadata") is
   left unparsed and reported, never guessed at -- "fail loudly, never
   silently" applies to seeding just as much as to verification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import AssumptionLedger, NumericClaim

_MULT_SEP_RE = re.compile(r"[×xX*]")
_TRAILING_UNIT_RE = re.compile(r"\s*(bytes?|GB|MB|KB|GiB|MiB|KiB)\s*$")
_FACTOR_RE = re.compile(r"^~?\s*([\d,]*\.?\d+)\s*([BMK])?$", re.IGNORECASE)
_SCALE = {None: 1.0, "B": 1e9, "M": 1e6, "K": 1e3}


@dataclass
class FormulaParseResult:
    raw: str
    parse_ok: bool
    expression: str = ""
    variables: dict[str, float] = field(default_factory=dict)
    output_unit: str = ""
    computed_value: float | None = None
    tolerance: float = 0.01
    notes: list[str] = field(default_factory=list)


def parse_formula(formula: str) -> FormulaParseResult:
    """Parse a source's own formula caption (e.g. "7.61B × 2 bytes") into a
    deterministic multiplication chain, or report exactly why it can't.

    Only handles a clean chain of factors separated by ×/x/*, each either a
    bare number or a number with a B/M/K (billion/million/thousand) suffix,
    with an optional trailing unit word. Anything else (an addition, a "~"
    approximation, a parenthetical annotation) fails closed with a note --
    it is never partially evaluated.
    """
    raw = formula.strip()
    working = raw
    output_unit = ""

    unit_match = _TRAILING_UNIT_RE.search(working)
    if unit_match:
        output_unit = unit_match.group(1).lower().rstrip("s")
        working = working[: unit_match.start()]

    raw_factors = [f.strip() for f in _MULT_SEP_RE.split(working) if f.strip()]
    if not raw_factors:
        return FormulaParseResult(raw=raw, parse_ok=False, notes=["no factors found"])

    variables: dict[str, float] = {}
    approximate = False
    for i, factor in enumerate(raw_factors, start=1):
        match = _FACTOR_RE.match(factor)
        if not match:
            return FormulaParseResult(
                raw=raw, parse_ok=False,
                notes=[f"factor {i} ({factor!r}) is not a clean number(+B/M/K suffix)"],
            )
        digits, suffix = match.groups()
        if factor.strip().startswith("~"):
            approximate = True
        value = float(digits.replace(",", "")) * _SCALE[suffix.upper() if suffix else None]
        variables[f"f{i}"] = value

    expression = " * ".join(variables.keys())
    computed_value = 1.0
    for v in variables.values():
        computed_value *= v

    # A source author's own "~" means "treat this as approximate" -- parsed
    # normally (never silently ignored), but with a wider tolerance and a
    # visible note rather than a false claim of exactness.
    notes = ["one or more factors were marked approximate (~)"] if approximate else []
    tolerance = 0.05 if approximate else 0.01

    return FormulaParseResult(
        raw=raw, parse_ok=True, expression=expression, variables=variables,
        output_unit=output_unit, computed_value=computed_value,
        tolerance=tolerance, notes=notes,
    )


def seed_assumption_ledger(js_literals: dict[str, Any]) -> AssumptionLedger:
    """Top-level SCALAR literals only (int/float/str/bool) become extra ledger
    fields, lowercased, unchanged. Nested objects/arrays (e.g. a `modes`
    config object) are structured data for `find_formula_claims`, not
    ledger scalars, and are skipped here."""
    scalars = {
        name.lower(): value
        for name, value in js_literals.items()
        if isinstance(value, (int, float, str, bool))
    }
    return AssumptionLedger(**scalars)


def find_formula_claims(
    literals: dict[str, Any], claim_id_prefix: str = "N"
) -> tuple[list[NumericClaim], list[dict]]:
    """Recursively walk extracted JS literals for any dict carrying a
    "formula" string, and parse it into a NumericClaim wherever found --
    regardless of nesting shape, since different sources structure their
    data objects differently and no single canonical path is assumed.

    Returns (numeric_claims, unparsed) -- unparsed formulas are reported,
    never silently dropped.
    """
    numeric_claims: list[NumericClaim] = []
    unparsed: list[dict] = []
    counter = [0]

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            formula = node.get("formula")
            if isinstance(formula, str):
                result = parse_formula(formula)
                if result.parse_ok:
                    counter[0] += 1
                    display_value = _best_effort_display_value(node)
                    numeric_claims.append(
                        NumericClaim(
                            numeric_claim_id=f"{claim_id_prefix}{counter[0]:03d}",
                            expression=result.expression,
                            variables=result.variables,
                            output_unit=result.output_unit,
                            display_value=display_value or "",
                            tolerance=result.tolerance,
                        )
                    )
                else:
                    unparsed.append({"path": path, "formula": formula, "notes": result.notes})
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                visit(item, f"{path}[{i}]")

    visit(literals, "")
    return numeric_claims, unparsed


def _best_effort_display_value(node: dict) -> str:
    """A source's own displayed result for a formula, if it stated one
    (commonly "size" in this project's design system) -- used only for
    later cross-checking, never trusted as ground truth."""
    for key in ("size", "value", "display", "gb"):
        if key in node and isinstance(node[key], (str, int, float)):
            return str(node[key])
    return ""
