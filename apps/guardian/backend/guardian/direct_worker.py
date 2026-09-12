"""Bounded numeric-inbox processing; capture receipt is separate from completion."""
import logging
from datetime import datetime, timezone

from .detectors import cost_anomaly, reliability_anomaly
from .ledger import LEDGER_VERSION, SAFE_FIELDS, LedgerError, LeaseLost, ObservationLedger, restore_metric

logger = logging.getLogger(__name__)
MAX_EVENTS_PER_POLL = 500
COMMIT_BATCH_SIZE = 100
PROCESSING_ID = "direct_processing"
HEALTH_ID = "guardian_worker_cursor"
SOURCE_API = "direct-v1"
DETECTORS = [cost_anomaly, reliability_anomaly]


def _now():
    return datetime.now(timezone.utc)


async def _guard(database, settings, session=None, *, touch=False):
    from capture.settings import ensure_direct_binding, guard_source_mode
    await guard_source_mode(database, "direct", session=session)
    return await ensure_direct_binding(database, settings, session=session, touch=touch)


async def _health(ledger, lease, **fields):
    async def commit(session):
        await ledger._touch(lease, session)
        await ledger.db.guardian_state.update_one(
            {"_id": HEALTH_ID}, {"$set": fields}, upsert=True, session=session)
    try:
        await ledger.transaction(commit)
    except LeaseLost:
        # A successor alone owns the heartbeat after lease expiry.
        pass


async def _begin(ledger, lease, settings):
    async def commit(session):
        await ledger._touch(lease, session)
        await _guard(ledger.db, settings, session, touch=True)
        await ledger._migration_guard(session)
        config = await ledger.db.guardian_state.find_one({"_id": "ledger_configuration"}, session=session)
        from capture.settings import NORMALIZATION_VERSION
        contract = {"source_api_version": SOURCE_API, "normalization_version": NORMALIZATION_VERSION}
        if any(config.get(key, value) != value for key, value in contract.items()):
            raise LedgerError("source_mode_reconciliation_required")
        await ledger.db.guardian_state.update_one({"_id": "ledger_configuration"}, {"$set": contract}, session=session)
        previous = await ledger.db.guardian_state.find_one({"_id": PROCESSING_ID}, session=session) or {}
        if previous.get("cutoff_sequence") is not None:
            return previous["cutoff_sequence"]
        capture = await ledger.db.guardian_state.find_one({"_id": "direct_capture"}, session=session) or {}
        cutoff = capture.get("last_sequence", 0)
        if type(cutoff) is not int or cutoff < 0:
            raise LedgerError("invalid_capture_sequence")
        await ledger.db.guardian_state.update_one({"_id": PROCESSING_ID},
            {"$set": {"cutoff_sequence": cutoff, "started_at": _now()}}, upsert=True, session=session)
        return cutoff
    return await ledger.transaction(commit)


async def _consume(ledger, lease, settings, cutoff, limit):
    async def commit(session):
        await ledger._touch(lease, session)
        binding = await _guard(ledger.db, settings, session, touch=True)
        state = await ledger.db.guardian_state.find_one({"_id": PROCESSING_ID}, session=session)
        if not state or state.get("cutoff_sequence") != cutoff:
            raise LedgerError("stale_capture_batch")
        query = {"binding_id": binding["binding_id"], "connection_id": ledger.connection_id,
                 "processed": False, "sequence": {"$lte": cutoff}}
        rows = await ledger.db.guardian_capture_inbox.find(query, session=session).sort("sequence", 1).limit(limit).to_list(limit)
        counts = {"accepted": 0, "duplicate": 0, "conflict": 0}
        for row in rows:
            if not isinstance(row.get("metric"), dict) or set(row["metric"]) - set(SAFE_FIELDS):
                raise LedgerError("invalid_capture_record")
            metric = restore_metric(row)
            if (metric.source != "guardian_direct" or metric.project_id != settings.project_id
                    or metric.environment != settings.environment or metric.output_text is not None):
                raise LedgerError("invalid_capture_scope")
            disposition = await ledger._accept(metric, [], session)
            counts[disposition] += 1
            result = await ledger.db.guardian_capture_inbox.update_one(
                {"_id": row["_id"], "processed": False},
                {"$set": {"processed": True, "processed_at": _now(), "disposition": disposition}}, session=session)
            if result.matched_count != 1:
                raise LedgerError("stale_capture_batch")
        if rows:
            await ledger.db.guardian_state.update_one({"_id": PROCESSING_ID},
                {"$set": {"last_processed_at": _now()}, "$inc": {"processed_events": len(rows)}}, session=session)
        remaining = await ledger.db.guardian_capture_inbox.find_one(query, {"_id": 1}, session=session)
        if remaining is None:
            await ledger.db.guardian_state.update_one({"_id": PROCESSING_ID},
                {"$set": {"cutoff_sequence": None, "last_completed_sequence": cutoff,
                          "last_completed_at": _now()}}, session=session)
        return len(rows), remaining is None, counts
    return await ledger.transaction(commit)


