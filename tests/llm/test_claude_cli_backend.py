"""Unit tests for llm/backends/claude_cli.py — plan §3.1.

The key-leak test is the most important one in this file: it asserts
ANTHROPIC_API_KEY can never reach the subprocess, even when it's set in the
parent environment. Everything here is mocked (no real `claude` binary
invoked, zero subscription quota spent); the live end-to-end check is
test_live_haiku_smoke, marked integration.
"""
import json
import subprocess

import pytest

from llm.backends.claude_cli import (
    ClaudeCliBackend,
    ClaudeCliInvocationError,
    ModelMismatch,
    strip_fences,
)


def make_envelope(model="haiku", result="{}", input_tokens=170, output_tokens=10, cost=0.001):
    return {
        "result": result,
        "modelUsage": {
            model: {"inputTokens": input_tokens, "outputTokens": output_tokens, "costUSD": cost}
        },
    }


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_strip_fences_handles_fenced_and_bare_json():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_anthropic_api_key_is_never_passed_to_the_subprocess(monkeypatch):
    """The key-leak test. Even with ANTHROPIC_API_KEY set in the parent shell,
    the subscription lane must run without it (plan §3.1)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-reach-the-subprocess")

    captured = {}

    def fake_run(cmd, env, cwd, capture_output, text, timeout):
        captured["env"] = env
        return FakeCompletedProcess(stdout=json.dumps(make_envelope()))

    monkeypatch.setattr("subprocess.run", fake_run)

    backend = ClaudeCliBackend()
    backend.call("haiku", "system", "payload")

    assert "ANTHROPIC_API_KEY" not in captured["env"], "ANTHROPIC_API_KEY leaked into the subprocess env"


def test_stripped_flags_are_present_in_the_command():
    backend = ClaudeCliBackend()
    cmd = backend._build_command("haiku", "sys", "payload")
    for flag in ("--tools", "--setting-sources", "--strict-mcp-config",
                 "--exclude-dynamic-system-prompt-sections", "--max-turns", "--output-format"):
        assert flag in cmd


def test_call_parses_envelope_and_returns_notional_cost(monkeypatch):
    envelope = make_envelope(model="haiku", result='{"ok": true}', input_tokens=170,
                              output_tokens=53, cost=0.0180378)

    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: FakeCompletedProcess(stdout=json.dumps(envelope))
    )

    backend = ClaudeCliBackend()
    result = backend.call("haiku", "system", "payload")

    assert result.content == '{"ok": true}'
    assert result.model_resolved == "haiku"
    assert result.input_tokens == 170
    assert result.output_tokens == 53
    assert result.notional_microusd == 18038  # 0.0180378 usd -> microdollars, rounded


def test_call_strips_fences_from_result():
    from llm.backends.claude_cli import ClaudeCliBackend

    backend = ClaudeCliBackend()
    envelope = make_envelope(result='```json\n{"ok": true}\n```')
    parsed = backend._parse_envelope(envelope, "haiku", latency_ms=1)
    assert parsed.content == '{"ok": true}'


def test_identifies_resolved_model_from_multi_model_envelope(monkeypatch):
    """Regression test for a real bug found 2026-09-10: a single `-p --model sonnet`
    call can log MORE THAN ONE entry in modelUsage — observed: claude-sonnet-5
    (182 in / 9 out) plus an internal claude-haiku-4-5-20251001 entry (525 in /
    12 out). Taking the first dict key picked Haiku by accident. The correct
    signal is matching token counts against the envelope's top-level `usage`
    block, which belongs to whichever model actually produced `result`."""
    envelope = {
        "result": '{"ok": true}',
        "usage": {"input_tokens": 182, "output_tokens": 9},
        "total_cost_usd": 0.001266,
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 525, "outputTokens": 12, "costUSD": 0.000585,
            },
            "claude-sonnet-5": {
                "inputTokens": 182, "outputTokens": 9, "costUSD": 0.000681,
            },
        },
    }
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: FakeCompletedProcess(stdout=json.dumps(envelope))
    )

    backend = ClaudeCliBackend()
    result = backend.call("claude-sonnet-5", "system", "payload")

    assert result.model_resolved == "claude-sonnet-5"
    assert result.input_tokens == 182
    assert result.output_tokens == 9
    # notional cost is the envelope's total (both sub-calls), not just this model's slice
    assert result.notional_microusd == 1266


def test_dict_key_order_alone_would_have_picked_the_wrong_model():
    """Documents exactly what went wrong: iterating modelUsage naively gives Haiku
    first even though Sonnet produced the answer."""
    model_usage = {
        "claude-haiku-4-5-20251001": {"inputTokens": 525, "outputTokens": 12},
        "claude-sonnet-5": {"inputTokens": 182, "outputTokens": 9},
    }
    assert next(iter(model_usage)) == "claude-haiku-4-5-20251001"  # the wrong answer
    resolved = ClaudeCliBackend._identify_resolved_model(model_usage, 182, 9, "claude-sonnet-5")
    assert resolved == "claude-sonnet-5"  # the fix


def test_resolved_model_mismatch_raises(monkeypatch):
    """Appendix E #8: refuse to proceed if the CLI resolved a different model than requested."""
    envelope = make_envelope(model="claude-haiku-4-5-20251001")  # not the literal "haiku" alias

    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: FakeCompletedProcess(stdout=json.dumps(envelope))
    )

    backend = ClaudeCliBackend()
    with pytest.raises(ModelMismatch):
        backend.call("haiku", "system", "payload")


