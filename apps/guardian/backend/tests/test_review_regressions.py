"""Executable acceptance cases for the seven 2026-09-11 review probes.

All seven original cases now pass, including late arrivals within the replay
window, replay accounting, distinct-agent evidence and the explicit zero-cost
history transition. The original customer-visible assertions remain intact.

The SDK and Mongo are isolated fakes. These tests exercise production adapters,
worker orchestration, stores and ASGI routing, but do not prove real Mongo
atomicity, SDK compatibility, an external HTTP boundary or a browser journey.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from guardian.detectors import cost_anomaly, reliability_anomaly
from guardian.incident_engine import process_detector_results
from guardian.langfuse_client import LangfuseTraceSource
from guardian.metrics import MongoMetricsStore
from guardian.store import MongoIncidentStore
from guardian.traces import LiveTraceReader


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _observation(observation_id="generation-1", **overrides):
    observation = {
        "id": observation_id,
        "trace_id": "workflow-1",
        "name": "answer-generator",
        "model": "test-model",
        "start_time": NOW - timedelta(minutes=1),
        "calculated_total_cost": 2.0,
        "usage": {"input": 12, "output": 8, "total": 20},
        "latency": 0.5,
        "level": "DEFAULT",
    }
    observation.update(overrides)
    return observation


class _PaginatedSDK:
    """Deterministic response fixture using the current SDK's public read methods.

    The source can become unavailable or expose an observation after its start
    time. Unlike the old pagination fixture, successive pages contain distinct
    rows and metadata describes the entire matching window.
    """

    def __init__(self, observations=(), error=None):
        self.observations = list(observations)
        self.error = error
        self.calls = []

    def fetch_observations(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        since = kwargs.get("from_start_time")
        matching = [
            row for row in self.observations
            if since is None or row["start_time"] >= since
        ]
        limit, page = kwargs.get("limit", 100), kwargs.get("page", 1)
        offset = (page - 1) * limit
        return SimpleNamespace(
            data=matching[offset:offset + limit],
            meta=SimpleNamespace(
                page=page,
                limit=limit,
                total_items=len(matching),
                total_pages=(len(matching) + limit - 1) // limit,
            ),
        )

    def fetch_traces(self, **kwargs):
        return SimpleNamespace(data=[])


def _source(sdk):
    # Avoid constructing a real SDK client, regardless of the operator's .env.
    source = LangfuseTraceSource.__new__(LangfuseTraceSource)
    source._api_version = "v1"
    source._client = sdk
    return source


@pytest.fixture
def database():
    return AsyncMongoMockClient()["guardian_review_regressions"]


@pytest.fixture
def worker(monkeypatch, database):
    import guardian.worker as worker_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(worker_module, "db", database)
    monkeypatch.setattr(worker_module, "datetime", Clock)
    return worker_module


@pytest.fixture
def live_api(monkeypatch, database):
    import api.routes as routes
    import auth
    from server import app

    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", "review-test-key")
    monkeypatch.setattr(routes, "db", database)

    def get_snapshot(sdk, **params):
        monkeypatch.setattr(routes, "_live", LiveTraceReader(_source(sdk)))
        # In-process ASGI; no server, credentials or network are involved.
        with TestClient(app) as client:
            response = client.get(
                "/api/guardian/live",
                params=params,
                headers={"X-Guardian-Key": "review-test-key"},
            )
        response.raise_for_status()
        return response.json()

    return get_snapshot


@pytest.mark.anyio
async def test_source_failure_preserves_last_successful_checkpoint(worker, database):
    previous = NOW - timedelta(minutes=2)
    await worker._save_cursor(previous)
    source = _source(_PaginatedSDK(error=ConnectionError("synthetic source outage")))

    await worker.poll_once(source)

    cursor = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert cursor["last_polled_at"] == previous.isoformat()


@pytest.mark.anyio
async def test_late_arrival_is_accounted_for_on_a_subsequent_poll(worker, database):
    await worker._save_cursor(NOW - timedelta(minutes=2))
    sdk = _PaginatedSDK()
    source = _source(sdk)
    await worker.poll_once(source)

    # It started before the last successful poll, but only now became visible.
    sdk.observations.append(_observation())
    await worker.poll_once(source)

    rollups = await MongoMetricsStore(database).since(NOW - timedelta(hours=1))
    assert sum(row["call_count"] for row in rollups) == 1
    assert sum(row["total_cost_usd"] for row in rollups) == pytest.approx(2.0)


@pytest.mark.anyio
async def test_replaying_one_source_observation_counts_its_spend_once(database):
    source = _source(_PaginatedSDK([_observation()]))
    store = MongoMetricsStore(database)

    # Separate adapter reads model replay after restart. The raw fixture has a
    # stable observation ID; this asserts no speculative new TraceMetric field.
    for _ in range(2):
        await store.record(source.fetch_recent_generations(NOW - timedelta(hours=1)))

    rollups = await store.since(NOW - timedelta(hours=1))
    assert sum(row["call_count"] for row in rollups) == 1
    assert sum(row["total_cost_usd"] for row in rollups) == pytest.approx(2.0)


@pytest.mark.anyio
async def test_distinct_agent_failures_in_one_workflow_retain_both_agents(database):
    agents = ["planning-agent", "retrieval-agent"]
    source = _source(_PaginatedSDK([
        _observation(f"generation-{index}", name=agent, level="ERROR")
        for index, agent in enumerate(agents)
    ]))
    candidates = source.fetch_recent_generations(NOW - timedelta(hours=1))
    results = reliability_anomaly.evaluate([], candidates)
    store = MongoIncidentStore(database)

    await process_detector_results(results, store)

    # ADR-06 permits distinct incidents or grouped evidence. Require that both
    # agents remain visible, without fixing the future grouping schema/count.
    retained = json.dumps([incident.model_dump(mode="json") for incident in await store.list_open()])
    assert all(agent in retained for agent in agents)


def test_live_api_falls_back_to_populated_usage_when_details_are_empty(live_api):
    body = live_api(_PaginatedSDK([_observation(usageDetails={})]))

    assert body["stats"]["total_tokens"] == 20
    call = body["calls"][0]
    assert (call["input_tokens"], call["output_tokens"], call["total_tokens"]) == (12, 8, 20)


def test_live_window_totals_cover_all_rows_independent_of_visible_feed_limit(live_api):
    sdk = _PaginatedSDK([_observation(f"generation-{i}") for i in range(250)])

    body = live_api(sdk, hours=24, calls=60)

    # All rows in this fixture are available. Assert the existing totals contract,
    # not an invented partial-status schema. R1-03 must also test partial/unknown
    # presentation once its completeness contract has been implemented.
    assert body["stats"]["call_count"] == 250
    assert body["stats"]["total_cost_usd"] == pytest.approx(500.0)
    assert body["stats"]["total_tokens"] == 5000
    assert len(body["calls"]) == 60


def test_cost_policy_recognizes_material_spend_after_explicitly_free_baseline():
    # Explicit reported zeros avoid treating unknown prices as free. This is a
    # policy acceptance example. R3-02 now defines the bare known-zero baseline
    # transition floor as $0.01; this original $2 assertion is unchanged.
    source = _source(_PaginatedSDK([
        _observation(f"baseline-{i}", calculated_total_cost=0.0)
        for i in range(6)
    ] + [_observation("paid-generation", calculated_total_cost=2.0)]))
    metrics = source.fetch_recent_generations(NOW - timedelta(hours=1))

    results = cost_anomaly.evaluate(metrics[:6], metrics[6:])

    assert any(result.triggered for result in results)


def test_regression_fixture_and_adapter_return_distinct_rows_across_pages():
    """Passing control: later pages exist and contain independent observations."""
    sdk = _PaginatedSDK([
        _observation(f"generation-{i}", trace_id=f"workflow-{i}")
        for i in range(250)
    ])

    metrics = _source(sdk).fetch_recent_generations(NOW - timedelta(hours=1), limit=500)

    assert {metric.trace_id for metric in metrics} == {f"workflow-{i}" for i in range(250)}
    assert [call["page"] for call in sdk.calls] == [1, 2, 3]


@pytest.mark.anyio
async def test_newly_visible_observation_is_accounted_for_after_earlier_checkpoint(worker, database):
    """Passing control for the same fixture/worker path as the late-arrival gap."""
    await worker._save_cursor(NOW - timedelta(minutes=2))

    await worker.poll_once(_source(_PaginatedSDK([_observation()])))

    rollups = await MongoMetricsStore(database).since(NOW - timedelta(hours=1))
    assert sum(row["call_count"] for row in rollups) == 1
    assert sum(row["total_cost_usd"] for row in rollups) == pytest.approx(2.0)


def test_live_api_returns_complete_small_window_with_split_token_usage(live_api):
    """Passing control for auth, routing, serialization and the usage fixture."""
    body = live_api(_PaginatedSDK([_observation()]))

    assert body["available"] is True
    assert body["degraded"] is False
    assert body["stats"]["call_count"] == 1
    assert body["stats"]["total_tokens"] == 20
    assert body["stats"]["total_cost_usd"] == pytest.approx(2.0)
