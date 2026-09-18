"""Tests for review/visual_sequence_critic.py -- C3-sequence (STORY_IMPROVEMENT_PLAN.md
Phase 15)."""
from llm.budget import BudgetCounter, DEFAULT_TIERS
from review.models import CritiqueIssue
from review.visual_sequence_critic import (
    TASK_PROMPT, VisualSequenceCritique, critique_visual_sequence, sequence_scene_payload,
)


class FakeVisualAuditor:
    def __init__(self, response: VisualSequenceCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_budget():
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def test_sequence_scene_payload_shape():
    payload = sequence_scene_payload("s1", 0, "card")
    assert payload == {"scene_id": "s1", "image_index": 0, "component_id": "card"}


def test_images_and_payload_reach_the_agent_call():
    auditor = FakeVisualAuditor(VisualSequenceCritique(issues=[]))
    payloads = [sequence_scene_payload("s1", 0, "card"), sequence_scene_payload("s2", 1, "diagram_card")]

    critique_visual_sequence(payloads, ["img1", "img2"], auditor, make_budget())

    assert auditor.calls[0]["images"] == ["img1", "img2"]
    assert auditor.calls[0]["payload"]["scenes"] == payloads


def test_returns_the_issues_from_the_critique():
    layout_repetition_issue = {
        "issue_id": "V1", "severity": "major", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1", "s2", "s3", "s4"], "problem": "four scenes in a row all use card",
        "why_it_matters": "the sequence feels static", "recommended_intent": "vary the component choice",
        "repair_owner": "html_author",
    }
    auditor = FakeVisualAuditor(VisualSequenceCritique(issues=[layout_repetition_issue]))
    payloads = [sequence_scene_payload(f"s{i}", i, "card") for i in range(4)]

    issues = critique_visual_sequence(payloads, ["img"] * 4, auditor, make_budget())

    assert len(issues) == 1
    assert isinstance(issues[0], CritiqueIssue)
    assert issues[0].scene_ids == ["s1", "s2", "s3", "s4"]


def test_no_issues_is_a_valid_clean_result():
    auditor = FakeVisualAuditor(VisualSequenceCritique(issues=[]))
    assert critique_visual_sequence([], [], auditor, make_budget()) == []


def test_uses_pass_id_c3seq_and_visual_sequence_auditor_mode():
    auditor = FakeVisualAuditor(VisualSequenceCritique(issues=[]))
    critique_visual_sequence([], [], auditor, make_budget())
    call = auditor.calls[0]
    assert call["pass_id"] == "C3seq"
    assert call["mode"] == "VISUAL_SEQUENCE_AUDITOR"


def test_prompt_instructs_judging_the_sequence_not_a_single_scene():
    assert "SEQUENCE" in TASK_PROMPT
    assert "component_id" in TASK_PROMPT
    assert "never `critical`" in TASK_PROMPT


def test_prompt_has_no_hardcoded_topic_vocabulary():
    """Overfitting guard (STORY_IMPROVEMENT_PLAN.md's own established convention): this
    prompt runs on every future video's sequence regardless of topic."""
    lowered = TASK_PROMPT.lower()
    for term in ("q/k/v", "softmax", "multi-head", "attention"):
        assert term not in lowered, f"found topic-specific term {term!r} in a generic prompt"
