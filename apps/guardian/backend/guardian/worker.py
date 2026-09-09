"""Guardian worker: polls Langfuse for new LLM-call observations, runs detectors over
them, and stores resulting incidents.

Runnable standalone: `python -m guardian.worker`. `poll_once()` is also importable for
a single manual pass -- useful for verifying the pipeline without a live poll loop.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from config import POLL_INTERVAL_SECONDS
from db import db

from .detectors import cost_anomaly, pii, reliability_anomaly
from .detectors.base import DetectorResult
from .incident_engine import process_detector_results
from .langfuse_client import LangfuseTraceSource
from .metrics import MongoMetricsStore
from .models import TraceMetric
from .store import MongoIncidentStore

logger = logging.getLogger(__name__)

DETECTORS = [cost_anomaly, reliability_anomaly, pii]

BASELINE_LOOKBACK = timedelta(hours=24)
CURSOR_DOC_ID = "guardian_worker_cursor"


async def _get_cursor() -> datetime:
    doc = await db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
    if doc and doc.get("last_polled_at"):
        return datetime.fromisoformat(doc["last_polled_at"])
    # First run: only look back a few minutes, not the full baseline window, so we
    # don't immediately flag the whole history as "new".
    return datetime.now(timezone.utc) - timedelta(minutes=5)


async def _save_cursor(when: datetime) -> None:
    await db.guardian_state.update_one(
        {"_id": CURSOR_DOC_ID},
        {"$set": {"last_polled_at": when.isoformat()}},
        upsert=True,
    )


def _run_detectors(
    baseline: List[TraceMetric], candidates: List[TraceMetric]
) -> List[DetectorResult]:
    results: List[DetectorResult] = []
    for detector_module in DETECTORS:
        try:
            results.extend(detector_module.evaluate(baseline, candidates))
        except Exception as e:
            # One bad detector must not take down the worker or block the others.
            logger.error(f"[Guardian] Detector {detector_module.NAME} raised: {e}")
    return results


async def poll_once(source: LangfuseTraceSource) -> int:
    """Run one poll cycle. Returns the number of new incidents created."""
    cursor = await _get_cursor()
    now = datetime.now(timezone.utc)

    window = source.fetch_recent_generations(since=now - BASELINE_LOOKBACK, limit=500)
    candidates = [m for m in window if m.timestamp >= cursor]
    baseline = [m for m in window if m.timestamp < cursor]

    if not candidates:
        # Say so explicitly. A worker that only logs when it finds something makes
        # "nothing is happening in your system" and "the worker died" look identical
        # in the log -- the same distinction the dashboard's live indicator exists to
        # protect, and it matters more here because nobody is watching this process.
        logger.info(
            f"[Guardian] Poll cycle: no new generations since {cursor.isoformat()} "
            f"({len(window)} in the {int(BASELINE_LOOKBACK.total_seconds() // 3600)}h "
            f"baseline window)."
        )
        await _save_cursor(now)
        return 0

    # Trend rollups first: even a poll cycle that finds no anomalies should still move
    # the dashboard's cost/latency lines forward.
    await MongoMetricsStore(db).record(candidates)

    results = _run_detectors(baseline, candidates)
    store = MongoIncidentStore(db)
    created = await process_detector_results(results, store)

    await _save_cursor(now)
    logger.info(
        f"[Guardian] Poll cycle: {len(candidates)} new generation(s) checked, "
        f"{len(created)} incident(s) created."
    )
    return len(created)


async def run_forever() -> None:
    source = LangfuseTraceSource()
    if not source.available:
        logger.error(
            "[Guardian] Langfuse not configured - worker will idle every cycle. Set "
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY in backend/.env."
        )

    logger.info(
        f"[Guardian] Worker started - polling Langfuse every {POLL_INTERVAL_SECONDS}s."
    )

    while True:
        try:
            await poll_once(source)
        except Exception as e:
            # The loop itself must survive one bad cycle.
            logger.error(f"[Guardian] Poll cycle failed: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(run_forever())
