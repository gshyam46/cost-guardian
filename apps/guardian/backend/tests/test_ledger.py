"""Ledger semantic tests with an explicitly mocked transaction boundary.

conftest supplies the mock transaction override. These tests exercise durable
record shapes and replay/recovery decisions but cannot establish Mongo atomicity,
write conflicts, ambiguous commit handling, replica-set durability or failover.
"""

import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.detectors import pii, reliability_anomaly
from guardian.ledger import LEDGER_VERSION, LedgerError, ObservationLedger, identity
from guardian.metrics import MongoMetricsStore
from guardian.models import SourcePageResult, SourceRowDisposition, TraceMetric


NOW = datetime.now(timezone.utc)
PRIVATE = "private-content-must-never-enter-ledger"


def metric(identifier="generation-1", **changes):
    value = TraceMetric(
        trace_id="workflow-1", observation_id=identifier, project_id="project-1",
        agent_name="answer-agent", model="test-model", cost_usd=0.75,
        total_tokens=20, latency_ms=500, status="success", timestamp=NOW,
    )
    return replace(value, **changes)


@pytest.fixture
def database():
    return AsyncMongoMockClient()["guardian_ledger_semantics"]


@pytest.fixture
async def ledger(database):
    value = ObservationLedger(database, "test-connection")
    lease = await value.acquire("first-owner")
    assert lease is not None
    yield value, lease
    await value.release(lease)


async def rollups(database):
    return await MongoMetricsStore(database).since(NOW - timedelta(hours=2))


@pytest.mark.anyio
async def test_ledger_retains_only_allowlisted_metrics_and_safe_pii_categories(ledger, database):
    repository, lease = ledger
    candidate = metric(
        output_text=PRIVATE + " contact private-canary@example.com",
        status_message=PRIVATE, user_id=PRIVATE, session_id=PRIVATE,
        trace_tags=(PRIVATE,), trace_name=PRIVATE,
    )
    prepared = {identity(candidate, repository.connection_id): [asdict(item) for item in pii.evaluate([], [candidate])]}

    await repository.ingest_metrics([candidate], lease, prepared)

    row = await database.guardian_observations.find_one({})
    persisted = json.dumps(row, default=str)
    assert PRIVATE not in persisted
    assert "private-canary@example.com" not in persisted
    assert not ({"output_text", "status_message", "user_id", "session_id", "trace_tags", "trace_name"} & row["metric"].keys())
    assert row["metric"]["cost_usd_decimal"] == "0.75"
    assert row["pii_results"][0]["evidence"] == {"pii_types": ["email"]}


@pytest.mark.anyio
async def test_duplicate_identity_rebuilds_one_contribution_across_store_instances(ledger, database):
    repository, lease = ledger
    candidate = metric()
    await repository.ingest_metrics([candidate], lease)
    await repository.rebuild(lease)

    restarted = ObservationLedger(database, repository.connection_id)
    await restarted.ingest_metrics([replace(candidate)], lease)
    await restarted.rebuild(lease)

    assert await database.guardian_observations.count_documents({}) == 1
    rows = await rollups(database)
    assert len(rows) == 1
    assert rows[0]["call_count"] == 1
    assert rows[0]["total_cost_usd"] == pytest.approx(0.75)
    assert rows[0]["total_tokens"] == 20
    assert rows[0]["accounting_status"] == LEDGER_VERSION
    assert await database.guardian_dirty_buckets.count_documents({}) == 0


@pytest.mark.anyio
async def test_conflicting_copy_invalidates_previously_trusted_measurements(ledger, database):
    repository, lease = ledger
    accepted = metric()
    await repository.ingest_metrics([accepted], lease)
    await repository.rebuild(lease)
    assert (await rollups(database))[0]["total_cost_usd"] == pytest.approx(0.75)

    await repository.ingest_metrics([replace(accepted, cost_usd=9)], lease)
    await repository.rebuild(lease)

    row = (await rollups(database))[0]
    assert row["call_count"] == 1
    assert row["conflict_count"] == 1
    assert row["total_cost_usd"] is None
    assert row["total_tokens"] is None
    assert row["avg_latency_ms"] is None
    assert (row["cost_known_count"], row["cost_unknown_count"]) == (0, 1)
    assert await database.guardian_quarantine.count_documents({}) == 1
    # Replaying the original must not silently restore trust after conflict.
    await repository.ingest_metrics([accepted], lease)
    await repository.rebuild(lease)
    assert (await rollups(database))[0]["total_cost_usd"] is None


