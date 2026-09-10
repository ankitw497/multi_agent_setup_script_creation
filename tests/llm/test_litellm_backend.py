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


class FakeCompletionTokensDetails:
    def __init__(self, reasoning_tokens=None):
        self.reasoning_tokens = reasoning_tokens


class FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens, reasoning_tokens=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.completion_tokens_details = FakeCompletionTokensDetails(reasoning_tokens)


class FakeResponse:
    def __init__(self, content, model, prompt_tokens, completion_tokens, reasoning_tokens=None):
        self.choices = [FakeChoice(content)]
        self.model = model
        self.usage = FakeUsage(prompt_tokens, completion_tokens, reasoning_tokens)


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


def test_reasoning_effort_is_forwarded_to_litellm_when_given(monkeypatch):
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gemini/gemini-3.6-flash", "sys", "user", reasoning_effort="none")

    assert captured.get("reasoning_effort") == "none"


def test_reasoning_effort_is_omitted_by_default(monkeypatch):
    """Strong-tier calls leave reasoning on by not passing the param at all —
    litellm/the provider then uses its own default, not an explicit override."""
    fake_response = FakeResponse("OK", "gemini-3.1-pro-preview", 6, 93, reasoning_tokens=92)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gemini/gemini-3.1-pro-preview", "sys", "user")

    assert "reasoning_effort" not in captured


def test_call_result_reports_reasoning_tokens_separately_from_output_tokens(monkeypatch):
    """Regression test for the real finding (2026-09-10): a cheap-tier call with no
    reasoning_effort override can spend nearly its whole output budget on hidden
    reasoning tokens instead of visible text. This must be visible in CallResult,
    not silently folded into output_tokens."""
    fake_response = FakeResponse("", "gemini-3.6-flash", 6, 96, reasoning_tokens=95)
    monkeypatch.setattr("litellm.completion", lambda **kw: fake_response)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0003645)

    backend = LiteLLMBackend()
    result = backend.call("gemini/gemini-3.6-flash", "sys", "user")

    assert result.output_tokens == 96
    assert result.reasoning_tokens == 95
    assert result.content == ""  # the real, costly failure mode this documents


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
    """Real API call, using the exact ids pinned in config/models.yaml after two
    real findings on 2026-09-10: (1) gemini-1.5-flash/pro are fully retired --
    Google's 404 responses named the exact replacements; (2) the replacement
    flash model reasons by default and needs reasoning_effort="none" or a cheap
    call becomes an expensive empty one. See models.yaml for the full story."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY not set"

    backend = LiteLLMBackend(max_tokens=10)
    result = backend.call(
        "gemini/gemini-3.6-flash", "You are terse.", "Reply with exactly: OK",
        reasoning_effort="none",
    )
    assert "OK" in result.content
    assert result.reasoning_tokens == 0
    print(f"\n[live gemini flash] tokens in={result.input_tokens} out={result.output_tokens} "
          f"reasoning={result.reasoning_tokens} cost=${result.billed_microusd / 1_000_000:.6f}")


@pytest.mark.integration
def test_live_gemini_strong_smoke():
    """Real API call against the strong tier, reasoning left on (that's the point
    of this tier) -- confirms gemini-3.1-pro-preview still resolves."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY not set"

    backend = LiteLLMBackend(max_tokens=100)
    result = backend.call(
        "gemini/gemini-3.1-pro-preview", "You are terse.", "Reply with exactly: OK"
    )
    assert "OK" in result.content
    print(f"\n[live gemini strong] tokens in={result.input_tokens} out={result.output_tokens} "
          f"reasoning={result.reasoning_tokens} cost=${result.billed_microusd / 1_000_000:.6f}")
