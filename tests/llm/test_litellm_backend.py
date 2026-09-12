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


def test_default_max_tokens_is_4096_not_2048(monkeypatch):
    """Real bug found 2026-09-10: a full multi-scene StoryPlan (A2) was
    truncated mid-string at the old 2048-token default -- even the Haiku
    repair path can't recover a response cut off mid-JSON-string."""
    fake_response = FakeResponse("OK", "gpt-4o", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gpt-4o", "sys", "user")

    assert captured["max_tokens"] == 4096


def test_num_retries_defaults_to_3_and_is_forwarded_to_litellm(monkeypatch):
    """ERR-032, 2026-09-11: a real ~45-minute, ~$0.71 run died on a single
    transient Gemini 503 ("high demand, try again later") at the very last
    call before completion -- litellm.completion() does not retry unless
    told to. Whether litellm actually retries a given exception class is
    litellm's own already-tested behavior, not ours to re-verify here;
    this only locks in that we ask for it."""
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gemini/gemini-3.6-flash", "sys", "user")

    assert captured["num_retries"] == 3


def test_num_retries_is_configurable(monkeypatch):
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend(num_retries=5)
    backend.call("gemini/gemini-3.6-flash", "sys", "user")

    assert captured["num_retries"] == 5


def test_timeout_defaults_to_300s_and_is_forwarded_to_litellm(monkeypatch):
    """Real bug found live 2026-09-12: litellm.completion() had NO timeout
    at all -- num_retries above only backs off an already-RAISED exception,
    but a connection that simply never responds raises nothing, so it can
    hang forever. A real gpt-5.6-sol comparison run did exactly that (6+
    hours, no progress, no error) before being killed by hand."""
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gemini/gemini-3.6-flash", "sys", "user")

    assert captured["timeout"] == 300.0


def test_timeout_is_configurable_at_the_backend_level(monkeypatch):
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend(timeout_s=60.0)
    backend.call("gemini/gemini-3.6-flash", "sys", "user")

    assert captured["timeout"] == 60.0


def test_timeout_is_overridable_per_call(monkeypatch):
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend(timeout_s=300.0)
    backend.call("gemini/gemini-3.6-flash", "sys", "user", timeout_s=45.0)

    assert captured["timeout"] == 45.0


def test_max_tokens_override_is_forwarded_when_given(monkeypatch):
    fake_response = FakeResponse("OK", "gpt-4o", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gpt-4o", "sys", "user", max_tokens=8000)

    assert captured["max_tokens"] == 8000


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


def test_no_images_sends_a_plain_string_user_message(monkeypatch):
    """V1C: every existing caller (nothing sends images yet) must get the
    exact same request shape as before this feature existed -- a bare
    string, not a content-block list."""
    fake_response = FakeResponse("OK", "gpt-4o", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call("gpt-4o", "sys", "user")

    assert captured["messages"][1]["content"] == "user"


def test_images_become_an_openai_style_multimodal_content_block_list(monkeypatch):
    """V1C: C3's screenshots must reach litellm as content blocks (text +
    one image_url block per image) -- LiteLLM normalizes this shape for
    Gemini itself, no provider-specific branching needed here."""
    fake_response = FakeResponse("OK", "gemini-3.6-flash", 6, 1)
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake_response

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.completion_cost", lambda completion_response: 0.0)

    backend = LiteLLMBackend()
    backend.call(
        "gemini/gemini-3.6-flash", "sys", "user",
        images=["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"],
    )

    content = captured["messages"][1]["content"]
    assert content == [
        {"type": "text", "text": "user"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
    ]


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


# A real 100x100 solid-blue JPEG. A PNG was tried first (both a degenerate
# 1x1 pixel and a real PIL-generated 64x64 solid color) and Gemini/Vertex
# rejected both outright ("Unable to process input image") while this exact
# JPEG succeeded -- a real, live-confirmed finding, not assumed: C3's real
# screenshots must be captured/sent as JPEG (Playwright supports this
# directly), never PNG, until the PNG rejection is understood further.
_TINY_JPEG_DATA_URI = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQE"
    "BQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsN"
    "FBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCABkAGQDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQID"
    "AAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpT"
    "VFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOU"
    "lZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oA"
    "DAMBAAIRAxEAPwDwSiiiv6zP5kCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooo"
    "oAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAK"
    "KKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK"
    "ACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP/2Q=="
)


@pytest.mark.integration
def test_live_gemini_multimodal_smoke():
    """V1C prerequisite: confirms Gemini flash actually accepts our exact
    image_url content-block format before anything (C3, Playwright
    screenshots) is built on top of it -- the smallest possible real
    increment, one call, one tiny image."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=".env")
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY not set"

    backend = LiteLLMBackend(max_tokens=20)
    result = backend.call(
        "gemini/gemini-3.6-flash", "You are terse.",
        "What color is this image? Reply with one word.",
        reasoning_effort="none", images=[_TINY_JPEG_DATA_URI],
    )
    assert result.content.strip() != ""
    print(f"\n[live gemini multimodal] content={result.content!r} "
          f"cost=${result.billed_microusd / 1_000_000:.6f}")