@pytest.mark.anyio
async def test_conflicting_attribution_invalidates_both_affected_buckets(ledger, database):
    repository, lease = ledger
    accepted = metric()
    await repository.ingest_metrics([accepted], lease)
    await repository.rebuild(lease)

    changed = replace(accepted, agent_name="different-agent", timestamp=NOW - timedelta(hours=1))
    await repository.ingest_metrics([changed], lease)
    await repository.rebuild(lease)

    rows = await rollups(database)
    assert {row["agent_name"] for row in rows} == {"answer-agent", "different-agent"}
    assert all(row["conflict_count"] == 1 and row["total_cost_usd"] is None for row in rows)
    assert sum(row["call_count"] for row in rows) == 1


@pytest.mark.anyio
async def test_work_survives_an_interruption_after_ingestion_and_replays_once(ledger, database, monkeypatch):
    import guardian.ledger as module

    repository, lease = ledger
    await repository.ingest_metrics([metric(status="error")], lease)
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_incidents.count_documents({}) == 0
    assert (await repository.backlog())["pending_observations"] == 1
    assert (await repository.backlog())["dirty_buckets"] == 1

    # Simulate owner expiry after the ingestion commit, without pretending that
    # this mock can reproduce an interruption within a Mongo transaction.
    monkeypatch.setattr(module, "utcnow", lambda: NOW + timedelta(minutes=10))
    restarted = ObservationLedger(database, repository.connection_id)
    second_lease = await restarted.acquire("replacement-owner")
    assert second_lease is not None
    try:
        await restarted.rebuild(second_lease)
        created, failures = await restarted.process_pending(second_lease, [reliability_anomaly])
        assert (created, failures) == (1, 0)
        assert await restarted.process_pending(second_lease, [reliability_anomaly]) == (0, 0)
    finally:
        await restarted.release(second_lease)

    assert (await rollups(database))[0]["call_count"] == 1
    assert await database.guardian_incidents.count_documents({}) == 1
    assert (await repository.backlog())["pending_observations"] == 0
    assert (await repository.backlog())["dirty_buckets"] == 0


@pytest.mark.anyio
async def test_failed_rule_remains_pending_while_completed_rules_do_not_duplicate(ledger, database):
    class RecoveringRule:
        NAME = "recovering_rule"
        RULE_VERSION = "7"
        attempts = 0

        @classmethod
        def evaluate(cls, baseline, candidates):
            cls.attempts += 1
            if cls.attempts == 1:
                raise RuntimeError("synthetic detector failure")
            return [replace(finding, detector=cls.NAME, rule_version=cls.RULE_VERSION)
                    for finding in reliability_anomaly.evaluate(baseline, candidates)]

    repository, lease = ledger
    await repository.ingest_metrics([metric(status="error")], lease)
    assert await repository.process_pending(lease, [reliability_anomaly, RecoveringRule]) == (1, 1)
    row = await database.guardian_observations.find_one({})
    assert row["pending"] is True
    assert "reliability_anomaly:1" in row["completed_rules"]
    assert "recovering_rule:7" not in row["completed_rules"]

    assert await repository.process_pending(lease, [reliability_anomaly, RecoveringRule]) == (1, 0)
    row = await database.guardian_observations.find_one({})
    assert row["pending"] is False
    assert "recovering_rule:7" in row["completed_rules"]
    assert await database.guardian_incidents.count_documents({}) == 2


@pytest.mark.anyio
async def test_legacy_rollups_block_ledger_writes_without_overwriting_history(ledger, database):
    repository, lease = ledger
    legacy = {"_id": "legacy-rollup", "hour": "2026-09-01T00:00:00+00:00", "call_count": 9, "total_cost_usd": 12}
    await database.guardian_metrics.insert_one(dict(legacy))

    with pytest.raises(LedgerError, match="legacy_metrics_migration_required"):
        await repository.ingest_metrics([metric()], lease)

    assert await database.guardian_metrics.find_one({"_id": legacy["_id"]}) == legacy
    assert await database.guardian_observations.count_documents({}) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("identifier", [None, "", "   "])
