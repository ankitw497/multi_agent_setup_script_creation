"""Tests for reporting/emit_short.py -- R* for shorts (plan §16, §17)."""
import json

from narration.models import SceneNarration, SentenceNarration
from orchestration.shorts_pipeline import ShortRunResult
from planning.shorts_models import HookEvent, ShortPlan
from reporting.emit_short import emit_short_deliverables


def make_result() -> ShortRunResult:
    plan = ShortPlan(title="t", central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0))
    narration = [SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="Hi.", sentence_type="transition")])]
    return ShortRunResult(plan=plan, narration=narration, hard_failures=[], issues=[], diagnostics=[], final_status="PASS")


def test_writes_both_files(tmp_path):
    short_dir = emit_short_deliverables(make_result(), tmp_path / "shorts" / "1")
    assert (short_dir / "short_plan.json").exists()
    assert (short_dir / "narration.json").exists()


def test_narration_json_round_trips(tmp_path):
    short_dir = emit_short_deliverables(make_result(), tmp_path / "shorts" / "1")
    data = json.loads((short_dir / "narration.json").read_text())
    assert data[0]["scene_id"] == "hook"
    assert data[0]["sentences"][0]["text"] == "Hi."


def test_short_plan_json_round_trips(tmp_path):
    short_dir = emit_short_deliverables(make_result(), tmp_path / "shorts" / "1")
    data = json.loads((short_dir / "short_plan.json").read_text())
    assert data["title"] == "t"
    assert data["micro_arc"] == "problem_fix"
