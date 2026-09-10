"""Unit tests for llm/backends/litellm_backend.py — plan §3.2 (public cost interface only).

These are mocked and free. The live smoke test that actually verified OpenAI
and Gemini keys against real endpoints is test_live_openai_smoke /
test_live_gemini_smoke below, marked `integration` so it never runs by
accident and never costs money in a normal test run.
"""
import os
from types import SimpleNamespace

import pytest

from llm.backends.litellm_backend import LiteLLMBackend


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeResponse:
    def __init__(self, content, model, prompt_tokens, completion_tokens):
        self.choices = [FakeChoice(content)]
        self.model = model
        self.usage = FakeUsage(prompt_tokens, completion_tokens)


def test_call_reads_public_cost_interface_not_hidden_params(monkeypatch):
    """The final hygiene review's fix: cost must come from litellm.completion_cost(),
    never from response._hidden_params (plan §3.2, Appendix G #7)."""
    fake_response = FakeResponse("OK", "gpt-4o-mini-2024-07-18", 12, 1)

    def fake_completion(**kwargs):
        return fake_response

    def fake_completion_cost(completion_response):
        assert completion_response is fake_response
        return 0.0000024

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", fake_completion_cost)

    backend = LiteLLMBackend()
    result = backend.call("gpt-4o-mini", "system", "user")

    assert result.content == "OK"
    assert result.model_resolved == "gpt-4o-mini-2024-07-18"
    assert result.input_tokens == 12
    assert result.output_tokens == 1
    assert result.billed_microusd == 2  # 0.0000024 usd -> rounds to 2 microusd


def test_call_degrades_to_zero_cost_when_completion_cost_raises(monkeypatch):
    """A model with no pricing entry in LiteLLM must not crash the call — the pre-flight
    estimate is the real backstop, not this figure."""
    fake_response = FakeResponse("OK", "some-new-model", 5, 1)
    monkeypatch.setattr("litellm.completion", lambda **kw: fake_response)

    def raising_cost(completion_response):
        raise Exception("no pricing entry")

    monkeypatch.setattr("litellm.completion_cost", raising_cost)

    backend = LiteLLMBackend()
    result = backend.call("some-new-model", "system", "user")
    assert result.billed_microusd == 0


@pytest.mark.integration
def test_live_openai_smoke():
    """Real API call, minimal tokens. Costs a fraction of a cent. Run with: pytest -m integration"""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY not set"

    backend = LiteLLMBackend(max_tokens=5)
    result = backend.call("gpt-4o-mini", "You are terse.", "Reply with exactly: OK")
    assert "OK" in result.content
    assert result.input_tokens > 0
    print(f"\n[live openai] tokens in={result.input_tokens} out={result.output_tokens} "
          f"cost=${result.billed_microusd / 1_000_000:.6f}")


@pytest.mark.integration
def test_live_gemini_smoke():
    """Real API call. As of 2026-09-10 this fails with 403 API_KEY_SERVICE_BLOCKED —
    the Generative Language API is disabled/restricted for this key's GCP project.
    Not a code issue. Fix at aistudio.google.com/apikey, then re-run this test."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY not set"

    backend = LiteLLMBackend(max_tokens=5)
    result = backend.call("gemini/gemini-1.5-flash", "You are terse.", "Reply with exactly: OK")
    assert "OK" in result.content
    print(f"\n[live gemini] tokens in={result.input_tokens} out={result.output_tokens} "
          f"cost=${result.billed_microusd / 1_000_000:.6f}")
