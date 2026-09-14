"""Bounded Mongo-backed direct views, with no source credentials or raw content."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest
from mongomock_motor import AsyncMongoMockClient

from capture.settings import ensure_direct_binding
from guardian import direct_traces
from guardian.direct_traces import DirectTraceReader
from guardian.ledger import ObservationLedger, safe_metric
from guardian.models import TraceMetric
from guardian.traces import LiveReadError
from identity.settings import Settings
from identity.store import IdentityStore

pytestmark = pytest.mark.anyio
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
async def environment(monkeypatch):
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "direct")
    database = AsyncMongoMockClient(tz_aware=True)["direct_live_tests"]
    settings = Settings(mode="oidc", organization_id="organization", project_id="project", environment="test",
                        connection_id="primary", issuer="https://issuer.example.invalid", client_id="test-client")
    await IdentityStore(database, settings).ensure_binding()
    await ensure_direct_binding(database, settings)
    return database, settings, DirectTraceReader(database, settings)


async def insert(database, identifier="call-one", **changes):
    metric = TraceMetric(trace_id="trace-one", observation_id=identifier, source="guardian_direct", project_id="project",
        environment="test", agent_name="answer-agent", model="test-model", cost_usd=.01, cost_usd_decimal="0.01",
        total_tokens=12, input_tokens=10, output_tokens=2, latency_ms=100, status="success",
        timestamp=NOW - timedelta(minutes=1), ended_at=NOW - timedelta(minutes=1) + timedelta(milliseconds=100),
        completion_state="completed")
    state = changes.pop("state", "accepted")
    connection_id = changes.pop("connection_id", "primary")
    metric = replace(metric, **changes)
    await database.guardian_observations.insert_one({"_id": identifier, "connection_id": connection_id,
        "metric": safe_metric(metric), "state": state, "pending": False})


async def test_live_uses_numeric_ledger_without_vendor_or_content_fields(environment):
    db, _, reader = environment
    await insert(db)
    snapshot = await reader.snapshot()
    assert snapshot["source_kind"] == "guardian_direct"
    assert snapshot["source_api"] == "direct-v1"
    assert snapshot["coverage"]["scope"] == "captured_terminal_events"
    assert snapshot["coverage"]["status"] == "complete"
    assert snapshot["stats"]["total_cost_usd"] == .01
    assert snapshot["stats"]["total_tokens"] == 12
    assert snapshot["calls"][0]["output_preview"] == ""
    assert snapshot["calls"][0]["status_message"] is None
    assert snapshot["runs"][0]["langfuse_url"] is None
    assert snapshot["runs"][0]["workflow_status"] == "unknown"
    run = await reader.run_detail("trace-one")
    assert run["observation_state"] == "observed"
    assert run["source_kind"] == "guardian_direct"
    assert run["calls"][0]["id"] == "call-one"


async def test_parent_references_survive_direct_views_without_counting_uncollected_parents(environment):
    db, _, reader = environment
    parent = "00000000000000a1"
    await insert(db, "00000000000000b1", parent_observation_id=parent)
    await insert(db, "00000000000000b2", parent_observation_id=parent)
    snapshot = await reader.snapshot()
    assert snapshot["stats"]["call_count"] == 2
    assert snapshot["stats"]["total_tokens"] == 24
    assert len(snapshot["runs"]) == 1
    assert {call["parent_observation_id"] for call in snapshot["calls"]} == {parent}
    run = await reader.run_detail("trace-one")
    assert run["call_count"] == 2
    assert {call["id"] for call in run["calls"]} == {"00000000000000b1", "00000000000000b2"}
    assert {call["parent_observation_id"] for call in run["calls"]} == {parent}
    assert run["workflow_status"] == "unknown" and run["latency_ms"] is None


async def test_direct_root_does_not_get_a_synthetic_parent(environment):
    db, _, reader = environment
    await insert(db)
    assert (await reader.snapshot())["calls"][0]["parent_observation_id"] is None
    assert (await reader.run_detail("trace-one"))["calls"][0]["parent_observation_id"] is None


async def test_missing_and_conflicted_measurements_remain_unknown(environment):
    db, _, reader = environment
    await insert(db, "known-zero", cost_usd=0, cost_usd_decimal="0", total_tokens=0)
    await insert(db, "unknown", cost_usd=None, cost_usd_decimal=None, total_tokens=None, latency_ms=None)
    await insert(db, "conflict", state="conflicted", cost_usd=100, cost_usd_decimal="100")
    snapshot = await reader.snapshot()
    assert snapshot["coverage"]["status"] == "partial"
    assert snapshot["coverage"]["reason"] == "conflicted_observations"
    assert snapshot["stats"]["call_count"] == 3
    assert snapshot["stats"]["total_cost_usd"] is None
    assert snapshot["stats"]["known_cost_usd"] == 0
    assert snapshot["stats"]["cost_known_count"] == 1
    assert snapshot["stats"]["cost_unknown_count"] == 2
    conflict = next(c for c in snapshot["calls"] if c["id"] == "conflict")
    for key in ("cost_usd", "cost_usd_decimal", "total_tokens", "input_tokens", "output_tokens", "latency_ms"):
        assert conflict[key] is None
    assert conflict["status"] == "unknown"


async def test_no_traffic_with_pending_receipt_is_partial_and_run_undetermined(environment):
    db, _, reader = environment
    await db.guardian_capture_inbox.insert_one({"_id": "queued", "connection_id": "primary", "processed": False})
    snapshot = await reader.snapshot()
    assert snapshot["coverage"]["status"] == "partial"
    assert snapshot["coverage"]["reason"] == "capture_pending"
    assert snapshot["coverage"]["pending_events"] == 1
    assert snapshot["calls"] == []
    run = await reader.run_detail("waiting-run")
    assert run["observation_state"] == "undetermined"
    assert run["total_cost_usd"] is None


async def test_empty_complete_capture_window_does_not_assert_workflow_health(environment):
    _, _, reader = environment
    run = await reader.run_detail("unobserved-run")
    assert run["coverage"]["status"] == "complete"
    assert run["observation_state"] == "not_observed"
    assert run["workflow_status"] == "unknown"
    assert run["cost_usd"] is None
    assert run["known_cost_usd"] is None


async def test_feed_limit_does_not_limit_headlines_and_window_cap_is_explicit(environment):
    db, _, reader = environment
    sample = TraceMetric(trace_id="large-run", observation_id="unused", source="guardian_direct", project_id="project",
        environment="test", agent_name="agent", model="model", cost_usd=1, total_tokens=2,
        latency_ms=10, status="success", timestamp=NOW - timedelta(minutes=1))
    await db.guardian_observations.insert_many([{"_id": str(i), "connection_id": "primary",
        "metric": safe_metric(replace(sample, observation_id=str(i))), "state": "accepted", "pending": False} for i in range(1001)])
    snapshot = await reader.snapshot(call_limit=2)
    assert len(snapshot["calls"]) == 2
    assert snapshot["stats"]["call_count"] == 1000
    assert snapshot["stats"]["known_cost_usd"] == 1000
    assert snapshot["coverage"]["truncated"] is True
    assert snapshot["coverage"]["reason"] == "limit_reached"
    assert snapshot["feed"] == {"returned": 2, "limit": 2, "limited": True}
    run = await reader.run_detail("large-run")
    assert len(run["calls"]) == 1000
    assert run["coverage"]["status"] == "partial"


async def test_scope_and_window_filters_prevent_foreign_or_future_rows(environment):
    db, _, reader = environment
    await insert(db, "visible")
    await insert(db, "foreign-project", project_id="foreign")
    await insert(db, "foreign-source", source="langfuse")
    await insert(db, "foreign-connection", connection_id="foreign")
    await insert(db, "foreign-environment", environment="foreign")
    await insert(db, "old", timestamp=NOW - timedelta(hours=25))
    await insert(db, "future", timestamp=NOW + timedelta(hours=1))
    await insert(db, "other-trace", trace_id="trace-two")
    assert (await reader.snapshot())["stats"]["call_count"] == 2
    run = await reader.run_detail("trace-one", hours=24)
    assert [c["id"] for c in run["calls"]] == ["visible"]


async def test_processing_backlog_keeps_coverage_partial(environment):
    db, _, reader = environment
    await insert(db)
    await db.guardian_observations.update_one({}, {"$set": {"pending": True}})
    result = await reader.snapshot()
    assert result["coverage"]["reason"] == "processing_pending"
    assert result["coverage"]["pending_observations"] == 1


async def test_stored_content_fields_never_enter_direct_live_projection(environment):
    db, _, reader = environment
    await insert(db)
    private = "private-content-from-corrupt-or-future-writer"
    await db.guardian_observations.update_one({}, {"$set": {"metric." + field: private for field in
        ("output_text", "status_message", "trace_name", "user_id", "session_id")}})
    snapshot = await reader.snapshot()
    run = await reader.run_detail("trace-one")
    assert private not in json.dumps(snapshot) + json.dumps(run)
    assert snapshot["calls"][0]["output_preview"] == ""
    assert snapshot["calls"][0]["status_message"] is None
    assert run["user_id"] is None and run["session_id"] is None


async def test_changed_binding_and_database_failure_return_safe_unavailable(environment, monkeypatch):
    db, settings, reader = environment
    with pytest.raises(LiveReadError, match="^capture_read_unavailable$"):
        await DirectTraceReader(db, replace(settings, project_id="wrong")).snapshot()
    async def broken(*args, **kwargs):
        raise RuntimeError("private-source-or-credential-canary")
    monkeypatch.setattr(ObservationLedger, "transaction", broken)
    with pytest.raises(LiveReadError) as error:
        await reader.snapshot()
    assert "private-source-or-credential-canary" not in str(error.value)


async def test_read_timeout_is_bounded_and_not_converted_to_empty_data(environment, monkeypatch):
    _, _, reader = environment
    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(reader, "_read", slow)
    monkeypatch.setattr(direct_traces, "READ_TIMEOUT_SECONDS", .01)
    with pytest.raises(LiveReadError):
        await reader.snapshot()
    assert cancelled == [True]


@pytest.mark.parametrize("kwargs", [{"hours": 0}, {"hours": True}, {"hours": 169}, {"run_limit": 101}, {"call_limit": 0}])
async def test_direct_caller_bounds(environment, kwargs):
    _, _, reader = environment
    with pytest.raises(ValueError):
        await reader.snapshot(**kwargs)