def test_nonzero_exit_raises_invocation_error(monkeypatch):
    """max_attempts=1: this always-fails fixture would otherwise be retried
    3x by default, which is correct in production but pointless (and slow)
    for a test whose only point is confirming the failure surfaces."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: FakeCompletedProcess(returncode=1, stderr="boom"),
    )
    backend = ClaudeCliBackend(max_attempts=1)
    with pytest.raises(ClaudeCliInvocationError, match="boom"):
        backend.call("haiku", "system", "payload")


def test_non_json_stdout_raises_invocation_error(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeCompletedProcess(stdout="not json"))
    backend = ClaudeCliBackend(max_attempts=1)
    with pytest.raises(ClaudeCliInvocationError, match="non-JSON"):
        backend.call("haiku", "system", "payload")


def test_a_transient_failure_is_retried_and_can_still_succeed(monkeypatch):
    """Real gap found live 2026-09-11: a full pipeline run crashed on one
    `claude -p` exit-1 with empty stderr; an immediate manual retry of the
    identical call succeeded, confirming it was transient. This backend
    had no retry logic at all. wait_min/max are shrunk to keep this test
    fast -- the retry COUNT and eventual success is what's being proven,
    not real backoff timing."""
    calls = {"n": 0}

    envelope = make_envelope(model="claude-haiku-4-5-20251001", result="OK")

    def flaky_run(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            return FakeCompletedProcess(returncode=1, stderr="transient hiccup")
        return FakeCompletedProcess(stdout=json.dumps(envelope))

    monkeypatch.setattr("subprocess.run", flaky_run)
    backend = ClaudeCliBackend(max_attempts=3, retry_wait_min_s=0.01, retry_wait_max_s=0.01)

    result = backend.call("claude-haiku-4-5-20251001", "system", "payload")

    assert result.content == "OK"
    assert calls["n"] == 2


def test_a_timeout_is_retried_and_can_still_succeed(monkeypatch):
    """Real gap found live 2026-09-12: a legitimately large B2 rewrite
    payload took longer than the default timeout on a real run.
    subprocess.run() raising TimeoutExpired used to propagate straight
    past this backend's retry classification (which only recognized
    ClaudeCliInvocationError), killing the whole pipeline run on one
    slow-but-transient call instead of retrying it -- the exact class of
    failure this backend's retry logic exists to handle."""
    calls = {"n": 0}
    envelope = make_envelope(model="claude-haiku-4-5-20251001", result="OK")

    def flaky_run(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=300)
        return FakeCompletedProcess(stdout=json.dumps(envelope))

    monkeypatch.setattr("subprocess.run", flaky_run)
    backend = ClaudeCliBackend(max_attempts=3, retry_wait_min_s=0.01, retry_wait_max_s=0.01)

    result = backend.call("claude-haiku-4-5-20251001", "system", "payload")

    assert result.content == "OK"
    assert calls["n"] == 2


def test_a_timeout_that_never_recovers_raises_invocation_error(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="claude", timeout=300)),
    )
    backend = ClaudeCliBackend(max_attempts=1)
    with pytest.raises(ClaudeCliInvocationError, match="timed out"):
        backend.call("haiku", "system", "payload")


def test_a_deterministic_model_mismatch_is_never_retried(monkeypatch):
    """ModelMismatch is a real, deterministic bug (the CLI resolved a
    different model than requested) -- retrying can never fix it, so it
    must surface on the very first attempt, not be masked by 3 identical
    failures first."""
    calls = {"n": 0}
    envelope = make_envelope(model="claude-haiku-4-5-20251001")  # not the literal "haiku" alias

    def always_wrong_model(*a, **kw):
        calls["n"] += 1
        return FakeCompletedProcess(stdout=json.dumps(envelope))

    monkeypatch.setattr("subprocess.run", always_wrong_model)
    backend = ClaudeCliBackend(max_attempts=3, retry_wait_min_s=0.01, retry_wait_max_s=0.01)

    with pytest.raises(ModelMismatch):
        backend.call("haiku", "system", "payload")
    assert calls["n"] == 1


@pytest.mark.integration
def test_live_haiku_smoke():
    """Real `claude -p` call, using the EXACT pinned id from config/models.yaml —
    not the shorthand "haiku" (see models.yaml for why that distinction matters:
    a shorthand alias can surface an unrelated internal model in the envelope).
    Costs subscription quota, not API dollars."""
    backend = ClaudeCliBackend()
    model_id = "claude-haiku-4-5-20251001"
    result = backend.call(model_id, "You output only JSON.", 'Reply with exactly: {"ok": true}')
    assert '"ok"' in result.content
    assert result.model_resolved == model_id
    print(f"\n[live haiku] tokens in={result.input_tokens} out={result.output_tokens} "
          f"notional=${result.notional_microusd / 1_000_000:.6f} latency={result.latency_ms}ms")


@pytest.mark.integration
def test_live_sonnet_smoke():
    """Real `claude -p --model claude-sonnet-5` call. Verifies the multi-model-envelope
    fix end to end: this exact call is what originally surfaced the bug where the
    harness's internal Haiku sub-entry got picked instead of Sonnet."""
    backend = ClaudeCliBackend()
    model_id = "claude-sonnet-5"
    result = backend.call(model_id, "You output only JSON.", 'Reply with exactly: {"ok": true}')
    assert '"ok"' in result.content
    assert result.model_resolved == model_id
    print(f"\n[live sonnet] tokens in={result.input_tokens} out={result.output_tokens} "
          f"notional=${result.notional_microusd / 1_000_000:.6f} latency={result.latency_ms}ms")
