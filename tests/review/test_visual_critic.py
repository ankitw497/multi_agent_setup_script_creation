"""Tests for review/visual_critic.py -- C3 (plan §13, V1C)."""
import base64

import pytest

from llm.budget import BudgetCounter, DEFAULT_TIERS
from review.models import CritiqueIssue
from review.visual_critic import VisualCritique, critique_visuals, scene_payload


class FakeVisualAuditor:
    def __init__(self, response: VisualCritique):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_issue(**overrides) -> CritiqueIssue:
    base = dict(
        issue_id="V1", severity="major", category="visual_mismatch", layer="VISUAL",
        scene_ids=["s1"], problem="x", why_it_matters="y", recommended_intent="z",
        repair_owner="narration_lead",
    )
    base.update(overrides)
    return CritiqueIssue(**base)


def test_images_reach_the_agent_call():
    auditor = FakeVisualAuditor(VisualCritique(issues=[]))
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    payloads = [scene_payload("s1", 0, "prose", "narration")]

    critique_visuals(payloads, ["data:image/jpeg;base64,AAAA"], auditor, budget)

    assert auditor.calls[0]["images"] == ["data:image/jpeg;base64,AAAA"]


def test_scene_payload_shape_reaches_the_call():
    auditor = FakeVisualAuditor(VisualCritique(issues=[]))
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    payloads = [scene_payload("s1", 0, "the prose text", "the spoken text")]

    critique_visuals(payloads, ["data:image/jpeg;base64,AAAA"], auditor, budget)

    sent_scenes = auditor.calls[0]["payload"]["scenes"]
    assert sent_scenes == [{
        "scene_id": "s1", "image_index": 0,
        "screen_prose": "the prose text", "narration_text": "the spoken text",
    }]


def test_returns_the_issues_from_the_critique():
    issue = make_issue()
    auditor = FakeVisualAuditor(VisualCritique(issues=[issue]))
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    result = critique_visuals([scene_payload("s1", 0, "p", "n")], ["img"], auditor, budget)

    assert result == [issue]


def test_uses_pass_id_c3_and_visual_auditor_mode():
    auditor = FakeVisualAuditor(VisualCritique(issues=[]))
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    critique_visuals([scene_payload("s1", 0, "p", "n")], ["img"], auditor, budget)

    assert auditor.calls[0]["pass_id"] == "C3"
    assert auditor.calls[0]["mode"] == "VISUAL_AUDITOR"


@pytest.mark.integration
def test_live_c3_catches_a_real_visual_mismatch():
    """The one real end-to-end check for C3: a genuine Playwright screenshot
    (JPEG, per ERR-040's PNG-rejection finding) sent to a real Gemini flash
    call, with narration that deliberately does NOT match what's on screen
    -- confirms the whole real path (screenshot -> JPEG -> multimodal call
    -> structured CritiqueIssue) works together, not just each piece alone."""
    from playwright.sync_api import sync_playwright

    from agents.review_lead import make_review_lead
    from llm.client import make_llm_client
    from llm.usage import UsageLedger

    html = """\
    <!doctype html><html><body style="margin:0;">
    <div id="s1" style="width:400px;height:300px;background:#c0392b;
        display:flex;align-items:center;justify-content:center;
        font-family:sans-serif;font-size:28px;color:white;">
        A solid red rectangle
    </div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 400, "height": 300})
        page.set_content(html)
        screenshot_bytes = page.screenshot(type="jpeg", quality=80)
        browser.close()

    image_b64 = base64.b64encode(screenshot_bytes).decode()
    image_uri = f"data:image/jpeg;base64,{image_b64}"

    usage_ledger = UsageLedger(path="/tmp/claude-501-scratch-c3-live-usage.jsonl")
    client = make_llm_client(run_id="test_live_c3", ledger=usage_ledger)
    visual_auditor = make_review_lead(client, tier="flash")
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])

    payloads = [scene_payload(
        "s1", 0,
        screen_prose="A detailed line chart comparing quarterly revenue across five product lines.",
        narration_text="Here we see a complex financial chart with many data series.",
    )]

    issues = critique_visuals(payloads, [image_uri], visual_auditor, budget)

    print(f"\n[live C3] {len(issues)} issue(s): {[(i.category, i.severity) for i in issues]}")
    assert len(issues) >= 1  # a solid red rectangle is nothing like "a detailed line chart"
    assert issues[0].scene_ids == ["s1"]
