"""Round-trip tests for orchestration/state.py (plan §5, §8, STORY_IMPROVEMENT_PLAN.md
Phase 17.1)."""
import pytest

from orchestration.state import PipelineState, load_checkpoint, save_checkpoint

from tests.conftest import roundtrip_fixture


def test_pipeline_state_roundtrips_empty_run():
    state = roundtrip_fixture(PipelineState, "orchestration", "PipelineState")
    assert state.status == "running"
    assert state.revision_count == 0
    assert state.plan is None


def test_pipeline_state_dump_is_the_checkpoint():
    """state.model_dump_json() after every stage IS the checkpoint (plan §4.2,
    §17 Phase 0's 'done when') — this just confirms the round-trip that
    property depends on actually holds."""
    state = PipelineState(run_id="r1", html_path="x.html")
    dumped = state.model_dump_json()
    restored = PipelineState.model_validate_json(dumped)
    assert restored == state


def test_pipeline_state_defaults_to_empty_collections_not_none():
    state = PipelineState(run_id="r1", html_path="x.html")
    assert state.source_units == []
    assert state.claim_registry == []
    assert state.narration == []
    assert state.shorts == []


def test_phase_17_resume_fields_default_to_a_fresh_never_resumed_state():
    state = PipelineState(run_id="r1", html_path="x.html")
    assert state.completed_stages == []
    assert state.claims_spent_microusd == 0
    assert state.source_brief_spent_microusd == 0
    assert state.loop_spent_microusd == 0
    assert state.story_replans_used == 0
    assert state.major_revisions_used == 0
    assert state.story_final_status == ""


def test_save_checkpoint_then_load_checkpoint_roundtrips(tmp_path):
    """STORY_IMPROVEMENT_PLAN.md Phase 17.1: the actual save/load pair `run_pipeline.py`'s
    --resume depends on, not just the schema's own model_dump_json round-trip."""
    state = PipelineState(
        run_id="r1", html_path="x.html", source_hash="sha256:abc",
        completed_stages=["claims", "source_brief"], claims_spent_microusd=70_000,
    )

    save_checkpoint(state, tmp_path)
    restored = load_checkpoint(tmp_path)

    assert restored == state
    assert (tmp_path / "checkpoint.json").exists()


def test_load_checkpoint_raises_a_clear_error_when_none_exists(tmp_path):
    """Never silently return a fresh/empty state when asked to resume from a directory that
    was never checkpointed -- that would look like a successful resume while actually
    redoing every stage anyway, the exact failure mode this phase exists to prevent."""
    with pytest.raises(FileNotFoundError, match="checkpoint"):
        load_checkpoint(tmp_path)
