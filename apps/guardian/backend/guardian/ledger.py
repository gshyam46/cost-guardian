"""Transactional observation ledger. See docs/INGESTION.md for the contract.

All production writes require Mongo transactions. Unit tests may explicitly replace
transaction(), but there is no runtime fallback for standalone Mongo or mocks.
"""
from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from .models import TraceMetric

LEASE_SECONDS = 90
MAX_BUCKET_ROWS = 10000
MAX_BASELINE_ROWS = 5000
CURSOR_DOC_ID = "guardian_worker_cursor"
LEDGER_VERSION = "ledger-1"


class LedgerError(RuntimeError):
    """A safe diagnostic code, never source content or database error text."""


class LeaseLost(LedgerError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=lambda v: aware(v).isoformat()).encode()).hexdigest()


def identity(metric, connection_id):
    if any(not isinstance(value, str) or not value.strip() for value in (metric.observation_id, metric.trace_id)):
        raise LedgerError("missing_observation_identity")
    return digest([connection_id, metric.source, metric.project_id, metric.trace_id, metric.observation_id])


# Explicit allowlist: never add output/status text or user/session/tag attributes.
SAFE_FIELDS = (
    "trace_id", "observation_id", "source", "project_id", "agent_name", "model",
    "cost_usd", "cost_usd_decimal", "total_tokens", "input_tokens", "output_tokens",
    "latency_ms", "status", "timestamp", "ended_at", "completion_state",
    "observation_kind", "environment", "version", "parent_observation_id",
)


def safe_metric(metric):
    value = {name: getattr(metric, name) for name in SAFE_FIELDS}
    if value["timestamp"].tzinfo is None:
        raise LedgerError("invalid_observation_timestamp")
    if value["cost_usd_decimal"] is None and metric.cost_usd is not None:
        value["cost_usd_decimal"] = str(metric.cost_usd)
    return value


def restore_metric(doc):
    values = dict(doc["metric"])
    for field in ("timestamp", "ended_at"):
        if values.get(field):
            values[field] = aware(values[field])
    return TraceMetric(**values)


def bucket_for(metric):
    from .metrics import hour_bucket, rollup_id
    hour = hour_bucket(metric.timestamp)
    return {"_id": rollup_id(hour, metric.agent_name), "hour": hour, "agent_name": metric.agent_name}


@dataclass(frozen=True)
class Lease:
    owner: str
    epoch: int


