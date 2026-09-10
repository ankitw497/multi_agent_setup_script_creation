"""Tests for llm/client.py::make_llm_client -- the one correct way to build a client.

Real gap found 2026-09-10: an LLMClient built by hand in an e2e script,
without a repair_fn, let a malformed paid-lane response raise immediately
instead of being repaired for free. This factory makes that impossible.
"""
from llm.client import LLMClient, make_llm_client
from llm.usage import UsageLedger


def test_make_llm_client_always_wires_a_repair_fn(tmp_path):
    client = make_llm_client("r1", UsageLedger(tmp_path / "usage.jsonl"))
    assert isinstance(client, LLMClient)
    assert client._repair_fn is not None


def test_make_llm_client_repair_fn_is_callable_and_uses_the_subscription_backend(tmp_path, monkeypatch):
    from llm.backends.claude_cli import CliCallResult

    captured = {}

    def fake_call(self, model_id, system_prompt, user_payload, timeout_s=None):
        captured["model_id"] = model_id
        return CliCallResult(content='{"ok": true}', model_resolved=model_id,
                              input_tokens=1, output_tokens=1, notional_microusd=1, latency_ms=1)

    monkeypatch.setattr("llm.backends.claude_cli.ClaudeCliBackend.call", fake_call)

    client = make_llm_client("r1", UsageLedger(tmp_path / "usage.jsonl"))
    result = client._repair_fn("broken", "error", "schema")

    assert result == '{"ok": true}'
    assert captured["model_id"] == "claude-haiku-4-5-20251001"  # repair is ALWAYS Haiku, never a paid model
