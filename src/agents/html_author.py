"""HTML Author (Sonnet, subscription lane) -- visual-first screen content (plan §2).

STORY_IMPROVEMENT_PLAN.md Phase 14: this identity was always part of the original design
(`agents/__init__.py`'s own docstring has listed it alongside story_lead/narration_lead/
review_lead/worker since before any agent was implemented) but was never actually built --
H and H-repair (`html_synth/synthesizer.py`, `editing/html_repair.py`) ran under
`narration_lead` instead, whose own `BASE_SYSTEM_PROMPT` says "you turn a validated story
plan into natural spoken narration... write for listening" -- directly contradicted by H's
own task prompt, which says the opposite: "NOT spoken narration". `RepairOwner` (`review/
models.py`) and every C3/H-repair routing decision already used the string "html_author" as
this identity's name; only the real `Agent` object was missing until now.
"""
from __future__ import annotations

from config.loader import resolve_model
from llm.client import LLMClient

from .base import Agent

BASE_SYSTEM_PROMPT = (
    "You convert a validated technical story and narration into visual-first "
    "screen content for a YouTube explainer. You do not write spoken "
    "narration. Your job is to communicate each scene visually: large "
    "teaching objects, minimal text, clear hierarchy, accurate numbers, and "
    "render-safe components. Prefer diagrams, transformations, comparisons "
    "and annotated objects over paragraphs whenever the idea can be shown "
    "rather than read."
)


def make_html_author(client: LLMClient) -> Agent:
    # 2026-09-24: used to discard reasoning_effort/max_tokens (`_, _`) -- config's own
    # sonnet alias carrying a real reasoning_effort (the CLI's `--effort` flag) would have
    # silently never reached this agent's calls. Now threaded through like every other
    # config-driven default (see llm/backends/claude_cli.py for the `--effort` mapping).
    model_resolved, reasoning_effort, max_tokens = resolve_model("subscription_lane", "sonnet")
    return Agent(
        name="html_author", lane="subscription", client=client,
        model_alias="sonnet", model_resolved=model_resolved,
        base_system_prompt=BASE_SYSTEM_PROMPT,
        default_reasoning_effort=reasoning_effort,
        default_max_tokens=max_tokens,
    )
