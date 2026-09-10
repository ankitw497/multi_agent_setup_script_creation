"""Project folder layout (user convention, 2026-09-10):

    project/<playlist>/input/<source>.html      -- rough sources you add
    project/<playlist>/<video_slug>/final/       -- stable deliverables
    project/<playlist>/<video_slug>/runs/vNN/    -- full working history per attempt

This replaces the plan's generic `runs/<id>/` root (plan §16) with a
project/playlist/video hierarchy: `runs/vNN/` under a video's own folder
holds exactly the same internal structure plan §16 describes
(extraction/, facts/, planning/, drafts/, reviews/, revisions/, html/,
usage.jsonl, run_manifest.json) -- only the root changed, not the shape.
`final/` always holds the latest successful run's deliverables, promoted
by `promote_to_final()` once the orchestrator (not yet built) has a
policy-gate result to act on.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

RUN_SUBDIRS = ("extraction", "facts", "planning", "drafts", "reviews", "revisions", "html")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """'Video 01: Attention!' -> 'video-01-attention'. Deterministic, filesystem-safe."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"name produces an empty slug: {name!r}")
    return slug


def playlist_dir(project_root: Path, playlist: str) -> Path:
    return Path(project_root) / playlist


def input_dir(project_root: Path, playlist: str) -> Path:
    return playlist_dir(project_root, playlist) / "input"


def video_dir(project_root: Path, playlist: str, video_slug: str) -> Path:
    return playlist_dir(project_root, playlist) / video_slug


def final_dir(project_root: Path, playlist: str, video_slug: str) -> Path:
    return video_dir(project_root, playlist, video_slug) / "final"


def runs_dir(project_root: Path, playlist: str, video_slug: str) -> Path:
    return video_dir(project_root, playlist, video_slug) / "runs"


def existing_run_versions(project_root: Path, playlist: str, video_slug: str) -> list[str]:
    """Sorted ["v01", "v02", ...] already present, empty if none yet."""
    base = runs_dir(project_root, playlist, video_slug)
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and re.fullmatch(r"v\d+", p.name))


def next_run_dir(project_root: Path, playlist: str, video_slug: str) -> Path:
    """The next vNN run directory, NOT yet created on disk (caller scaffolds it)."""
    existing = existing_run_versions(project_root, playlist, video_slug)
    next_n = (max(int(v[1:]) for v in existing) + 1) if existing else 1
    return runs_dir(project_root, playlist, video_slug) / f"v{next_n:02d}"


def scaffold_run_dir(run_dir: Path) -> Path:
    """Creates run_dir and every plan-§16 working subfolder inside it. Idempotent."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for sub in RUN_SUBDIRS:
        (run_dir / sub).mkdir(exist_ok=True)
    (run_dir / "final").mkdir(exist_ok=True)  # this run's own candidate final/, before promotion
    return run_dir


def promote_to_final(run_dir: Path, project_root: Path, playlist: str, video_slug: str) -> Path:
    """Copies run_dir/final/* to project/<playlist>/<video_slug>/final/, overwriting it.

    Called by the orchestrator once a run reaches PASS or PASS_WARN (plan
    §14) -- not before. A REVISE/FAIL run's work stays visible under its
    own runs/vNN/final/ but never overwrites the last good result.
    """
    src = Path(run_dir) / "final"
    dst = final_dir(project_root, playlist, video_slug)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst
