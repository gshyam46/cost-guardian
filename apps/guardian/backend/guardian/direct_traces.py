"""Read bounded, content-free direct-capture evidence from the durable ledger."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .ledger import SAFE_FIELDS, ObservationLedger, restore_metric
from .traces import LiveReadError, _metric_to_call, _run_from, _runs_from, _stats_from

MAX_RECORDS = 1000
READ_TIMEOUT_SECONDS = 5
SOURCE_FIELDS = {"source_kind": "guardian_direct", "source_api": "direct-v1",
                 "source_api_version": "direct-v1", "metadata_basis": "captured_events"}


class DirectTraceReader:
    """Capture coverage describes retained receipts, never total application activity."""

    def __init__(self, db, settings):
        self._db = db
        self._settings = settings
        self._ledger = ObservationLedger(db, settings.connection_id)
        self._indexed = False

    @property
    def available(self):
        return True

    async def _read(self, hours, trace_id=None):
        from capture.settings import ensure_direct_binding, guard_source_mode
        await guard_source_mode(self._db, "direct")
        await ensure_direct_binding(self._db, self._settings)
        if not self._indexed:
            await self._db.guardian_observations.create_index([
                ("connection_id", 1), ("metric.source", 1), ("metric.project_id", 1), ("metric.timestamp", -1)], maxTimeMS=2000)
            await self._db.guardian_observations.create_index([
                ("connection_id", 1), ("metric.source", 1), ("metric.project_id", 1), ("metric.trace_id", 1), ("metric.timestamp", -1)], maxTimeMS=2000)
            self._indexed = True
        until = datetime.now(timezone.utc)
        since = until - timedelta(hours=hours)
        # One snapshot prevents a conflict commit between row and coverage reads
        # from advertising previously trusted amounts as current complete data.
        async def read(session):
            await ensure_direct_binding(self._db, self._settings, session=session)
            query = {"connection_id": self._settings.connection_id, "metric.source": "guardian_direct",
                     "metric.project_id": self._settings.project_id,
                     "metric.environment": self._settings.environment,
                     "metric.timestamp": {"$gte": since, "$lt": until}}
            if trace_id is not None:
                query["metric.trace_id"] = trace_id
            projection = {"state": 1, **{"metric." + field: 1 for field in SAFE_FIELDS}}
            docs = await self._db.guardian_observations.find(query, projection, session=session, max_time_ms=2000).sort(
                "metric.timestamp", -1).limit(MAX_RECORDS + 1).to_list(MAX_RECORDS + 1)
            pending = await self._db.guardian_capture_inbox.count_documents(
                {"connection_id": self._settings.connection_id, "processed": False}, session=session, maxTimeMS=2000)
            detector_pending = await self._db.guardian_observations.count_documents(
                {"connection_id": self._settings.connection_id, "pending": True}, session=session, maxTimeMS=2000)
            dirty = await self._db.guardian_dirty_buckets.count_documents(
                {"connection_id": self._settings.connection_id}, session=session, maxTimeMS=2000)
            return docs, pending, detector_pending, dirty
        docs, pending, detector_pending, dirty = await self._ledger.transaction(read)
        limited = len(docs) > MAX_RECORDS
        metrics, conflicts = [], 0
        for doc in docs[:MAX_RECORDS]:
            metric = restore_metric(doc)
            if doc["state"] != "accepted":
                conflicts += 1
                metric = replace(metric, cost_usd=None, cost_usd_decimal=None, total_tokens=None,
                    input_tokens=None, output_tokens=None, latency_ms=None, status="unknown",
                    normalization_issues=("observation_identity_conflict",))
            metrics.append(metric)
        reason = ("limit_reached" if limited else "conflicted_observations" if conflicts else
                  "capture_pending" if pending else "processing_pending" if detector_pending or dirty else None)
        coverage = {"scope": "captured_trace_events" if trace_id is not None else "captured_terminal_events",
            "status": "partial" if reason else "complete", "window_start": since.isoformat(),
            "window_end": until.isoformat(), "fetched_at": datetime.now(timezone.utc).isoformat(),
            "observed_count": len(metrics), "records_read": len(docs), "invalid_count": conflicts,
            "duplicate_count": 0, "pages_fetched": 1, "max_records": MAX_RECORDS, "max_pages": 1,
            "truncated": limited, "reason": reason, "issues": {"observation_identity_conflict": conflicts} if conflicts else {},
            "next_page": None, "has_more": limited, "pending_events": pending,
            "pending_observations": detector_pending, "dirty_buckets": dirty}
        calls = [_metric_to_call(metric) for metric in metrics]
        return metrics, calls, coverage

    async def snapshot(self, hours=24, run_limit=8, call_limit=60):
        if (type(hours) is not int or not 1 <= hours <= 168 or type(run_limit) is not int
                or not 1 <= run_limit <= 100 or type(call_limit) is not int or not 1 <= call_limit <= 100):
            raise ValueError("Live query exceeds supported bounds")
        try:
            metrics, calls, coverage = await asyncio.wait_for(self._read(hours), READ_TIMEOUT_SECONDS)
        except Exception:
            raise LiveReadError("capture_read_unavailable") from None
        return {**SOURCE_FIELDS, "available": True, "degraded": False, "stale": False,
            "fetched_at": coverage["fetched_at"], "coverage": coverage,
            "stats": _stats_from(calls, hours), "calls": calls[:call_limit],
            "runs": _runs_from(metrics, calls, lambda _: None, coverage)[:run_limit],
            "feed": {"returned": min(call_limit, len(calls)), "limit": call_limit, "limited": len(calls) > call_limit}}

    async def run_detail(self, trace_id, hours=168):
        if type(hours) is not int or not 1 <= hours <= 168:
            raise ValueError("Run query exceeds supported bounds")
        try:
            metrics, calls, coverage = await asyncio.wait_for(self._read(hours, trace_id), READ_TIMEOUT_SECONDS)
        except Exception:
            raise LiveReadError("capture_read_unavailable") from None
        calls.reverse()
        return {**_run_from(trace_id, calls, lambda _: None, coverage, metrics), **SOURCE_FIELDS,
            "window_hours": hours, "calls": calls, "stale": False, "fetched_at": coverage["fetched_at"]}
