"""Subscription lane: `claude -p` subprocess, sonnet | haiku (plan §3.1).

Measured: default flags cost ~30,167 tokens of Claude Code's own harness
overhead per call; the stripped-flag recipe below costs ~170. That ~99%
cut is what makes this lane usable at volume.

Hard requirement: ANTHROPIC_API_KEY must never reach this subprocess, so
this lane can never silently fall back to metered API billing. It is
asserted in code (`_build_env`), not left to shell hygiene — see the
key-leak test in tests/llm/test_claude_cli_backend.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

import tenacity

from ..usage import usd_to_microusd

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def strip_fences(text: str) -> str:
    """The CLI sometimes wraps JSON in ``` fences and sometimes doesn't; handle both."""
    return _FENCE_RE.sub("", text).strip()


class ModelMismatch(RuntimeError):
    """The CLI resolved a different model than the one requested.

    Benchmark runs must refuse to start on an unpinned/moved alias
    (plan §3.1, Appendix E #8) — this is that refusal.
    """


class ClaudeCliInvocationError(RuntimeError):
    """The `claude -p` subprocess itself failed (non-zero exit, bad JSON, ...)."""


@dataclass
class CliCallResult:
    content: str
    model_resolved: str
    input_tokens: int
    output_tokens: int
    notional_microusd: int  # what it WOULD have cost — never billed
    latency_ms: int


class ClaudeCliBackend:
    """lane = subscription. Zero marginal API cost; the constraint is the quota window."""

    lane = "subscription"

    def __init__(
        self, cwd: str | None = None, timeout_s: int = 300,
        max_attempts: int = 3, retry_wait_min_s: float = 1.0, retry_wait_max_s: float = 10.0,
    ):
        # 300s default: a real 11-unit/~3300-word batched extraction call was
        # observed to exceed the previous 120s default (2026-09-10) -- larger
        # batched payloads over a complex schema legitimately take longer.
        # This is subscription quota, not billed API time, so a generous
        # default costs wall-clock, not money.
        self.cwd = cwd
        self.timeout_s = timeout_s
        # max_attempts/retry_wait_* (2026-09-11): a real full pipeline run
        # crashed on a transient `claude -p` exit-1 with empty stderr -- an
        # immediate manual retry of the exact same call succeeded. Exposed
        # as constructor params (not just hardcoded in call()) so tests can
        # shrink the backoff to keep the default fast suite fast.
        self.max_attempts = max_attempts
        self.retry_wait_min_s = retry_wait_min_s
        self.retry_wait_max_s = retry_wait_max_s

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def _build_command(self, model_id: str, system_prompt: str, user_payload: str) -> list[str]:
        return [
            "claude", "-p", user_payload,
            "--model", model_id,
            "--system-prompt", system_prompt,
            "--tools",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections",
            "--max-turns", "1",
            "--output-format", "json",
        ]

    def call(
        self, model_id: str, system_prompt: str, user_payload: str, timeout_s: int | None = None,
    ) -> CliCallResult:
        """Retries a transient `claude -p` subprocess failure (a real, live
        finding, 2026-09-11: a full pipeline run crashed on `exit 1` with
        empty stderr -- an immediate manual retry of the exact same call
        succeeded, confirming it was transient, not a real bug). Only
        `ClaudeCliInvocationError` (non-zero exit, non-JSON stdout) is
        retried -- `ModelMismatch` is a real, deterministic bug (the CLI
        resolved a different model than requested) that retrying can never
        fix, so it is never caught here."""
        retrying = tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self.max_attempts),
            retry=tenacity.retry_if_exception_type(ClaudeCliInvocationError),
            wait=tenacity.wait_exponential(multiplier=1, min=self.retry_wait_min_s, max=self.retry_wait_max_s),
            reraise=True,
        )
        return retrying(self._call_once, model_id, system_prompt, user_payload, timeout_s)

    def _call_once(
        self, model_id: str, system_prompt: str, user_payload: str, timeout_s: int | None,
    ) -> CliCallResult:
        env = self._build_env()
        assert "ANTHROPIC_API_KEY" not in env, "ANTHROPIC_API_KEY leaked into the subscription lane"

        cmd = self._build_command(model_id, system_prompt, user_payload)
        effective_timeout = timeout_s if timeout_s is not None else self.timeout_s

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, env=env, cwd=self.cwd, capture_output=True, text=True, timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as e:
            # Real bug found live 2026-09-12: a legitimately large B2
            # rewrite payload (a full beat's scenes/claims) took longer
            # than the default 300s timeout on a real run -- this used to
            # propagate straight past `call()`'s retry classification
            # below (which only recognizes ClaudeCliInvocationError),
            # killing the entire pipeline run on one slow-but-transient
            # call instead of retrying it, exactly the class of failure
            # this method's own docstring says it exists to handle.
            raise ClaudeCliInvocationError(
                f"claude -p timed out after {effective_timeout}s"
            ) from e
        latency_ms = int((time.monotonic() - start) * 1000)

        if proc.returncode != 0:
            raise ClaudeCliInvocationError(
                f"claude -p failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}"
            )

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ClaudeCliInvocationError(f"claude -p returned non-JSON stdout: {e}") from e

        return self._parse_envelope(envelope, model_id, latency_ms)

    def _parse_envelope(self, envelope: dict, model_id: str, latency_ms: int) -> CliCallResult:
        result_text = strip_fences(envelope.get("result", ""))

        model_usage = envelope.get("modelUsage") or {}
        top_usage = envelope.get("usage", {}) or {}
        resolved_model = self._identify_resolved_model(
            model_usage, top_usage.get("input_tokens"), top_usage.get("output_tokens"), model_id
        )

        if resolved_model != model_id:
            raise ModelMismatch(
                f"requested model {model_id!r} but the CLI resolved {resolved_model!r} — "
                "refusing to proceed on an unpinned/moved alias (plan Appendix E #8)"
            )

        usage_block = model_usage.get(resolved_model, {})
        input_tokens = usage_block.get("inputTokens", top_usage.get("input_tokens", 0))
        output_tokens = usage_block.get("outputTokens", top_usage.get("output_tokens", 0))
        # Use the envelope's total_cost_usd, not just this model's costUSD: a single
        # `claude -p` call can involve an internal sub-call to a different model
        # (observed 2026-09-10: a `--model sonnet` request also logs a small
        # claude-haiku-4-5-20251001 entry in modelUsage — apparently harness-internal,
        # not something the caller asked for). total_cost_usd is what the call
        # actually consumed end to end, which is what "notional cost" should mean.
        notional_usd = envelope.get("total_cost_usd", usage_block.get("costUSD", 0.0))

        return CliCallResult(
            content=result_text,
            model_resolved=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            notional_microusd=usd_to_microusd(notional_usd),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _identify_resolved_model(
        model_usage: dict, top_input_tokens, top_output_tokens, requested: str
    ) -> str:
        """Pick the modelUsage entry that actually produced `result`.

        Dict-key order is NOT reliable: a single envelope can list more than one
        model (observed case above), and the harness-internal one can be listed
        first. The entry whose token counts match the envelope's top-level
        `usage` block is the one that generated the final response.
        """
        if not model_usage:
            return requested
        if len(model_usage) == 1:
            return next(iter(model_usage))
        for name, block in model_usage.items():
            if (
                block.get("inputTokens") == top_input_tokens
                and block.get("outputTokens") == top_output_tokens
            ):
                return name
        # No exact match (e.g. rounding/streaming edge case) — prefer the
        # requested id if it's present at all, rather than silently guessing.
        return requested if requested in model_usage else next(iter(model_usage))
