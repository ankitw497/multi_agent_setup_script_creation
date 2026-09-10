"""Round-trip tests for narration/models.py (plan §5, §5.1, §11.4)."""
from narration.models import EditMap, EditMapEntry, SceneNarration, SentenceNarration

from tests.conftest import roundtrip, roundtrip_fixture


def test_sentence_narration_grounding_defaults_to_false_until_cm_sets_it():
    """grounding_required defaults False and is set by the Claim Mapper, never
    the writer — sentence_type is metadata only (plan §5.1)."""
    s = SentenceNarration(text="That's the strange part.", sentence_type="transition")
    assert s.grounding_required is False
    assert s.grounding_refs == []


def test_sentence_narration_can_carry_writer_metadata_independent_of_grounding():
    s = roundtrip(
        SentenceNarration,
        {"text": "x", "sentence_type": "analogy", "claim_refs": [], "grounding_required": True,
         "grounding_refs": ["C017"]},
    )
    # Even labelled "analogy" by the writer, CM can still mark it grounding_required —
    # the label and the grounding boundary are independent fields on purpose.
    assert s.sentence_type == "analogy"
    assert s.grounding_required is True


def test_scene_narration_roundtrips_mixed_sentence_types():
    scene = roundtrip_fixture(SceneNarration, "narration", "SceneNarration")
    assert len(scene.sentences) == 3
    grounded = [s for s in scene.sentences if s.grounding_required]
    assert len(grounded) == 2
    ungrounded = [s for s in scene.sentences if not s.grounding_required]
    assert ungrounded[0].sentence_type == "transition"


def test_edit_map_entry_roundtrips():
    roundtrip(EditMapEntry, {"scene_id": "s1", "before": "a", "after": "b", "change_type": "rhythm"})


def test_edit_map_roundtrips_and_is_what_the_diff_guard_checks(): 
    edit_map = roundtrip_fixture(EditMap, "narration", "EditMap")
    assert edit_map.revision_cycle == 1
    assert edit_map.entries[0].change_type == "restored_causal_reasoning"
