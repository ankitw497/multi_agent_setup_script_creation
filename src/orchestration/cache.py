"""Central cache-key policy for every model stage (plan §4.2, Appendix G #7).

An LLM stage is not a pure function — its answer depends on the prompt
version, the exact model id, and (for verification) an evidence snapshot,
not only its declared inputs. So the cache key is built the same way,
everywhere, from one function, rather than each stage inventing its own
notion of "what matters."

    key = hash(input_hashes, prompt_version, schema_version, model_resolved,
               config_fingerprint, evidence_snapshot, temperature/seed)

`detected_archetype` (or any stage's own output) must never be one of the
inputs — a stage's cache key is built before it runs, from what it consumes,
never from what it produces (plan §4.1 caching table).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


@dataclass(frozen=True)
class CacheKeyInputs:
    input_hashes: tuple[str, ...]
    prompt_version: str
    schema_version: str
    model_resolved: str
    config_fingerprint: str = ""
    evidence_snapshot: str = ""
    temperature_or_seed: str = ""


def cache_key(inputs: CacheKeyInputs) -> str:
    """One deterministic sha256 hex digest from every input that shapes the model's answer."""
    payload = _stable_json(
        {
            "input_hashes": sorted(inputs.input_hashes),
            "prompt_version": inputs.prompt_version,
            "schema_version": inputs.schema_version,
            "model_resolved": inputs.model_resolved,
            "config_fingerprint": inputs.config_fingerprint,
            "evidence_snapshot": inputs.evidence_snapshot,
            "temperature_or_seed": inputs.temperature_or_seed,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_hash(text_or_bytes: str | bytes) -> str:
    """The hash used for `input_hashes` entries — e.g. a source HTML's content hash (plan §6.3)."""
    data = text_or_bytes.encode("utf-8") if isinstance(text_or_bytes, str) else text_or_bytes
    return hashlib.sha256(data).hexdigest()


class DiskCache:
    """Minimal content-addressed cache: one JSON file per key, under a cache directory.

    Stage-specific cache policies (e.g. C2a's key per plan §6.5, which adds the
    assumption ledger and evidence snapshot) build their CacheKeyInputs and
    call this store — the store itself doesn't know what a "claim registry" is.
    """

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def set(self, key: str, value: dict) -> None:
        self._path(key).write_text(_stable_json(value))

    def has(self, key: str) -> bool:
        return self._path(key).exists()
