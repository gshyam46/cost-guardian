"""Guardian worker: polls Langfuse for new LLM-call observations, runs detectors over
them, and stores resulting incidents.

Runnable standalone: `python -m guardian.worker`. `poll_once()` is also importable for
a single manual pass -- useful for verifying the pipeline without a live poll loop.
"""
import asyncio
from contextvars import ContextVar
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from config import POLL_INTERVAL_SECONDS
from db import db

from .detectors import cost_anomaly, pii, reliability_anomaly
from .detectors.base import DetectorResult
from .langfuse_client import LangfuseTraceSource
from .models import TraceMetric
from .source_io import SourceReadBusy, SourceReadTimeout, run_source_read

logger = logging.getLogger(__name__)

DETECTORS = [cost_anomaly, reliability_anomaly, pii]

BASELINE_LOOKBACK = timedelta(hours=24)
SOURCE_ROW_LIMIT = 500
CURSOR_DOC_ID = "guardian_worker_cursor"
_HEALTH_LEASE = ContextVar("guardian_health_lease", default=None)


async def _get_cursor() -> datetime:
    doc = await db.guardian_state.find_one({"_id": CURSOR_DOC_ID})
    if doc and doc.get("last_polled_at"):
        return datetime.fromisoformat(doc["last_polled_at"])
    if doc and doc.get("initial_cursor_at"):
        return datetime.fromisoformat(doc["initial_cursor_at"])
    # Preserve the first attempt's boundary across source outages. This records
    # initialization, not a successful checkpoint or completed historical import.
    initial = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.guardian_state.update_one(
        {"_id": CURSOR_DOC_ID},
        {"$set": {"initial_cursor_at": initial.isoformat()}}, upsert=True,
    )
    return initial


async def _save_cursor(when: datetime) -> None:
    await db.guardian_state.update_one(
        {"_id": CURSOR_DOC_ID},
        {"$set": {"last_polled_at": when.isoformat()}},
        upsert=True,
    )


def _run_detectors(
    baseline: List[TraceMetric], candidates: List[TraceMetric], failures=None
) -> List[DetectorResult]:
    results: List[DetectorResult] = []
    for detector_module in DETECTORS:
        try:
            results.extend(detector_module.evaluate(baseline, candidates))
        except Exception:
            # One bad detector must not take down the worker or block the others.
            logger.error("[Guardian] Detector evaluation failed")
            if failures is not None:
                failures.append(detector_module.NAME)
    return results


def _prepare_content(rows, connection_id):
    from dataclasses import asdict
    from .ledger import identity
    return {identity(row.metric, connection_id): [asdict(result) for result in pii.evaluate([], [row.metric])]
            for row in rows if row.disposition == "accepted" and row.metric is not None}


async def _read_page(source, window):
    from .ledger import aware, digest
    from .models import SourcePageResult, SourceRowDisposition
    start, end = aware(window["start"]), aware(window["end"])
    if getattr(source, "api_version", "v1") == "v2":
        return await run_source_read(source.fetch_generation_page, since=start, until=end,
            cursor=window["cursor"], expected_query_fingerprint=window["query_fingerprint"], page_size=100), None
    read = await run_source_read(source.fetch_generations, since=start, until=end, limit=SOURCE_ROW_LIMIT)
    if read.status != "complete":
        return None, read
    rows = [SourceRowDisposition(ordinal=index, disposition="accepted", metric=metric,
        record_fingerprint=metric.revision_fingerprint or "", observation_id=metric.observation_id,
        trace_id=metric.trace_id, source_project_id=metric.project_id) for index, metric in enumerate(read.metrics)]
    return SourcePageResult(rows=rows, status="ok", window_start=start, window_end=end, api_version="v1",
        query_fingerprint=digest([window["start"], window["end"], "legacy-complete"]),
        exhausted=True, records_read=len(rows), fetched_at=read.fetched_at), read


