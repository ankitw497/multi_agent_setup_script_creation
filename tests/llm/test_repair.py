"""Tests for llm/repair.py -- the Haiku-backed repair_fn (plan §3.4)."""
from llm.backends.claude_cli import CliCallResult
from llm.repair import make_haiku_repair_fn


class FakeBackend:
    def __init__(self, response_content: str):
        self._response_content = response_content
        self.calls = []

    def call(self, model_id, system_prompt, user_payload, timeout_s=None):
        self.calls.append({"model_id": model_id, "system_prompt": system_prompt,
                            "user_payload": user_payload, "timeout_s": timeout_s})
        return CliCallResult(content=self._response_content, model_resolved=model_id,
                              input_tokens=10, output_tokens=5, notional_microusd=100, latency_ms=1)


def test_repair_fn_calls_haiku_with_broken_output_error_and_schema():
    backend = FakeBackend('{"fixed": true}')
    repair_fn = make_haiku_repair_fn(backend)

    result = repair_fn("{broken", "Expecting property name", '{"type": "object"}')

    assert result == '{"fixed": true}'
    call = backend.calls[0]
    assert call["model_id"] == "claude-haiku-4-5-20251001"
    assert "{broken" in call["user_payload"]
    assert "Expecting property name" in call["user_payload"]
    assert '"type": "object"' in call["user_payload"]


def test_repair_fn_uses_a_bounded_timeout():
    backend = FakeBackend("{}")
    repair_fn = make_haiku_repair_fn(backend)
    repair_fn("x", "y", "z")
    assert backend.calls[0]["timeout_s"] == 120


def test_repair_fn_accepts_a_custom_model_id():
    backend = FakeBackend("{}")
    repair_fn = make_haiku_repair_fn(backend, model_id="some-other-haiku-id")
    repair_fn("x", "y", "z")
    assert backend.calls[0]["model_id"] == "some-other-haiku-id"
