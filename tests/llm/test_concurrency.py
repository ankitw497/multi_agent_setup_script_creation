"""Tests for llm/concurrency.py -- run_concurrently (2026-09-15).

Real concurrency, not mocked -- these use actual threads (sleeping briefly to
simulate an I/O-bound LLM call) to prove batches genuinely overlap in
wall-clock time and results still come back in input order regardless of
completion order.
"""
import threading
import time

import pytest

from llm.budget import BudgetCounter, BudgetExceeded, DEFAULT_TIERS
from llm.concurrency import run_concurrently
from llm.usage import UsageLedger, UsageRecord


def test_results_come_back_in_input_order_not_completion_order():
    def slow(n, delay):
        time.sleep(delay)
        return n

    # deliberately reversed delays: the LAST callable finishes FIRST
    results = run_concurrently([
        lambda: slow(1, 0.15),
        lambda: slow(2, 0.05),
        lambda: slow(3, 0.0),
    ])
    assert results == [1, 2, 3]


def test_batches_genuinely_overlap_in_wall_clock_time():
    """3 callables each sleeping 0.2s must finish well under 0.6s (sequential)
    -- proves this is real concurrency, not just a list comprehension."""
    start = time.monotonic()
    run_concurrently([lambda: time.sleep(0.2) for _ in range(3)], max_workers=3)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5


def test_a_single_callable_never_touches_the_thread_pool():
    """The common case (a narration small enough for one batch) must not pay
    thread-pool overhead or behave any differently from a plain call."""
    calls = []

    def only_one():
        calls.append(threading.current_thread())
        return "result"

    result = run_concurrently([only_one])
    assert result == ["result"]
    assert calls == [threading.main_thread()]


def test_an_exception_in_one_callable_propagates():
    def boom():
        raise ValueError("simulated failure")

    with pytest.raises(ValueError, match="simulated failure"):
        run_concurrently([lambda: 1, boom, lambda: 3])


def test_empty_list_returns_empty_list():
    assert run_concurrently([]) == []


def test_budget_counter_survives_concurrent_record_spend_without_losing_updates():
    """Without BudgetCounter's own lock (llm/budget.py), concurrent
    `spent_microusd += x` from multiple threads can race and silently lose an
    update -- this is the exact failure mode that would let real spend exceed
    hard_cap undetected once CM/C2b batches run concurrently."""
    budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    n_threads = 20
    per_call_microusd = 1000  # $0.001 each

    def spend():
        budget.record_spend(per_call_microusd)

    run_concurrently([spend for _ in range(n_threads)], max_workers=n_threads)
    assert budget.spent_microusd == n_threads * per_call_microusd


def test_budget_counter_still_raises_past_hard_cap_under_concurrency():
    tier = DEFAULT_TIERS["short"]  # hard_cap = 0.25
    budget = BudgetCounter(tier=tier)
    per_call_microusd = 30_000  # $0.03 each -- 10 calls = $0.30, over the $0.25 cap

    def spend():
        budget.record_spend(per_call_microusd)

    with pytest.raises(BudgetExceeded):
        run_concurrently([spend for _ in range(10)], max_workers=10)


def test_usage_ledger_append_survives_concurrent_writers_without_corrupting_lines(tmp_path):
    ledger = UsageLedger(path=tmp_path / "usage.jsonl")

    def write(i):
        ledger.append(UsageRecord(
            run_id="r", agent="worker", pass_id="S2b", mode="X", lane="subscription",
            model_alias="haiku", model_resolved="claude-haiku-4-5-20251001", notional_microusd=i,
        ))

    run_concurrently([lambda i=i: write(i) for i in range(30)], max_workers=10)
    records = ledger.read_all()
    assert len(records) == 30  # every line parsed cleanly -- none interleaved/corrupted
    assert sorted(r.notional_microusd for r in records) == list(range(30))