async def test_missing_observation_identity_is_rejected_before_any_ingestion(ledger, database, identifier):
    repository, lease = ledger

    with pytest.raises(LedgerError, match="observation_identity"):
        await repository.ingest_metrics([metric("valid"), metric(identifier)], lease)

    assert await database.guardian_observations.count_documents({}) == 0
    assert await database.guardian_dirty_buckets.count_documents({}) == 0


@pytest.mark.anyio
async def test_new_connection_cannot_silently_mix_with_existing_ledger(ledger, database):
    repository, lease = ledger
    await repository.ingest_metrics([metric()], lease)
    other = ObservationLedger(database, "different-connection")
    other_lease = await other.acquire("other-owner")
    try:
        with pytest.raises(LedgerError, match="connection_cutover_required"):
            await other.ingest_metrics([metric("other")], other_lease)
    finally:
        await other.release(other_lease)
    assert await database.guardian_observations.count_documents({}) == 1


@pytest.mark.anyio
async def test_terminal_page_accounts_for_quarantine_and_durable_continuation(ledger, database):
    repository, lease = ledger
    window = await repository.begin_window(lease, NOW - timedelta(hours=1), NOW + timedelta(minutes=1), "v2")
    page = SourcePageResult(
        rows=[
            SourceRowDisposition(0, "accepted", "accepted-fingerprint", metric=metric()),
            SourceRowDisposition(1, "quarantined", "invalid-row-fingerprint", issues=("missing_observation_id",)),
        ],
        status="ok", window_start=NOW - timedelta(hours=1), window_end=NOW + timedelta(minutes=1),
        query_fingerprint="fixed-query", exhausted=True, records_read=2,
    )

    await repository.commit_page(lease, window, page)

    state = await database.guardian_state.find_one({"_id": "guardian_worker_cursor"})
    assert state["active_window"] is None
    assert state["source_watermark"] == (NOW + timedelta(minutes=1)).isoformat()
    assert state["last_window_quarantined"] == 1
    assert await database.guardian_observations.count_documents({}) == 1
    assert await database.guardian_quarantine.count_documents({}) == 1
    assert (await repository.backlog())["pending_observations"] == 1


@pytest.mark.anyio
async def test_rejected_page_does_not_advance_active_window_or_source_watermark(ledger, database):
    repository, lease = ledger
    window = await repository.begin_window(lease, NOW - timedelta(hours=1), NOW, "v2")
    before = await database.guardian_state.find_one({"_id": "guardian_worker_cursor"})
    page = SourcePageResult(rows=[], status="failed", error_code="invalid_response")

    with pytest.raises(LedgerError, match="uncommittable_source_page"):
        await repository.commit_page(lease, window, page)

    assert await database.guardian_state.find_one({"_id": "guardian_worker_cursor"}) == before
    assert await database.guardian_page_receipts.count_documents({}) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_first", [True, False])
async def test_known_identity_quarantine_invalidates_trust_regardless_of_arrival_order(
    ledger, database, invalid_first
):
    repository, lease = ledger
    candidate = metric()
    valid = SourceRowDisposition(
        0, "accepted", "valid-copy", metric=candidate,
        observation_id=candidate.observation_id, trace_id=candidate.trace_id,
        source_project_id=candidate.project_id,
    )
    invalid = SourceRowDisposition(
        1, "quarantined", "invalid-copy", observation_id=candidate.observation_id,
        trace_id=candidate.trace_id, source_project_id=candidate.project_id,
        issues=("invalid_start_time",),
    )
    rows = [invalid, valid] if invalid_first else [valid, invalid]
    for ordinal, row in enumerate(rows):
        row.ordinal = ordinal
    end = NOW + timedelta(minutes=1)
    window = await repository.begin_window(lease, NOW - timedelta(hours=1), end, "v2")
    page = SourcePageResult(
        rows=rows, status="ok", window_start=NOW - timedelta(hours=1),
        window_end=end, query_fingerprint="fixed-query", exhausted=True, records_read=2,
    )

    await repository.commit_page(lease, window, page)
    await repository.rebuild(lease)

    row = (await rollups(database))[0]
    assert row["call_count"] == 1
    assert row["conflict_count"] == 1
    assert row["total_cost_usd"] is None
    assert (row["cost_known_count"], row["cost_unknown_count"]) == (0, 1)
