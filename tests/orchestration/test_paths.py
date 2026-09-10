"""Tests for the project/<playlist>/<video>/ folder layout (orchestration/paths.py)."""
from orchestration.paths import (
    RUN_SUBDIRS, existing_run_versions, final_dir, input_dir, next_run_dir,
    playlist_dir, promote_to_final, runs_dir, scaffold_run_dir, slugify, video_dir,
)


def test_slugify_basic_cases():
    assert slugify("Video 01: Attention!") == "video-01-attention"
    assert slugify("attention_series") == "attention-series"
    assert slugify("  spaced  out  ") == "spaced-out"


def test_slugify_rejects_a_name_with_nothing_slug_worthy():
    import pytest
    with pytest.raises(ValueError):
        slugify("!!!")


def test_directory_scheme_matches_the_documented_convention(tmp_path):
    assert playlist_dir(tmp_path, "attention_series") == tmp_path / "attention_series"
    assert input_dir(tmp_path, "attention_series") == tmp_path / "attention_series" / "input"
    assert video_dir(tmp_path, "attention_series", "video-01") == tmp_path / "attention_series" / "video-01"
    assert final_dir(tmp_path, "attention_series", "video-01") == (
        tmp_path / "attention_series" / "video-01" / "final"
    )
    assert runs_dir(tmp_path, "attention_series", "video-01") == (
        tmp_path / "attention_series" / "video-01" / "runs"
    )


def test_existing_run_versions_empty_when_nothing_created_yet(tmp_path):
    assert existing_run_versions(tmp_path, "series", "video-01") == []


def test_next_run_dir_starts_at_v01(tmp_path):
    run_dir = next_run_dir(tmp_path, "series", "video-01")
    assert run_dir.name == "v01"
    assert not run_dir.exists()  # caller scaffolds it, this function only resolves the path


def test_next_run_dir_increments_past_existing_versions(tmp_path):
    scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))  # creates v01
    scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))  # creates v02
    assert existing_run_versions(tmp_path, "series", "video-01") == ["v01", "v02"]
    assert next_run_dir(tmp_path, "series", "video-01").name == "v03"


def test_next_run_dir_handles_gaps_by_taking_the_max_not_the_count(tmp_path):
    """If v01 and v05 exist (e.g. v02-v04 were pruned), the next run is v06,
    never a reused number."""
    base = runs_dir(tmp_path, "series", "video-01")
    (base / "v01").mkdir(parents=True)
    (base / "v05").mkdir(parents=True)
    assert next_run_dir(tmp_path, "series", "video-01").name == "v06"


def test_scaffold_run_dir_creates_every_plan_working_subfolder(tmp_path):
    run_dir = next_run_dir(tmp_path, "series", "video-01")
    scaffold_run_dir(run_dir)
    for sub in RUN_SUBDIRS:
        assert (run_dir / sub).is_dir()
    assert (run_dir / "final").is_dir()


def test_scaffold_run_dir_is_idempotent(tmp_path):
    run_dir = next_run_dir(tmp_path, "series", "video-01")
    scaffold_run_dir(run_dir)
    scaffold_run_dir(run_dir)  # must not raise
    assert run_dir.is_dir()


def test_promote_to_final_copies_the_run_final_into_the_video_final(tmp_path):
    run_dir = scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))
    (run_dir / "final" / "video_script.html").write_text("<html>v1</html>")

    dst = promote_to_final(run_dir, tmp_path, "series", "video-01")

    assert dst == final_dir(tmp_path, "series", "video-01")
    assert (dst / "video_script.html").read_text() == "<html>v1</html>"


def test_promote_to_final_overwrites_a_previous_promotion(tmp_path):
    """A later successful run replaces the last good result -- final/ is
    always the latest PASS/PASS_WARN, never a merge of old and new files."""
    run1 = scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))
    (run1 / "final" / "video_script.html").write_text("v1")
    (run1 / "final" / "stale_only_in_v1.html").write_text("stale")
    promote_to_final(run1, tmp_path, "series", "video-01")

    run2 = scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))
    (run2 / "final" / "video_script.html").write_text("v2")
    promote_to_final(run2, tmp_path, "series", "video-01")

    final = final_dir(tmp_path, "series", "video-01")
    assert (final / "video_script.html").read_text() == "v2"
    assert not (final / "stale_only_in_v1.html").exists()


def test_a_failed_runs_own_final_never_touches_the_video_final(tmp_path):
    """promote_to_final is only ever called by the orchestrator after PASS/
    PASS_WARN (plan §14) -- a run that never gets promoted leaves the
    video-level final/ untouched, so a REVISE/FAIL attempt can't clobber
    the last good result just by existing."""
    run_dir = scaffold_run_dir(next_run_dir(tmp_path, "series", "video-01"))
    (run_dir / "final" / "video_script.html").write_text("never promoted")
    assert not final_dir(tmp_path, "series", "video-01").exists()
