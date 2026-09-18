"""Concurrent batch dispatch for I/O-bound LLM calls (2026-09-15).

STORY_IMPROVEMENT_PLAN.md Phase 10's own note ("this codebase has no existing
concurrent-LLM-call infrastructure to build on safely... can revisit if a live
run shows batching alone isn't enough") is the reason this didn't exist until
now. It does now, because a live run did show exactly that: CM/C2b's batch
loops run sequentially, and a real run's wall-clock time is dominated by
waiting on one blocking network call after another when nothing about those
calls actually depends on each other.

A blocking HTTP call (the paid_api/LiteLLM lane) or a blocking subprocess wait
(the subscription/Claude-CLI lane) releases the GIL while waiting on I/O, so a
plain `ThreadPoolExecutor` genuinely parallelizes wall-clock time here -- this
is not CPU-bound work, so threads (not processes) are the right tool, and one
already-slow call no longer blocks every other independent batch behind it.
This does NOT reduce total $ cost (each batch is billed the same regardless of
when it runs) -- only wall-clock time, matching the plan's own framing.

Safe to share a single BudgetCounter/UsageLedger across the callables passed
here: both now hold their own internal lock (llm/budget.py, llm/usage.py)
around the small read-modify-write bookkeeping section, while the actual slow
I/O runs unlocked and fully concurrent.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")

# Bounds how many batches hit the paid API at once -- generous enough that a
# typical run's handful of C2B_BATCH_SIZE/CM_BATCH_SIZE-sized batches all run
# at once, conservative enough not to look like a burst to the provider's own
# rate limiting.
DEFAULT_MAX_WORKERS = 4


def run_concurrently(fns: list[Callable[[], T]], max_workers: int = DEFAULT_MAX_WORKERS) -> list[T]:
    """Runs each zero-arg callable in its own thread; returns results in the same
    order as `fns` (not completion order), so callers can zip them back up
    positionally without tracking which future belongs to which input.

    A single `fns` entry (the common case -- most narrations fit in one batch)
    skips the thread pool entirely and just calls it inline, so there's no
    executor-startup overhead when there was never anything to parallelize.
    """
    if len(fns) <= 1:
        return [fn() for fn in fns]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(fns))) as pool:
        futures = [pool.submit(fn) for fn in fns]
        return [f.result() for f in futures]
