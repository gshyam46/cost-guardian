"""Durable numeric inbox admission, separate from asynchronous detection."""
from datetime import datetime, timedelta, timezone

from guardian.ledger import ObservationLedger, digest, identity, safe_metric
from identity.store import IdentityStore
from .credentials import IngestionCredentialStore
from .errors import CaptureError, bounded
from .settings import ensure_direct_binding


class CaptureService:
    def __init__(self, db, settings, now=None):
        self.db, self.settings = db, settings
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.identity = IdentityStore(db, settings)
        self.credentials = IngestionCredentialStore(db, settings)

    def collection(self, name):
        return self.identity._collection(name)

    @bounded(35)
    async def ingest(self, token, batch):
        metrics = [safe_metric(metric) for metric in batch.metrics]
        fingerprint = digest([batch.test_mode, metrics])
        receipt_id = digest([self.identity.binding_id, batch.batch_id])
        now = self.now()
        async def commit(session):
            options = {"session": session} if session is not None else {}
            key = await self.credentials.authenticate_ingestion(token, session=session, touch=True)
            await ensure_direct_binding(self.db, self.settings, session=session, touch=True)
            receipts = self.collection("guardian_capture_receipts")
            existing = await receipts.find_one({"_id": receipt_id}, **options)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise CaptureError(409, "batch_id_conflict")
                return {**existing["response"], "replayed": True}
            minute = int(now.timestamp()) // 60
            quota = self.collection("guardian_capture_admission")
            for scope, amount, maximum in (("key:" + key["_id"], 1, 120), ("project_batches", 1, 300),
                                          ("project_events", len(metrics), 6000)):
                counter_id = digest([self.identity.binding_id, scope, minute])
                old = await quota.find_one({"_id": counter_id}, **options) or {}
                if old.get("count", 0) + amount > maximum:
                    raise CaptureError(429, "capture_rate_limited")
                await quota.update_one({"_id": counter_id}, {"$inc": {"count": amount},
                    "$setOnInsert": {"expires_at": now + timedelta(minutes=3)}}, upsert=True, **options)
            state = self.collection("guardian_state")
            current = await state.find_one({"_id": "direct_capture"}, **options) or {}
            sequence = current.get("last_sequence", 0)
            received = duplicate = conflict = 0
            inbox = self.collection("guardian_capture_inbox")
            if batch.test_mode:
                received = len(metrics)
                await state.update_one({"_id": "direct_capture"},
                    {"$set": {"binding_id": self.identity.binding_id, "last_test_received_at": now}}, upsert=True, **options)
            else:
                for metric, value in zip(batch.metrics, metrics):
                    observation_key = identity(metric, self.settings.connection_id)
                    metric_fingerprint = digest(value)
                    row_id = digest([observation_key, metric_fingerprint])
                    if await inbox.find_one({"_id": row_id}, {"_id": 1}, **options):
                        duplicate += 1
                        continue
                    different = await inbox.find_one({"observation_key": observation_key}, {"_id": 1}, **options)
                    if different:
                        conflict += 1
                    sequence += 1
                    await inbox.insert_one({"_id": row_id, "observation_key": observation_key,
                        "fingerprint": metric_fingerprint, "binding_id": self.identity.binding_id,
                        "connection_id": self.settings.connection_id, "sequence": sequence, "metric": value,
                        "received_at": now, "processed": False, "processed_at": None}, **options)
                    received += 1
                # Checked after proposed writes but before commit; excess rolls back.
                pending = await inbox.count_documents({"binding_id": self.identity.binding_id, "processed": False},
                                                      limit=10001, **options)
                if pending > 10000:
                    raise CaptureError(429, "capture_backlog_full")
                await state.update_one({"_id": "direct_capture"},
                    {"$set": {"binding_id": self.identity.binding_id, "last_sequence": sequence,
                              "last_received_at": now}, "$inc": {"received_events": received}}, upsert=True, **options)
            response = {"batch_id": batch.batch_id, "received": received, "duplicate": duplicate,
                        "conflict_candidates": conflict, "test_mode": batch.test_mode, "replayed": False,
                        "processing": "test_only" if batch.test_mode else "queued"}
            await receipts.insert_one({"_id": receipt_id, "binding_id": self.identity.binding_id,
                "batch_id": batch.batch_id, "fingerprint": fingerprint, "received_at": now,
                "response": response}, **options)
            return response
        return await ObservationLedger(self.db).transaction(commit)

    @bounded()
    async def status(self):
        await ensure_direct_binding(self.db, self.settings)
        state = await self.collection("guardian_state").find_one({"_id": "direct_capture"}, max_time_ms=2000) or {}
        processing = await self.collection("guardian_state").find_one({"_id": "direct_processing"}, max_time_ms=2000) or {}
        worker = await self.collection("guardian_state").find_one({"_id": "guardian_worker_cursor"}, max_time_ms=2000) or {}
        query = {"binding_id": self.identity.binding_id}
        pending = await self.collection("guardian_capture_inbox").count_documents({**query, "processed": False}, maxTimeMS=2000)
        processed = await self.collection("guardian_capture_inbox").count_documents({**query, "processed": True}, maxTimeMS=2000)
        conflicts = await self.collection("guardian_observations").count_documents(
            {"connection_id": self.settings.connection_id, "metric.source": "guardian_direct", "state": "conflicted"}, maxTimeMS=2000)
        def stamp(value):
            if value is None:
                return None
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        attempted = stamp(worker.get("last_attempt_at"))
        from config import POLL_INTERVAL_SECONDS
        threshold = max(120, max(1, POLL_INTERVAL_SECONDS) * 3 + 20)
        worker_status = "not_started" if not attempted else (
            "current" if (self.now() - datetime.fromisoformat(attempted)).total_seconds() <= threshold else "stale")
        return {"last_test_received_at": stamp(state.get("last_test_received_at")),
                "last_received_at": stamp(state.get("last_received_at")), "received_events": state.get("received_events", 0),
                "pending_events": pending, "processed_events": processed,
                "last_processed_at": stamp(processing.get("last_processed_at")), "conflicted_events": conflicts,
                "worker_status": worker_status}

    @bounded()
    async def ensure_indexes(self):
        await self.collection("guardian_capture_admission").create_index("expires_at", expireAfterSeconds=0,
            name="capture_admission_expiry", maxTimeMS=2000)
        await self.collection("guardian_capture_inbox").create_index([("binding_id", 1), ("processed", 1), ("sequence", 1)], maxTimeMS=2000)
        await self.collection("guardian_capture_inbox").create_index("observation_key", maxTimeMS=2000)
