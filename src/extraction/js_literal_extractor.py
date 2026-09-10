"""Extracts JS object/array literals from inline <script> blocks (plan §6.2).

Parses with Acorn via a small Node bridge (src/extraction/js_bridge/) and
extracts ONLY literal-safe declarations — nothing here ever executes
source code. This is the fix for Appendix G #1: `node:vm` is not a
security boundary, so this module never touches it.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_BRIDGE_DIR = Path(__file__).parent / "js_bridge"
_BRIDGE_SCRIPT = _BRIDGE_DIR / "extract_literals.js"


class JsBridgeError(RuntimeError):
    """The Node subprocess itself failed (missing node, missing acorn, timeout, ...)."""


@dataclass
class RejectedDeclaration:
    name: str
    kind: str  # the AST node type that made it unsafe (e.g. "CallExpression")
    reason: str


@dataclass
class LiteralExtractionResult:
    literals: dict = field(default_factory=dict)
    rejected: list[RejectedDeclaration] = field(default_factory=list)
    parse_ok: bool = True
    error: str | None = None


def extract_literals(js_source: str, timeout_s: int = 10) -> LiteralExtractionResult:
    """Run one inline <script> block's source through the Acorn bridge.

    Never raises on rejected/unsafe code within valid JS — that's the
    normal, expected outcome for behavioral scripts (e.g. reveal-on-scroll
    observers) and is reported in `.rejected`, not treated as failure.
    Raises JsBridgeError only if the Node subprocess itself can't run.
    """
    if not js_source.strip():
        return LiteralExtractionResult()

    try:
        proc = subprocess.run(
            ["node", str(_BRIDGE_SCRIPT)],
            input=js_source,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(_BRIDGE_DIR),
        )
    except FileNotFoundError as e:
        raise JsBridgeError(f"node not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise JsBridgeError(f"js_bridge timed out after {timeout_s}s: {e}") from e

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise JsBridgeError(
            f"js_bridge produced non-JSON output (exit {proc.returncode}): "
            f"{proc.stdout[:200]!r} / stderr: {proc.stderr[:200]!r}"
        ) from e

    if not payload.get("ok", False):
        # A genuine JS parse error in the source (e.g. truly malformed script).
        # Not a security concern — just nothing to extract.
        return LiteralExtractionResult(parse_ok=False, error=payload.get("error"))

    rejected = [RejectedDeclaration(**r) for r in payload.get("rejected", [])]
    return LiteralExtractionResult(literals=payload.get("literals", {}), rejected=rejected)


def extract_literals_from_scripts(script_texts: list[str], timeout_s: int = 10) -> LiteralExtractionResult:
    """Run every inline <script> block through the bridge and merge the results.

    Later blocks' literals take precedence on a name collision (matching
    normal JS scoping when scripts run in document order); rejections from
    every block are kept, not just the last one's.
    """
    merged = LiteralExtractionResult()
    for text in script_texts:
        result = extract_literals(text, timeout_s=timeout_s)
        if not result.parse_ok:
            merged.parse_ok = False
            merged.error = result.error
            continue
        merged.literals.update(result.literals)
        merged.rejected.extend(result.rejected)
    return merged
