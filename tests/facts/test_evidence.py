"""Tests for facts/evidence.py -- the Evidence Broker (plan §6.5)."""
from facts.evidence import fulfil_evidence_requests
from facts.models import EvidenceRequest


def test_matches_a_request_to_a_relevant_local_reference(tmp_path):
    (tmp_path / "qwen2.5-7b-config.md").write_text(
        "Qwen2.5-7B architecture: hidden size 3584, 28 transformer layers, "
        "28 attention heads with 4 KV heads (grouped-query attention)."
    )
    request = EvidenceRequest(
        claim_id="C001",
        what_would_settle_it="the exact number of attention heads in Qwen2.5-7B",
        suggested_sources=["official model config"],
    )
    fulfilled = fulfil_evidence_requests([request], tmp_path)
    assert "C001" in fulfilled
    assert fulfilled["C001"].kind == "EXTERNAL_REFERENCE"
    assert "qwen2.5-7b-config.md" in fulfilled["C001"].ref


def test_no_references_directory_means_nothing_fulfilled(tmp_path):
    missing = tmp_path / "does_not_exist"
    request = EvidenceRequest(claim_id="C001", what_would_settle_it="x")
    assert fulfil_evidence_requests([request], missing) == {}


def test_empty_references_directory_means_nothing_fulfilled(tmp_path):
    request = EvidenceRequest(claim_id="C001", what_would_settle_it="x")
    assert fulfil_evidence_requests([request], tmp_path) == {}


def test_a_request_with_no_topical_overlap_is_left_unfulfilled(tmp_path):
    """An unfulfilled request must never be force-matched to an unrelated
    file -- the claim correctly stays UNVERIFIED (plan §6.5)."""
    (tmp_path / "unrelated-topic.md").write_text("This document is about gardening and soil pH.")
    request = EvidenceRequest(claim_id="C001", what_would_settle_it="the GPU memory bandwidth of an A100")
    assert fulfil_evidence_requests([request], tmp_path) == {}


def test_picks_the_best_matching_file_among_several():
    pass  # covered implicitly by score comparison logic; see the dedicated test below


def test_picks_the_higher_scoring_of_two_candidate_files(tmp_path):
    (tmp_path / "loosely-related.md").write_text("attention mechanisms in general.")
    (tmp_path / "exact-match.md").write_text(
        "Qwen2.5-7B head dimension is 128, computed as hidden size 3584 divided by 28 heads."
    )
    request = EvidenceRequest(
        claim_id="C001",
        what_would_settle_it="Qwen2.5-7B head dimension hidden size 128 divided 28 heads",
    )
    fulfilled = fulfil_evidence_requests([request], tmp_path)
    assert fulfilled["C001"].ref == "exact-match.md"


def test_hidden_files_are_ignored(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    request = EvidenceRequest(claim_id="C001", what_would_settle_it="anything")
    assert fulfil_evidence_requests([request], tmp_path) == {}


def test_dotfile_only_returns_nothing_but_does_not_crash(tmp_path):
    (tmp_path / ".hidden").write_text("hidden content")
    request = EvidenceRequest(claim_id="C001", what_would_settle_it="anything at all here")
    assert fulfil_evidence_requests([request], tmp_path) == {}
