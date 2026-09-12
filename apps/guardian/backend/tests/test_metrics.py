"""Hourly rollup aggregation (guardian/metrics.py) against a mocked Mongo backend."""
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.metrics import MongoMetricsStore, hour_bucket, to_public_dict
from guardian.models import TraceMetric

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_db():
    return AsyncMongoMockClient()["guardian_metrics_test_db"]


def _trace(trace_id, cost=0.01, latency=800.0, tokens=500, status="success",
           agent="profile_analyst", at=None):
    return TraceMetric(
        trace_id=trace_id,
        observation_id=trace_id,
        agent_name=agent,
        model="groq/llama-3.3-70b-versatile",
        cost_usd=cost,
        total_tokens=tokens,
        latency_ms=latency,
        status=status,
        timestamp=at or datetime.now(timezone.utc),
    )


def test_hour_bucket_truncates_to_the_hour():
    moment = datetime(2026, 9, 9, 14, 37, 12, tzinfo=timezone.utc)
    assert hour_bucket(moment) == "2026-09-09T14:00:00+00:00"


def test_hour_bucket_assumes_utc_for_naive_timestamps():
    naive = datetime(2026, 9, 9, 14, 37, 12)
    assert hour_bucket(naive) == "2026-09-09T14:00:00+00:00"


def test_to_public_dict_computes_average_latency():
    doc = {"hour": "h", "agent_name": "a", "call_count": 4, "sum_latency_ms": 4000.0,
           "latency_known_count": 4, "latency_unknown_count": 0}
    assert to_public_dict(doc)["avg_latency_ms"] == 1000.0


def test_to_public_dict_handles_zero_calls_without_dividing_by_zero():
    doc = {"hour": "h", "agent_name": "a", "call_count": 0, "sum_latency_ms": 0.0}
    assert to_public_dict(doc)["avg_latency_ms"] is None


async def test_record_aggregates_calls_in_the_same_hour(mock_db):
    store = MongoMetricsStore(mock_db)
    at = datetime(2026, 9, 9, 14, 5, tzinfo=timezone.utc)

    await store.record([
        _trace("t1", cost=0.01, latency=800.0, tokens=100, at=at),
        _trace("t2", cost=0.02, latency=1200.0, tokens=200, at=at.replace(minute=50)),
    ])

    rollups = await store.since(at - timedelta(hours=1))

    assert len(rollups) == 1
    rollup = rollups[0]
    assert rollup["call_count"] == 2
    assert rollup["total_cost_usd"] == 0.03
    assert rollup["total_tokens"] == 300
    assert rollup["avg_latency_ms"] == 1000.0
    assert rollup["error_count"] == 0


async def test_record_separates_different_agents(mock_db):
    store = MongoMetricsStore(mock_db)
    at = datetime(2026, 9, 9, 14, 5, tzinfo=timezone.utc)

    await store.record([
        _trace("t1", agent="profile_analyst", at=at),
        _trace("t2", agent="market_hunter", at=at),
    ])

    rollups = await store.since(at - timedelta(hours=1))

    assert len(rollups) == 2
    assert {r["agent_name"] for r in rollups} == {"profile_analyst", "market_hunter"}


async def test_record_separates_different_hours(mock_db):
    store = MongoMetricsStore(mock_db)
    first = datetime(2026, 9, 9, 14, 5, tzinfo=timezone.utc)

    await store.record([_trace("t1", at=first), _trace("t2", at=first + timedelta(hours=1))])

    rollups = await store.since(first - timedelta(hours=1))

    assert len(rollups) == 2
    assert rollups[0]["hour"] < rollups[1]["hour"]  # oldest first


async def test_record_counts_errors(mock_db):
    store = MongoMetricsStore(mock_db)
    at = datetime(2026, 9, 9, 14, 5, tzinfo=timezone.utc)

    await store.record([
        _trace("t1", status="success", at=at),
        _trace("t2", status="error", at=at),
        _trace("t3", status="error", at=at),
    ])

    rollup = (await store.since(at - timedelta(hours=1)))[0]

    assert rollup["call_count"] == 3
    assert rollup["error_count"] == 2


async def test_since_excludes_older_buckets(mock_db):
    store = MongoMetricsStore(mock_db)
    now = datetime(2026, 9, 9, 14, 5, tzinfo=timezone.utc)

    await store.record([
        _trace("old", at=now - timedelta(hours=10)),
        _trace("new", at=now),
    ])

    rollups = await store.since(now - timedelta(hours=2))

    assert len(rollups) == 1
    assert rollups[0]["hour"] == hour_bucket(now)
