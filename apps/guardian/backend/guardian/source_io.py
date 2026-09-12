"""Bound synchronous source work without blocking the API/worker event loop.

Timing out an await cannot kill a Python thread. The permit belongs to the real
job until it finishes, so repeated client timeouts cannot grow an unbounded queue.
SDK calls must also set their own transport timeouts and bounded retries.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading


MAX_SOURCE_READS = 4
SOURCE_READ_TIMEOUT_SECONDS = 20.0
_pool = ThreadPoolExecutor(max_workers=MAX_SOURCE_READS, thread_name_prefix="guardian-source")
_slots = threading.BoundedSemaphore(MAX_SOURCE_READS)


class SourceReadBusy(Exception):
    """All actual source jobs are still running; no new job was queued."""


class SourceReadTimeout(Exception):
    """The caller's deadline expired; an SDK job may still be finishing."""


async def run_source_read(function, *args, timeout=SOURCE_READ_TIMEOUT_SECONDS, **kwargs):
    if not _slots.acquire(blocking=False):
        raise SourceReadBusy("source_busy")

    def work():
        try:
            return function(*args, **kwargs)
        finally:
            _slots.release()

    try:
        job = _pool.submit(work)
    except BaseException:
        _slots.release()
        raise

    future = asyncio.wrap_future(job)
    # A caller may disappear before a background exception is delivered. Consume
    # it without logging the source exception (which could contain credentials).
    future.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        raise SourceReadTimeout("source_timeout") from None
