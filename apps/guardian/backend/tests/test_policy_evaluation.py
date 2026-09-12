"""Policy pinning and partial detector progress against production store flows.

The transaction callback is mocked explicitly by conftest. These checks establish
state/retry semantics; tools/test_mongo_policies.py establishes Mongo ordering and
atomic rollback on an actual replica set.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient
import pytest

from guardian.detectors import cost_anomaly, monitoring_policy, reliability_anomaly
from guardian.ledger import LedgerError, ObservationLedger
from guardian.models import TraceMetric
from guardian.store import MongoIncidentStore
from identity.settings import Member, Settings
from identity.store import IdentityStore
from policies.schema import DEFAULT_RULES
from policies.store import PolicyStore


pytestmark = pytest.mark.anyio
NOW = datetime.now(timezone.utc).replace(microsecond=0)
DETECTORS = [cost_anomaly, reliability_anomaly]


def metric(identifier="candidate", **changes):
    return replace(TraceMetric(trace_id="run", observation_id=identifier, project_id="project",
        agent_name="answer", model="model", cost_usd=1, cost_usd_decimal="1", total_tokens=12,
        latency_ms=100, status="success", timestamp=NOW), **changes)


@pytest.fixture
async def environment():
    db = AsyncMongoMockClient(tz_aware=True)["policy_evaluation"]
    settings = Settings(mode="oidc", issuer="https://issuer.example.invalid", client_id="client",
        organization_id="organization", project_id="project", environment="test", connection_id="primary",
        members={"owner": Member("owner", "owner", "Owner")})
    auth = IdentityStore(db, settings)
    opaque = await auth.create_session({"issuer": settings.issuer, "subject": "owner"})
    principal = await auth.authenticate(opaque)
    ledger = ObservationLedger(db, settings.connection_id)
    lease = await ledger.acquire("test-worker")
    assert lease is not None
    yield db, ledger, lease, PolicyStore(db, settings), principal
    await ledger.release(lease)


async def save(environment, expected=0, **rules):
    return await environment[3].save(environment[4], expected, {**DEFAULT_RULES, **rules})


async def history(environment, count=6):
    db, ledger, lease, _, _ = environment
    observations = [metric("baseline-" + str(i), timestamp=NOW - timedelta(minutes=i + 1)) for i in range(count)]
    await ledger.ingest_metrics(observations, lease)
    # Previously completed history is an input fixture, not pending new work.
    await db.guardian_observations.update_many({}, {"$set": {"pending": False,
        "completed_rules": ["cost_anomaly:1", "reliability_anomaly:1"]}})


async def candidate_row(db):
    return await db.guardian_observations.find_one({"metric.observation_id": "candidate"})


async def test_cold_start_policy_produces_cost_duration_and_error_independently(environment):
    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0.05", max_call_latency_ms=1000)
    await ledger.ingest_metrics([metric(status="error", cost_usd=.050000000001,
        cost_usd_decimal="0.050000000001", latency_ms=1001)], lease)

    assert await ledger.process_pending(lease, DETECTORS) == (3, 0)
    incidents = await db.guardian_incidents.find({}).to_list(10)
    assert {row["evidence"]["reason"] for row in incidents} == {
        "cost_limit_exceeded", "latency_limit_exceeded", "reported_call_error"}
    assert all(row["evidence"]["policy_revision"] == 1 for row in incidents)
    row = await candidate_row(db)
    assert row["pending"] is False
    assert row["monitoring_policy"] == {"revision": 1, "rules": {
        "max_call_cost_usd": "0.05", "max_call_latency_ms": 1000, "alert_on_errors": True}}
    assert await ledger.process_pending(lease, DETECTORS) == (0, 0)


async def test_saved_edit_during_failed_evaluation_keeps_first_snapshot_on_retry(environment, monkeypatch):
    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0.5")
    await ledger.ingest_metrics([metric(status="unknown", latency_ms=None)], lease)
    original = monitoring_policy.evaluate
    calls = []

    def fail_once(detector, baseline, candidate, snapshot, completed, **kwargs):
        if detector.NAME == cost_anomaly.NAME:
            calls.append(snapshot["revision"])
            if len(calls) == 1:
                raise RuntimeError("simulated detector interruption")
        return original(detector, baseline, candidate, snapshot, completed, **kwargs)

    monkeypatch.setattr(monitoring_policy, "evaluate", fail_once)
    assert await ledger.process_pending(lease, DETECTORS) == (0, 1)
    assert (await candidate_row(db))["monitoring_policy"]["revision"] == 1
    await save(environment, expected=1, max_call_cost_usd="100")

    assert await ledger.process_pending(lease, DETECTORS) == (1, 0)
    assert calls == [1, 1]
    incident = await db.guardian_incidents.find_one({})
    assert incident["evidence"]["threshold_value"] == "0.5"
    assert incident["evidence"]["policy_revision"] == 1


async def test_baseline_cap_preserves_immediate_cost_and_defers_only_relative_latency(environment, monkeypatch):
    import guardian.ledger as module

    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0.5")
    await history(environment)
    await ledger.ingest_metrics([metric(latency_ms=900)], lease)
    monkeypatch.setattr(module, "MAX_BASELINE_ROWS", 2)

    assert await ledger.process_pending(lease, DETECTORS) == (1, 1)
    row = await candidate_row(db)
    assert row["pending"] is True
    assert "cost_anomaly:2:policy:1" in row["completed_rules"]
    assert "reliability_anomaly:1:policy:1" not in row["completed_rules"]
    assert await ledger.process_pending(lease, DETECTORS) == (0, 1)
    await save(environment, expected=1, max_call_cost_usd="100", max_call_latency_ms=5000)
    monkeypatch.setattr(module, "MAX_BASELINE_ROWS", 10)

    assert await ledger.process_pending(lease, DETECTORS) == (1, 0)
    assert (await candidate_row(db))["pending"] is False
    evidence = [row["evidence"] for row in await db.guardian_incidents.find({}).to_list(10)]
    assert len(evidence) == 2
    assert {item["policy_kind"] for item in evidence} == {"absolute", "relative"}
    assert {item["policy_revision"] for item in evidence} == {1}


async def test_baseline_read_failure_does_not_suppress_error_or_become_empty_success(environment, monkeypatch):
    db, ledger, lease, _, _ = environment
    await ledger.ingest_metrics([metric(status="error")], lease)
    collection_type = type(db.guardian_observations)
    original = collection_type.find

    def failing_baseline(self, query=None, *args, **kwargs):
        if self.name == "guardian_observations" and query and "metric.timestamp" in query:
            raise RuntimeError("simulated baseline query unavailable")
        return original(self, query, *args, **kwargs)

    monkeypatch.setattr(collection_type, "find", failing_baseline)
    assert await ledger.process_pending(lease, DETECTORS) == (1, 1)
    assert (await candidate_row(db))["pending"] is True
    assert (await db.guardian_incidents.find_one({}))["evidence"]["reason"] == "reported_call_error"
    assert await ledger.process_pending(lease, DETECTORS) == (0, 1)
    monkeypatch.setattr(collection_type, "find", original)
    assert await ledger.process_pending(lease, DETECTORS) == (0, 0)
    assert (await candidate_row(db))["pending"] is False


async def test_partial_legacy_rules_keep_defaults_and_completed_v1_decision(environment):
    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0", alert_on_errors=False)
    await ledger.ingest_metrics([metric(status="error")], lease)
    await db.guardian_observations.update_one({}, {"$set": {"completed_rules": ["cost_anomaly:1"]}})

    assert await ledger.process_pending(lease, DETECTORS) == (1, 0)
    row = await candidate_row(db)
    assert row["monitoring_policy"] == {"revision": 0, "rules": DEFAULT_RULES}
    assert row["pending"] is False
    assert "cost_anomaly:1" in row["completed_rules"]
    evidence = (await db.guardian_incidents.find_one({}))["evidence"]
    assert evidence["reason"] == "reported_call_error" and evidence["policy_revision"] == 0


async def test_policy_save_and_source_replay_never_reopen_completed_resolved_incident(environment):
    db, ledger, lease, _, _ = environment
    candidate = metric(status="error")
    await ledger.ingest_metrics([candidate], lease)
    assert await ledger.process_pending(lease, DETECTORS) == (1, 0)
    incident = await db.guardian_incidents.find_one({})
    await MongoIncidentStore(db).resolve(incident["id"])
    original_row = await candidate_row(db)

    await save(environment, max_call_cost_usd="0", max_call_latency_ms=0)
    await ledger.ingest_metrics([replace(candidate)], lease)
    assert await ledger.process_pending(lease, DETECTORS) == (0, 0)
    row = await candidate_row(db)
    assert row["monitoring_policy"] == original_row["monitoring_policy"]
    assert row["completed_rules"] == original_row["completed_rules"]
    assert await db.guardian_incidents.count_documents({}) == 1
    assert (await db.guardian_incidents.find_one({}))["status"] == "resolved"


async def test_policy_store_failure_does_not_fall_back_to_defaults(environment):
    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0")
    await db.guardian_monitoring_policies.update_one({}, {"$set": {"rules.max_call_cost_usd": "corrupt"}})
    await ledger.ingest_metrics([metric()], lease)

    with pytest.raises(LedgerError, match="invalid_monitoring_policy"):
        await ledger.process_pending(lease, DETECTORS)
    assert "monitoring_policy" not in await candidate_row(db)
    assert (await candidate_row(db))["pending"] is True
    assert await db.guardian_incidents.count_documents({}) == 0


async def test_observation_conflicted_after_pin_cannot_publish_findings(environment, monkeypatch):
    import policies.store as module

    db, ledger, lease, _, _ = environment
    await save(environment, max_call_cost_usd="0")
    await ledger.ingest_metrics([metric()], lease)
    original = module.pin_policy

    async def conflict_after_pin(repository, token, row):
        snapshot = await original(repository, token, row)
        await db.guardian_observations.update_one({"_id": row["_id"]}, {
            "$set": {"state": "conflict", "pending": False}, "$inc": {"version": 1}})
        return snapshot

    monkeypatch.setattr(module, "pin_policy", conflict_after_pin)
    assert await ledger.process_pending(lease, DETECTORS) == (0, 0)
    assert await db.guardian_incidents.count_documents({}) == 0
    assert (await candidate_row(db))["completed_rules"] == []
