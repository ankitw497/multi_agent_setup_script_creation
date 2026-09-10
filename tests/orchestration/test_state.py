"""Round-trip tests for orchestration/state.py (plan §5, §8)."""
from orchestration.state import PipelineState

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