class ObservationLedger:
    def __init__(self, db, connection_id="primary"):
        self.db = db
        self.connection_id = connection_id
        self.lease_id = "ingestion:" + connection_id

    async def transaction(self, callback):
        # Motor 3.3.1's context manager commits before its with_transaction retry
        # loop. Own the explicit commit boundary so an uncertain acknowledgement
        # retries commit on the SAME transaction, not the callback.
        deadline = time.monotonic() + 30
        async with await self.db.client.start_session() as session:
            while True:
                session.start_transaction(read_concern=ReadConcern("snapshot"),
                    write_concern=WriteConcern("majority"), max_commit_time_ms=10000)
                try:
                    result = await callback(session)
                except BaseException as error:
                    if session.in_transaction:
                        try:
                            await session.abort_transaction()
                        except PyMongoError:
                            pass
                    if isinstance(error, PyMongoError) and error.has_error_label("TransientTransactionError") and time.monotonic() < deadline:
                        await asyncio.sleep(0.01)
                        continue
                    raise
                while True:
                    try:
                        await session.commit_transaction()
                        return result
                    except PyMongoError as error:
                        if time.monotonic() >= deadline:
                            raise
                        if error.has_error_label("UnknownTransactionCommitResult"):
                            await asyncio.sleep(0.01)
                            continue
                        if error.has_error_label("TransientTransactionError"):
                            break
                        raise

    async def ensure_indexes(self):
        await self.db.guardian_observations.create_index([("connection_id", 1), ("bucket_ids", 1)])
        await self.db.guardian_observations.create_index([("connection_id", 1), ("metric.agent_name", 1), ("metric.timestamp", 1)])
        await self.db.guardian_observations.create_index([("connection_id", 1), ("pending", 1)])
        await self.db.guardian_dirty_buckets.create_index([("connection_id", 1)])

    async def acquire(self, owner=None):
        owner = owner or uuid4().hex
        try:
            await self.db.guardian_leases.update_one(
                {"_id": self.lease_id}, {"$setOnInsert": {"epoch": 0, "owner": None, "expires_at": datetime(1970, 1, 1, tzinfo=timezone.utc), "fence": 0}}, upsert=True,
            )
        except DuplicateKeyError:
            pass
        now = utcnow()
        doc = await self.db.guardian_leases.find_one_and_update(
            {"_id": self.lease_id, "expires_at": {"$lte": now}},
            {"$set": {"owner": owner, "expires_at": now + timedelta(seconds=LEASE_SECONDS)}, "$inc": {"epoch": 1, "fence": 1}},
            return_document=ReturnDocument.AFTER,
        )
        return Lease(owner, doc["epoch"]) if doc else None

    async def release(self, lease):
        await self.db.guardian_leases.update_one(
            {"_id": self.lease_id, "owner": lease.owner, "epoch": lease.epoch},
            {"$set": {"expires_at": utcnow(), "owner": None}, "$inc": {"fence": 1}},
        )

    async def _touch(self, lease, session):
        now = utcnow()
        result = await self.db.guardian_leases.update_one(
            {"_id": self.lease_id, "owner": lease.owner, "epoch": lease.epoch, "expires_at": {"$gt": now}},
            {"$inc": {"fence": 1}, "$set": {"expires_at": now + timedelta(seconds=LEASE_SECONDS)}}, session=session,
        )
        if result.matched_count != 1:
            raise LeaseLost("worker_lease_lost")

    async def _migration_guard(self, session):
        if await self.db.guardian_metrics.find_one({"accounting_status": {"$ne": LEDGER_VERSION}}, session=session):
            raise LedgerError("legacy_metrics_migration_required")
        # This deployment is single-connection. Do not silently mix two projects.
        state = await self.db.guardian_state.find_one({"_id": "ledger_configuration"}, session=session)
        if state and state["connection_id"] != self.connection_id:
            raise LedgerError("connection_cutover_required")
        await self.db.guardian_state.update_one(
            {"_id": "ledger_configuration"}, {"$setOnInsert": {"connection_id": self.connection_id, "version": LEDGER_VERSION}}, upsert=True, session=session,
        )

    async def _langfuse_guard(self, session):
        from capture.errors import CaptureError
        from capture.settings import claim_langfuse_binding
        try:
            await claim_langfuse_binding(self.db, session=session)
        except CaptureError:
            raise LedgerError("source_mode_reconciliation_required") from None

    async def claim_langfuse(self, lease):
        """Establish the shared mode fence before recovery or upstream reads."""
        async def commit(session):
            await self._touch(lease, session)
            await self._langfuse_guard(session)
        await self.transaction(commit)

    async def begin_window(self, lease, start, end, api_version):
        async def commit(session):
            await self._touch(lease, session)
            await self._langfuse_guard(session)
            state = await self.db.guardian_state.find_one({"_id": CURSOR_DOC_ID}, session=session) or {}
            active = state.get("active_window")
            if active:
                if active["api_version"] != api_version:
                    raise LedgerError("source_mode_reconciliation_required")
                return active
            active = {"id": uuid4().hex, "start": aware(start).isoformat(), "end": aware(end).isoformat(), "api_version": api_version,
                      "cursor": None, "query_fingerprint": None, "page": 0, "restarts": 0, "quarantined": 0}
            await self.db.guardian_state.update_one({"_id": CURSOR_DOC_ID}, {"$set": {"active_window": active}}, upsert=True, session=session)
            return active
        return await self.transaction(commit)

    async def restart_window(self, lease, window):
        async def commit(session):
            await self._touch(lease, session)
            await self._langfuse_guard(session)
            if window["restarts"] >= 1:
                raise LedgerError("source_cursor_restart_exhausted")
            result = await self.db.guardian_state.update_one(
                {"_id": CURSOR_DOC_ID, "active_window.id": window["id"], "active_window.page": window["page"]},
                {"$set": {"active_window.cursor": None}, "$inc": {"active_window.restarts": 1}}, session=session,
            )
            if result.matched_count != 1:
                raise LedgerError("stale_source_page")
        await self.transaction(commit)

    async def _dirty(self, bucket, session):
        await self.db.guardian_dirty_buckets.update_one(
            {"_id": digest([self.connection_id, bucket["_id"]])},
            {"$set": {"connection_id": self.connection_id, "bucket": bucket}, "$inc": {"version": 1}}, upsert=True, session=session,
        )

    async def _accept(self, metric, pii_results, session):
        key = identity(metric, self.connection_id)
        value = safe_metric(metric)
        fingerprint = digest(value)
        bucket = bucket_for(metric)
        existing = await self.db.guardian_observations.find_one({"_id": key}, session=session)
        if existing and existing["fingerprint"] == fingerprint:
            return "duplicate"
        if existing:
            conflict_id = digest([key, fingerprint])
            if await self.db.guardian_quarantine.find_one({"_id": conflict_id}, session=session):
                return "duplicate"
            buckets = {item["_id"]: item for item in existing["buckets"]}
            buckets[bucket["_id"]] = bucket
            if len(buckets) > 16:
                raise LedgerError("observation_conflict_limit")
            await self.db.guardian_observations.update_one(
                {"_id": key}, {"$set": {"state": "conflicted", "metric": existing.get("metric") or value,
                                        "buckets": list(buckets.values()), "bucket_ids": list(buckets), "pending": False},
                               "$inc": {"version": 1}}, session=session,
            )
            await self.db.guardian_quarantine.update_one(
                {"_id": conflict_id},
                {"$setOnInsert": {"connection_id": self.connection_id, "observation_key": key, "fingerprint": fingerprint, "issues": ["observation_identity_conflict"], "created_at": utcnow()}}, upsert=True, session=session,
            )
            for item in buckets.values():
                await self._dirty(item, session)
            await self.db.guardian_incidents.update_many({"id": {"$in": existing.get("signal_ids", [])}},
                {"$set": {"evidence.measurement_status": "conflicted"}}, session=session)
            return "conflict"
        await self.db.guardian_observations.insert_one(
            {"_id": key, "connection_id": self.connection_id, "metric": value, "fingerprint": fingerprint,
             "state": "accepted", "buckets": [bucket], "bucket_ids": [bucket["_id"]], "version": 1,
             "pending": True, "completed_rules": [], "pii_results": pii_results, "ingested_at": utcnow()}, session=session,
        )
        await self._dirty(bucket, session)
        return "accepted"

    async def ingest_metrics(self, metrics, lease, pii_results=None):
        """Compatibility entry point for normalized Langfuse metrics callers.

        Native capture commits its inbox acknowledgment with _accept instead.
        """
        prepared = pii_results or {}
        # Validate before transaction entry; callbacks have no content processing.
        for metric in metrics:
            if metric.source != "langfuse":
                raise LedgerError("capture_inbox_required")
            identity(metric, self.connection_id)
            safe_metric(metric)
        async def commit(session):
            await self._touch(lease, session)
            await self._langfuse_guard(session)
            await self._migration_guard(session)
            counts = {"accepted": 0, "duplicate": 0, "conflict": 0}
            for metric in metrics:
                result = await self._accept(metric, prepared.get(identity(metric, self.connection_id), []), session)
                counts[result] += 1
            return counts
        return await self.transaction(commit)

    async def commit_page(self, lease, window, page, pii_results=None):
        if page.status != "ok" or page.exhausted is None:
            raise LedgerError("uncommittable_source_page")
        if (page.api_version != window["api_version"] or page.records_read != len(page.rows)
                or not page.query_fingerprint or len({row.ordinal for row in page.rows}) != len(page.rows)
                or (page.exhausted and page.next_cursor is not None)
                or (not page.exhausted and page.next_cursor is None)):
            raise LedgerError("invalid_page_contract")
        if aware(page.window_start) != aware(window["start"]) or aware(page.window_end) != aware(window["end"]):
            raise LedgerError("source_window_mismatch")
        if page.request_cursor != window["cursor"]:
            raise LedgerError("source_cursor_mismatch")
        prepared = pii_results or {}
        async def commit(session):
            await self._touch(lease, session)
            await self._langfuse_guard(session)
            await self._migration_guard(session)
            configuration = await self.db.guardian_state.find_one({"_id": "ledger_configuration"}, session=session)
            contract = {"source_api_version": page.api_version, "normalization_version": page.normalization_version}
            if any(configuration.get(key, value) != value for key, value in contract.items()):
                raise LedgerError("source_mode_reconciliation_required")
            await self.db.guardian_state.update_one({"_id": "ledger_configuration"}, {"$set": contract}, session=session)
            state = await self.db.guardian_state.find_one({"_id": CURSOR_DOC_ID}, session=session) or {}
            active = state.get("active_window")
            if not active or active["id"] != window["id"] or active["page"] != window["page"] or active["restarts"] != window["restarts"]:
                raise LedgerError("stale_source_page")
            if active["query_fingerprint"] and active["query_fingerprint"] != page.query_fingerprint:
                raise LedgerError("source_query_mismatch")
            receipt_id = digest([window["id"], window["restarts"], page.request_cursor])
            if page.next_cursor is not None:
                next_id = digest([window["id"], window["restarts"], page.next_cursor])
                if next_id == receipt_id or await self.db.guardian_page_receipts.find_one({"_id": next_id}, session=session):
                    raise LedgerError("source_cursor_cycle")
            counts = {"accepted": 0, "duplicate": 0, "conflict": 0, "quarantined": 0}
            for row in page.rows:
                if row.disposition == "accepted" and row.metric is not None:
                    result = await self._accept(row.metric, prepared.get(identity(row.metric, self.connection_id), []), session)
                    counts[result] += 1
                else:
                    counts["quarantined"] += 1
                    await self.db.guardian_quarantine.update_one(
                        {"_id": digest([receipt_id, row.ordinal])},
                        {"$setOnInsert": {"connection_id": self.connection_id, "window_id": window["id"],
                                          "ordinal": row.ordinal, "fingerprint": row.record_fingerprint,
                                          "issues": list(row.issues), "created_at": utcnow()}}, upsert=True, session=session,
                    )
                    # A bad later copy with known identity invalidates earlier trust.
                    if row.trace_id and row.observation_id:
                        key = digest([self.connection_id, "langfuse", row.source_project_id, row.trace_id, row.observation_id])
                        old = await self.db.guardian_observations.find_one({"_id": key}, session=session)
                        if old:
                            await self.db.guardian_observations.update_one({"_id": key}, {"$set": {"state": "conflicted", "pending": False}, "$inc": {"version": 1}}, session=session)
                            await self.db.guardian_incidents.update_many({"id": {"$in": old.get("signal_ids", [])}},
                                {"$set": {"evidence.measurement_status": "conflicted"}}, session=session)
                            for bucket in old["buckets"]:
                                await self._dirty(bucket, session)
                        else:
                            # A known rejected identity must not become trusted on
                            # a later copy solely because that copy parses.
                            await self.db.guardian_observations.insert_one({"_id": key, "connection_id": self.connection_id,
                                "metric": None, "fingerprint": row.record_fingerprint, "state": "conflicted",
                                "buckets": [], "bucket_ids": [], "version": 1, "pending": False,
                                "completed_rules": [], "pii_results": [], "ingested_at": utcnow()}, session=session)
            await self.db.guardian_page_receipts.insert_one({"_id": receipt_id, "window_id": window["id"], "records": len(page.rows), "counts": counts}, session=session)
            quarantined = active["quarantined"] + counts["quarantined"] + counts["conflict"]
            changes = {"source_fetched_at": page.fetched_at.isoformat(), "ledger_version": LEDGER_VERSION}
            if page.exhausted:
                changes.update({"active_window": None, "last_polled_at": aware(window["end"]).isoformat(),
                                "source_watermark": aware(window["end"]).isoformat(), "last_window_quarantined": quarantined})
            else:
                changes["active_window"] = dict(active, cursor=page.next_cursor, query_fingerprint=page.query_fingerprint,
                                                page=active["page"] + 1, quarantined=quarantined)
            await self.db.guardian_state.update_one({"_id": CURSOR_DOC_ID}, {"$set": changes}, session=session)
            return counts
        return await self.transaction(commit)

    async def rebuild(self, lease, limit=100):
        """Replace bounded buckets; transaction fence prevents stale publication."""
        dirty = await self.db.guardian_dirty_buckets.find({"connection_id": self.connection_id}).limit(limit).to_list(limit)
        for work in dirty:
            async def commit(session):
                await self._touch(lease, session)
                current = await self.db.guardian_dirty_buckets.find_one({"_id": work["_id"]}, session=session)
                if current is None:
                    return
                bucket = current["bucket"]
                rows = await self.db.guardian_observations.find({"connection_id": self.connection_id, "bucket_ids": bucket["_id"]}, session=session).limit(MAX_BUCKET_ROWS + 1).to_list(MAX_BUCKET_ROWS + 1)
                if len(rows) > MAX_BUCKET_ROWS:
                    raise LedgerError("ledger_bucket_read_limit")
                doc = dict(bucket, call_count=0, error_count=0, unknown_status_count=0, total_cost_usd=0.0,
                           total_tokens=0, sum_latency_ms=0.0, conflict_count=0, accounting_status=LEDGER_VERSION,
                           materialized_at=utcnow(), materialization_version=current["version"])
                for name in ("cost", "tokens", "latency"):
                    doc[name + "_known_count"] = doc[name + "_unknown_count"] = 0
                for row in rows:
                    metric = row["metric"]
                    trusted = row["state"] == "accepted"
                    doc["conflict_count"] += int(not trusted)
                    # Keep one count per identity across all affected buckets.
                    # Additional disputed attributions only mark a coverage gap.
                    if bucket_for(restore_metric(row))["_id"] != bucket["_id"]:
                        continue
                    doc["call_count"] += 1
                    doc["error_count"] += int(trusted and metric["status"] == "error")
                    doc["unknown_status_count"] += int(not trusted or metric["status"] not in ("success", "error"))
                    for name, value_field, sum_field in (("cost", "cost_usd", "total_cost_usd"), ("tokens", "total_tokens", "total_tokens"), ("latency", "latency_ms", "sum_latency_ms")):
                        known = trusted and metric[value_field] is not None
                        doc[name + "_known_count"] += int(known)
                        doc[name + "_unknown_count"] += int(not known)
                        if known:
                            doc[sum_field] += metric[value_field]
                if doc["total_tokens"] > (1 << 63) - 1:
                    doc["total_tokens_exact"] = str(doc["total_tokens"])
                    doc["total_tokens"] = None
                await self.db.guardian_metrics.replace_one({"_id": bucket["_id"]}, doc, upsert=True, session=session)
                await self.db.guardian_dirty_buckets.delete_one({"_id": current["_id"], "version": current["version"]}, session=session)
            await self.transaction(commit)

    async def process_pending(self, lease, detectors, limit=100):
        from .detectors.base import DetectorResult
        from .detectors import monitoring_policy
        from .incident_engine import process_detector_results, signal_id
        from .store import MongoIncidentStore
        from policies.store import pin_policy
        state = await self.db.guardian_state.find_one({"_id": CURSOR_DOC_ID}) or {}
        if state.get("active_window"):
            # Descending source pages may deliver a candidate before its older
            # baseline. Do not settle a no-finding decision on that partial view.
            return 0, 0
        pending = await self.db.guardian_observations.find({"connection_id": self.connection_id, "pending": True, "state": "accepted"}).sort("metric.timestamp", 1).limit(limit).to_list(limit)
        created = 0
        failures = 0
        for row in pending:
            policy = await pin_policy(self, lease, row)
            if policy is None:
                continue
            candidate = restore_metric(row)
            baseline, baseline_available = [], True
            try:
                baseline_docs = await self.db.guardian_observations.find({
                    "connection_id": self.connection_id, "state": "accepted", "metric.agent_name": candidate.agent_name,
                    "metric.timestamp": {"$gte": candidate.timestamp - timedelta(hours=24), "$lt": candidate.timestamp},
                }).limit(MAX_BASELINE_ROWS + 1).to_list(MAX_BASELINE_ROWS + 1)
                baseline_available = len(baseline_docs) <= MAX_BASELINE_ROWS
                if baseline_available:
                    baseline = [restore_metric(doc) for doc in baseline_docs]
            except Exception:
                # Independent limits/error rules can still commit. A failed
                # relative read never becomes an empty successful baseline.
                baseline_available = False
            results, completed = [], list(row["completed_rules"])
            for detector in detectors:
                rule = monitoring_policy.token(detector, policy) if detector.NAME in monitoring_policy.NAMES else detector.NAME + ":" + getattr(detector, "RULE_VERSION", "1")
                if detector.NAME in monitoring_policy.NAMES:
                    try:
                        evaluation = monitoring_policy.evaluate(detector, baseline, candidate, policy,
                            completed, baseline_available=baseline_available)
                        results.extend(evaluation.results)
                        completed = evaluation.completed
                        failures += int(evaluation.blocked)
                    except Exception:
                        failures += 1
                    continue
                if rule in completed:
                    continue
                try:
                    if detector.NAME == "pii":
                        results.extend(DetectorResult(**value) for value in row["pii_results"])
                    else:
                        if not baseline_available:
                            failures += 1
                            continue
                        results.extend(detector.evaluate(baseline, [candidate]))
                    completed.append(rule)
                except Exception:
                    failures += 1
            done = all(monitoring_policy.is_complete(detector, policy, completed) if detector.NAME in monitoring_policy.NAMES
                       else detector.NAME + ":" + getattr(detector, "RULE_VERSION", "1") in completed for detector in detectors)
            async def commit(session):
                await self._touch(lease, session)
                current = await self.db.guardian_observations.find_one({"_id": row["_id"]}, session=session)
                if (current is None or current["version"] != row["version"] or current["state"] != "accepted"
                        or current.get("monitoring_policy") != policy):
                    return 0
                incidents = await process_detector_results(results, MongoIncidentStore(self.db, session=session), scope_id=self.connection_id)
                from notifications.outbox import enqueue_created
                await enqueue_created(self.db, self.connection_id, incidents, session)
                signal_ids = list(set(current.get("signal_ids", [])) | {signal_id(result, scope_id=self.connection_id) for result in results if result.triggered and result.trace_ids})
                await self.db.guardian_observations.update_one({"_id": row["_id"], "version": row["version"]}, {"$set": {"completed_rules": completed, "pending": not done, "signal_ids": signal_ids}}, session=session)
                return len(incidents)
            created += await self.transaction(commit)
        return created, failures

    async def backlog(self):
        return {
            "pending_observations": await self.db.guardian_observations.count_documents({"connection_id": self.connection_id, "pending": True}),
            "dirty_buckets": await self.db.guardian_dirty_buckets.count_documents({"connection_id": self.connection_id}),
            "quarantined_records": await self.db.guardian_quarantine.count_documents({"connection_id": self.connection_id}),
        }
