"""Direct worker semantics; real Mongo separately proves transaction rollback."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest
from mongomock_motor import AsyncMongoMockClient

from capture.errors import CaptureError
from capture.settings import ensure_direct_binding
from guardian import direct_worker
from guardian.ledger import LedgerError, ObservationLedger, digest, identity, safe_metric
from guardian.metrics import MongoMetricsStore
from guardian.models import TraceMetric
from guardian.models import SourcePageResult, SourceReadResult
from identity.settings import Settings
from identity.store import IdentityStore

pytestmark = pytest.mark.anyio
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
async def environment(monkeypatch):
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "direct")
    db = AsyncMongoMockClient(tz_aware=True)["direct_worker_tests"]
    settings = Settings(mode="oidc", organization_id="organization", project_id="project", environment="test",
                        connection_id="primary", issuer="https://issuer.example.invalid", client_id="test-client")
    await IdentityStore(db, settings).ensure_binding()
    binding = await ensure_direct_binding(db, settings)
    return db, settings, binding


def metric(identifier="call-one", **changes):
    value = TraceMetric(trace_id="trace-one", observation_id=identifier, source="guardian_direct", project_id="project",
        environment="test", agent_name="answer-agent", model="test-model", cost_usd=.01, cost_usd_decimal="0.01",
        total_tokens=12, input_tokens=10, output_tokens=2, latency_ms=100, status="success",
        timestamp=NOW - timedelta(minutes=1), ended_at=NOW - timedelta(minutes=1) + timedelta(milliseconds=100),
        completion_state="completed")
    return replace(value, **changes)


async def enqueue(environment, metrics):
    db, settings, binding = environment
    state = await db.guardian_state.find_one({"_id": "direct_capture"}) or {}
    sequence = state.get("last_sequence", 0)
    for value in metrics:
        sequence += 1
        stored = safe_metric(value)
        await db.guardian_capture_inbox.insert_one({"_id": digest([identity(value, settings.connection_id), digest(stored)]),
            "binding_id": binding["binding_id"], "connection_id": settings.connection_id, "sequence": sequence,
            "metric": stored, "received_at": NOW, "processed": False, "processed_at": None})
    await db.guardian_state.update_one({"_id": "direct_capture"},
        {"$set": {"binding_id": binding["binding_id"], "last_sequence": sequence}}, upsert=True)


async def test_terminal_error_receipt_reaches_ledger_metrics_incident_once(environment):
    db, settings, _ = environment
    await enqueue(environment, [metric(status="error")])
    assert await direct_worker.poll_direct_once(db, settings) == 1
    assert await direct_worker.poll_direct_once(db, settings) == 0
    observation = await db.guardian_observations.find_one({})
    assert observation["pending"] is False
    assert {"cost_anomaly:2", "reliability_anomaly:1"} <= set(observation["completed_rules"])
    assert observation["monitoring_policy"]["revision"] == 0
    assert observation["pii_results"] == []
    assert await db.guardian_incidents.count_documents({}) == 1
    assert (await db.guardian_capture_inbox.find_one({}))["processed"] is True
    rows = await MongoMetricsStore(db).since(NOW - timedelta(hours=1))
    assert rows[0]["call_count"] == 1
    assert rows[0]["error_count"] == 1
    assert rows[0]["total_cost_usd"] == .01
    assert rows[0]["total_tokens"] == 12
    state = await db.guardian_state.find_one({"_id": "guardian_worker_cursor"})
    assert state["source_api_version"] == "direct-v1"
    assert state["processing_status"] == "complete"
    assert not {"source_watermark", "processing_watermark", "last_polled_at", "active_window"} & state.keys()


async def test_later_conflicting_event_invalidates_trusted_amount_and_replay_cannot_restore(environment):
    db, settings, _ = environment
    original = metric()
    await enqueue(environment, [original])
    await direct_worker.poll_direct_once(db, settings)
    await enqueue(environment, [replace(original, cost_usd=5, cost_usd_decimal="5")])
    await direct_worker.poll_direct_once(db, settings)
    row = (await MongoMetricsStore(db).since(NOW - timedelta(hours=1)))[0]
    assert row["call_count"] == 1
    assert row["total_cost_usd"] is None
    assert row["cost_unknown_count"] == 1
    assert row["conflict_count"] == 1
    assert await db.guardian_quarantine.count_documents({}) == 1
    # Replay after an interrupted acknowledgment must retain the conflict.
    await db.guardian_capture_inbox.update_many({}, {"$set": {"processed": False}})
    await direct_worker.poll_direct_once(db, settings)
    assert await db.guardian_observations.count_documents({}) == 1
    assert (await db.guardian_observations.find_one({}))["state"] == "conflicted"


async def test_more_than_500_receipts_resume_original_cutoff_and_wait_for_baseline(environment):
    db, settings, _ = environment
    # Candidate arrives first; its older same-agent baseline is across the poll boundary.
    candidate = metric("candidate", cost_usd=5, cost_usd_decimal="5")
    padding = [metric(f"padding-{n}", agent_name="other-agent") for n in range(499)]
    baseline = [metric(f"baseline-{n}", timestamp=NOW - timedelta(minutes=10 + n)) for n in range(6)]
    await enqueue(environment, [candidate, *padding, *baseline])
    assert await direct_worker.poll_direct_once(db, settings) == 0
    assert await db.guardian_observations.count_documents({}) == 500
    assert await db.guardian_incidents.count_documents({}) == 0
    progress = await db.guardian_state.find_one({"_id": "direct_processing"})
    assert progress["cutoff_sequence"] == 506
    await enqueue(environment, [metric("newer-arrival", status="error")])
    assert await direct_worker.poll_direct_once(db, settings) == 1
    assert await db.guardian_capture_inbox.count_documents({"processed": False}) == 1
    progress = await db.guardian_state.find_one({"_id": "direct_processing"})
    assert progress["cutoff_sequence"] is None
    assert progress["last_completed_sequence"] == 506
    incident = await db.guardian_incidents.find_one({})
    assert incident["detector"] == "cost_anomaly"
    assert incident["evidence"]["baseline_n"] == 6


async def test_db_failure_before_acceptance_leaves_pending_and_safe_diagnostic(environment, monkeypatch, caplog):
    db, settings, _ = environment
    await enqueue(environment, [metric()])
    async def broken(*args, **kwargs):
        raise RuntimeError("private-event-and-credential-canary")
    monkeypatch.setattr(ObservationLedger, "_accept", broken)
    assert await direct_worker.poll_direct_once(db, settings) == 0
    assert await db.guardian_capture_inbox.count_documents({"processed": False}) == 1
    assert await db.guardian_observations.count_documents({}) == 0
    state = await db.guardian_state.find_one({"_id": "guardian_worker_cursor"})
    assert state["read_error_code"] == "capture_processing_failed"
    assert "private-event-and-credential-canary" not in json.dumps(state, default=str) + caplog.text


async def test_lost_lease_cannot_ack_pending_capture(environment, monkeypatch):
    db, settings, _ = environment
    await enqueue(environment, [metric()])
    original = direct_worker._consume
    async def expire(ledger, lease, settings, cutoff, limit):
        await db.guardian_leases.update_one({"_id": ledger.lease_id}, {"$set": {"expires_at": NOW - timedelta(hours=1)}})
        return await original(ledger, lease, settings, cutoff, limit)
    monkeypatch.setattr(direct_worker, "_consume", expire)
    await direct_worker.poll_direct_once(db, settings)
    assert await db.guardian_capture_inbox.count_documents({"processed": False}) == 1
    assert await db.guardian_observations.count_documents({}) == 0


async def test_direct_mode_prevents_langfuse_poll_before_any_source_read(environment, monkeypatch):
    import guardian.worker as worker
    db, _, _ = environment
    monkeypatch.setattr(worker, "db", db)
    class Source:
        def fetch_generations(self, **kwargs):
            pytest.fail("Direct mode must not read Langfuse")
    with pytest.raises(CaptureError):
        await worker.poll_once(Source())
    assert await db.guardian_leases.count_documents({}) == 0


async def test_direct_forever_dispatch_never_constructs_langfuse(environment, monkeypatch):
    import guardian.worker as worker
    db, settings, _ = environment
    monkeypatch.setattr(worker, "db", db)
    monkeypatch.setattr(worker, "LangfuseTraceSource", lambda: pytest.fail("No Langfuse construction in direct mode"))
    calls = []
    async def direct(database):
        calls.append(database)
        raise asyncio.CancelledError()
    monkeypatch.setattr(direct_worker, "poll_direct_once", direct)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()
    assert calls == [db]


async def test_binding_mismatch_refuses_recovery_reads(environment):
    db, settings, _ = environment
    with pytest.raises(Exception):
        await direct_worker.poll_direct_once(db, replace(settings, project_id="another-project"))
    assert await db.guardian_leases.count_documents({}) == 0


async def test_empty_capture_never_creates_test_traffic_or_source_watermark(environment):
    db, settings, _ = environment
    await db.guardian_state.insert_one({"_id": "direct_capture", "last_sequence": 0, "last_test_received_at": NOW})
    await direct_worker.poll_direct_once(db, settings)
    assert await db.guardian_observations.count_documents({}) == 0
    assert await db.guardian_metrics.count_documents({}) == 0
    assert await db.guardian_incidents.count_documents({}) == 0
    progress = await db.guardian_state.find_one({"_id": "direct_processing"})
    assert progress.get("last_processed_at") is None


async def test_new_direct_binding_between_langfuse_preflight_and_lease_blocks_source_write(environment, monkeypatch):
    """Two deployments must not pass independent checks against an empty DB."""
    import guardian.worker as worker
    db, settings, _ = environment
    await db.guardian_state.delete_one({"_id": "capture_binding"})
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    monkeypatch.setattr(worker, "db", db)
    acquire = ObservationLedger.acquire
    async def competing_binding(ledger, owner=None):
        lease = await acquire(ledger, owner)
        # Simulate the other process publishing its binding after our preflight.
        monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "direct")
        try:
            await ensure_direct_binding(db, settings)
        finally:
            monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
        return lease
    monkeypatch.setattr(ObservationLedger, "acquire", competing_binding)
    calls = []
    class Source:
        def fetch_generations(self, since, until=None, limit=500):
            calls.append(True)
            return SourceReadResult(metrics=[], status="complete", window_start=since, window_end=until)
    await worker.poll_once(Source())
    assert calls == []
    assert await db.guardian_observations.count_documents({}) == 0
    assert await db.guardian_metrics.count_documents({}) == 0
    assert await db.guardian_page_receipts.count_documents({}) == 0


async def test_empty_langfuse_claim_blocks_direct_binding_before_any_observations(environment, monkeypatch):
    db, settings, _ = environment
    await db.guardian_state.delete_one({"_id": "capture_binding"})
    ledger = ObservationLedger(db, settings.connection_id)
    lease = await ledger.acquire()
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    try:
        await ledger.claim_langfuse(lease)
        monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "direct")
        with pytest.raises(CaptureError):
            await ensure_direct_binding(db, settings)
        binding = await db.guardian_state.find_one({"_id": "capture_binding"})
        assert binding["mode"] == "langfuse"
        assert binding["fence"] == 1
        assert await db.guardian_observations.count_documents({}) == 0
    finally:
        await ledger.release(lease)


async def test_langfuse_begin_and_commit_each_recheck_mode_inside_transaction(environment):
    db, settings, _ = environment
    ledger = ObservationLedger(db, settings.connection_id)
    lease = await ledger.acquire()
    try:
        with pytest.raises(LedgerError, match="source_mode_reconciliation_required"):
            await ledger.begin_window(lease, NOW - timedelta(hours=1), NOW, "v2")
        window = {"id": "interrupted-window", "api_version": "v2", "start": (NOW-timedelta(hours=1)).isoformat(),
                  "end": NOW.isoformat(), "cursor": None, "page": 0, "restarts": 0, "query_fingerprint": None, "quarantined": 0}
        await db.guardian_state.insert_one({"_id": "guardian_worker_cursor", "active_window": window})
        page = SourcePageResult(rows=[], status="ok", window_start=NOW-timedelta(hours=1), window_end=NOW,
            query_fingerprint="synthetic-query", records_read=0, exhausted=True)
        with pytest.raises(LedgerError, match="source_mode_reconciliation_required"):
            await ledger.commit_page(lease, window, page)
        with pytest.raises(LedgerError, match="source_mode_reconciliation_required"):
            await ledger.restart_window(lease, window)
        assert await db.guardian_page_receipts.count_documents({}) == 0
        current = await db.guardian_state.find_one({"_id": "guardian_worker_cursor"})
        assert current["active_window"]["page"] == current["active_window"]["restarts"] == 0
    finally:
        await ledger.release(lease)
