"""Unit tests for orchestration/cache.py — plan §4.2, Appendix G #6-7 (central cache-key policy)."""
from orchestration.cache import CacheKeyInputs, DiskCache, cache_key, content_hash


def make_inputs(**overrides):
    base = dict(
        input_hashes=("abc123",),
        prompt_version="1.0",
        schema_version="1.0",
        model_resolved="gpt-4o-mini",
    )
    base.update(overrides)
    return CacheKeyInputs(**base)


def test_same_inputs_produce_the_same_key():
    assert cache_key(make_inputs()) == cache_key(make_inputs())


def test_input_hash_order_does_not_affect_the_key():
    """input_hashes is sorted internally, so hash composition order never matters."""
    k1 = cache_key(make_inputs(input_hashes=("a", "b")))
    k2 = cache_key(make_inputs(input_hashes=("b", "a")))
    assert k1 == k2


def test_a_changed_prompt_version_changes_the_key():
    k1 = cache_key(make_inputs(prompt_version="1.0"))
    k2 = cache_key(make_inputs(prompt_version="1.1"))
    assert k1 != k2


def test_a_changed_model_id_changes_the_key():
    """A moved alias must not silently hit a stale cache entry."""
    k1 = cache_key(make_inputs(model_resolved="gpt-4o-mini"))
    k2 = cache_key(make_inputs(model_resolved="gpt-4o-mini-2024-07-18"))
    assert k1 != k2


def test_evidence_snapshot_changes_the_key():
    """The C2a fix from the final hygiene review: a changed model card must invalidate
    verification even when the claim registry hash is identical (plan §4.2)."""
    k1 = cache_key(make_inputs(evidence_snapshot="modelcard-v1"))
    k2 = cache_key(make_inputs(evidence_snapshot="modelcard-v2"))
    assert k1 != k2


def test_content_hash_is_deterministic_and_sensitive_to_content():
    assert content_hash("hello") == content_hash("hello")
    assert content_hash("hello") != content_hash("hello!")


def test_content_hash_accepts_str_or_bytes_consistently():
    assert content_hash("hello") == content_hash(b"hello")


def test_disk_cache_round_trip(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    key = cache_key(make_inputs())

    assert cache.get(key) is None
    assert not cache.has(key)

    cache.set(key, {"result": "cached value"})

    assert cache.has(key)
    assert cache.get(key) == {"result": "cached value"}


def test_disk_cache_keys_are_isolated_by_directory(tmp_path):
    cache1 = DiskCache(tmp_path / "a")
    cache2 = DiskCache(tmp_path / "b")
    key = cache_key(make_inputs())
    cache1.set(key, {"v": 1})
    assert cache2.get(key) is None