async def poll_direct_once(database, settings=None):
    """Drain one fixed receipt prefix, then materialize and evaluate its ledger rows.

    Later earlier-timestamp events do not re-evaluate completed decisions. There
    is no source timestamp watermark: sequence exhaustion means captured receipt
    completion only, not that the customer's application exported every call.
    """
    if settings is None:
        from identity.settings import load_settings
        settings = load_settings()
    # Scope/mode verification precedes data recovery or lease acquisition.
    await _guard(database, settings)
    ledger = ObservationLedger(database, settings.connection_id)
    lease = await ledger.acquire()
    if lease is None:
        return 0
    created = 0
    try:
        await ledger.ensure_indexes()
        await database.guardian_capture_inbox.create_index([("connection_id", 1), ("processed", 1), ("sequence", 1)])
        await _health(ledger, lease, last_attempt_at=_now().isoformat(), last_finished_at=None,
            source_api_version=SOURCE_API, ledger_version=LEDGER_VERSION, processing_status="reading",
            read_status="reading", read_error_code=None, records_read=0, duplicate_count=0,
            invalid_count=0, detector_failures=0, source_row_limit=MAX_EVENTS_PER_POLL)
        cutoff = await _begin(ledger, lease, settings)
        await ledger.rebuild(lease)
        consumed = duplicates = conflicts = 0
        exhausted = False
        while consumed < MAX_EVENTS_PER_POLL:
            count, exhausted, outcomes = await _consume(ledger, lease, settings, cutoff,
                min(COMMIT_BATCH_SIZE, MAX_EVENTS_PER_POLL - consumed))
            consumed += count
            duplicates += outcomes["duplicate"]
            conflicts += outcomes["conflict"]
            if exhausted:
                break
        await ledger.rebuild(lease)
        failures = 0
        if exhausted:
            created, failures = await ledger.process_pending(lease, DETECTORS)
        backlog = await ledger.backlog()
        pending = await database.guardian_capture_inbox.count_documents({"connection_id": settings.connection_id, "processed": False})
        unfinished = not exhausted or pending or backlog["pending_observations"] or backlog["dirty_buckets"]
        status = "detector_degraded" if failures else "pending" if unfinished else "complete"
        await _health(ledger, lease, records_read=consumed, duplicate_count=duplicates, invalid_count=conflicts,
            detector_failures=failures, pending_events=pending, processing_status=status,
            read_status="partial" if backlog["quarantined_records"] else "pending" if pending else "complete",
            read_error_code="quarantined_observations" if backlog["quarantined_records"] else None, **backlog)
        return created
    except LedgerError as error:
        await _health(ledger, lease, processing_status="blocked", read_status="partial", read_error_code=str(error))
        logger.warning("[Guardian] Direct processing requires recovery")
        return created
    except Exception:
        await _health(ledger, lease, processing_status="read_blocked", read_status="failed", read_error_code="capture_processing_failed")
        logger.warning("[Guardian] Direct processing failed; captured events remain available for retry")
        return created
    finally:
        try:
            await _health(ledger, lease, last_finished_at=_now().isoformat())
        finally:
            await ledger.release(lease)