async def poll_once(source):
    """Resume durable work, ingest bounded pages, then materialize accepted rows."""
    from capture.settings import guard_source_mode, load_capture_mode
    from capture.errors import CaptureError
    if load_capture_mode() != "langfuse":
        raise CaptureError(503, "capture_mode_mismatch")
    await guard_source_mode(db, "langfuse")
    from config import GUARDIAN_CONNECTION_ID
    from .ledger import LedgerError, ObservationLedger, aware
    now = datetime.now(timezone.utc)
    ledger = ObservationLedger(db, GUARDIAN_CONNECTION_ID)
    lease = await ledger.acquire()
    if lease is None:
        logger.info("[Guardian] Another worker owns this connection")
        return 0
    health_token = _HEALTH_LEASE.set((ledger, lease))
    created = 0
    try:
        await ledger.claim_langfuse(lease)
        await ledger.ensure_indexes()
        cursor = await _get_cursor()
        await _record_health(last_attempt_at=now.isoformat(), last_finished_at=None,
            processing_status="reading", read_status="reading", read_error_code=None,
            source_fetched_at=None, pages_fetched=0, records_read=0, invalid_count=0,
            duplicate_count=0, detector_failures=0, source_row_limit=SOURCE_ROW_LIMIT,
            source_api_version=getattr(source, "api_version", "v1"),
            window_start=(now - BASELINE_LOOKBACK).isoformat(), window_end=now.isoformat())
        # Recovery is independent of upstream availability.
        await ledger.rebuild(lease)
        created, failures = await ledger.process_pending(lease, DETECTORS)
        state = await db.guardian_state.find_one({"_id": CURSOR_DOC_ID}) or {}
        if cursor < now - BASELINE_LOOKBACK and not state.get("active_window"):
            await _record_health(read_status="partial", processing_status="read_blocked",
                                 read_error_code="checkpoint_outside_window")
            return created
        window = await ledger.begin_window(lease, now - BASELINE_LOOKBACK, now, getattr(source, "api_version", "v1"))
        pages = records = invalid = duplicates = 0
        exhausted = False
        for _ in range(max(1, SOURCE_ROW_LIMIT // 100)):
            page, legacy = await _read_page(source, window)
            if legacy is not None and legacy.status != "complete":
                await _record_health(read_status=legacy.status, read_error_code=legacy.error_code,
                    processing_status="read_blocked", pages_fetched=legacy.pages_fetched,
                    records_read=legacy.records_read, invalid_count=legacy.invalid_count,
                    duplicate_count=legacy.duplicate_count)
                return created
            if page.status != "ok":
                if window["cursor"] is not None and page.error_code == "invalid_query" and window["restarts"] < 1:
                    await ledger.restart_window(lease, window)
                    window = (await db.guardian_state.find_one({"_id": CURSOR_DOC_ID}))["active_window"]
                    continue
                await _record_health(read_status="failed", read_error_code=page.error_code, processing_status="read_blocked")
                return created
            try:
                prepared = _prepare_content(page.rows, ledger.connection_id)
            except Exception:
                raise LedgerError("content_detector_preparation_failed") from None
            counts = await ledger.commit_page(lease, window, page, prepared)
            pages += legacy.pages_fetched if legacy is not None else 1
            records += page.records_read
            invalid += counts["quarantined"] + counts["conflict"]
            duplicates += counts["duplicate"]
            await _record_health(pages_fetched=pages, records_read=records, invalid_count=invalid,
                duplicate_count=duplicates, window_start=window["start"], window_end=window["end"])
            if page.exhausted:
                exhausted = True
                break
            window = (await db.guardian_state.find_one({"_id": CURSOR_DOC_ID}))["active_window"]
        await ledger.rebuild(lease)
        new, more_failures = await ledger.process_pending(lease, DETECTORS)
        created += new
        failures += more_failures
        backlog = await ledger.backlog()
        incomplete = backlog["quarantined_records"] > 0
        processing = "detector_degraded" if failures else "pending" if (not exhausted or backlog["pending_observations"] or backlog["dirty_buckets"]) else "complete"
        await _record_health(read_status="partial" if incomplete else "complete" if exhausted else "pending",
            read_error_code="quarantined_observations" if incomplete else None,
            processing_status=processing, detector_failures=failures, **backlog)
        if processing == "complete":
            await _record_health(processing_watermark=aware(window["end"]).isoformat())
        return created
    except (SourceReadBusy, SourceReadTimeout) as error:
        await _record_health(read_status="failed", processing_status="read_blocked",
            read_error_code="source_busy" if isinstance(error, SourceReadBusy) else "source_timeout")
        return created
    except LedgerError as error:
        await _record_health(processing_status="blocked", read_status="partial", read_error_code=str(error))
        logger.warning("[Guardian] Ingestion requires recovery: %s", str(error))
        return created
    except Exception:
        await _record_health(read_status="failed", processing_status="read_blocked", read_error_code="ingestion_failed")
        logger.error("[Guardian] Ingestion failed; durable work remains available for retry")
        return created
    finally:
        try:
            await _record_health(last_finished_at=datetime.now(timezone.utc).isoformat(), **(await ledger.backlog()))
            await ledger.release(lease)
        finally:
            _HEALTH_LEASE.reset(health_token)

async def _record_health(**fields):
    context = _HEALTH_LEASE.get()
    if context is None:
        await db.guardian_state.update_one({"_id": CURSOR_DOC_ID}, {"$set": fields}, upsert=True)
        return
    from .ledger import LeaseLost
    ledger, lease = context
    async def commit(session):
        await ledger._touch(lease, session)
        await db.guardian_state.update_one({"_id": CURSOR_DOC_ID}, {"$set": fields}, upsert=True, session=session)
    try:
        await ledger.transaction(commit)
    except LeaseLost:
        # A replacement worker owns both progress and monitoring now.
        return


async def run_forever() -> None:
    from capture.settings import load_capture_mode
    mode = load_capture_mode()
    source = LangfuseTraceSource() if mode == "langfuse" else None
    if source is not None and not source.available:
        logger.error(
            "[Guardian] Langfuse not configured - worker will idle every cycle. Set "
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY in backend/.env."
        )

    logger.info(
        "[Guardian] Worker started - processing %s every %ss.", mode, POLL_INTERVAL_SECONDS
    )

    try:
        while True:
            try:
                if mode == "direct":
                    from .direct_worker import poll_direct_once
                    await poll_direct_once(db)
                else:
                    await poll_once(source)
            except Exception:
                # The loop itself must survive one bad cycle.
                logger.error("[Guardian] Poll cycle failed; checkpoint was not completed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        if source is not None:
            source.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(run_forever())
