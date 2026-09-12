"""Authenticated monitoring and request boundaries, without live services."""
import asyncio
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient


HEADERS = {"X-Guardian-Key": "monitoring-test-key"}


@pytest.fixture
def environment(monkeypatch):
    import api.routes as routes
    import auth
    from server import app

    database = AsyncMongoMockClient()["guardian_monitoring_test"]
    monkeypatch.setattr(routes, "db", database)
    monkeypatch.setattr(routes, "_trace_source", SimpleNamespace(available=True))
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", HEADERS["X-Guardian-Key"])
    return app, routes, database


def test_monitoring_requires_guardian_auth(environment):
    app, _, _ = environment
    with TestClient(app) as client:
        assert client.get("/api/guardian/monitoring").status_code == 401


def test_no_poll_is_not_healthy_monitoring(environment):
    app, _, _ = environment
    with TestClient(app) as client:
        response = client.get("/api/guardian/monitoring", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_polled"
    assert body["healthy"] is False
    assert body["last_successful_checkpoint"] is None


@pytest.mark.anyio
async def test_worker_using_other_api_version_does_not_claim_current_health(environment):
    app, routes, database = environment
    routes._trace_source.api_version = "v2"
    await database.guardian_state.insert_one({
        "_id": "guardian_worker_cursor", "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "processing_status": "complete", "read_status": "complete", "source_api_version": "v1",
    })
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/guardian/monitoring", headers=HEADERS)
    body = response.json()
    assert body["status"] == "source_configuration_changed"
    assert body["healthy"] is False
    assert body["source_api_version"] == "v2"
    assert body["worker_source_api_version"] == "v1"


@pytest.mark.anyio
@pytest.mark.parametrize("condition", ["recent_success", "stopped_worker", "partial_source", "no_source"])
async def test_worker_health_distinguishes_progress_from_api_liveness(environment, condition):
    app, routes, database = environment
    now = datetime.now(timezone.utc)
    stamp = now - timedelta(hours=1) if condition == "stopped_worker" else now
    checkpoint = (now - timedelta(minutes=5)).isoformat()
    await database.guardian_state.insert_one({
        "_id": "guardian_worker_cursor",
        "last_attempt_at": stamp.isoformat(),
        "last_finished_at": stamp.isoformat(),
        "last_polled_at": checkpoint,
        "processing_status": "read_blocked" if condition == "partial_source" else "complete",
        "read_status": "partial" if condition == "partial_source" else "complete",
        "read_error_code": "limit_reached" if condition == "partial_source" else None,
        "pages_fetched": 5,
        "records_read": 500,
    })
    if condition == "no_source":
        routes._trace_source.available = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/guardian/monitoring", headers=HEADERS)
        liveness = await client.get("/api/health")
    assert liveness.status_code == 200
    body = response.json()
    assert body["last_successful_checkpoint"] == checkpoint
    assert body["healthy"] is (condition == "recent_success")
    expected = {"recent_success": "complete", "stopped_worker": "stale", "partial_source": "read_blocked", "no_source": "not_configured"}
    assert body["status"] == expected[condition]
    if condition == "partial_source":
        assert body["read_error_code"] == "limit_reached"
        assert body["records_read"] == 500


@pytest.mark.parametrize("path", [
    "/live?hours=0", "/live?hours=169", "/live?calls=0", "/live?calls=101",
    "/live?runs=0", "/live?runs=101", "/metrics?hours=0", "/metrics?hours=169",
    "/incidents?limit=0", "/incidents?limit=501", "/incidents?status=invalid",
    "/trends?days=0", "/trends?days=91",
])
def test_unbounded_or_invalid_queries_are_rejected_before_work(environment, path):
    app, _, _ = environment
    with TestClient(app) as client:
        response = client.get("/api/guardian" + path, headers=HEADERS)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_health_request_remains_responsive_while_live_sdk_read_is_blocked(environment, monkeypatch):
    app, routes, _ = environment
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def snapshot(**kwargs):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=5):
            raise RuntimeError("Fixture was not released")
        return {"available": True, "stats": None}

    monkeypatch.setattr(routes, "_live", SimpleNamespace(snapshot=snapshot))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.get("/api/guardian/live", headers=HEADERS))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            response = await asyncio.wait_for(client.get("/api/health"), timeout=1)
            assert response.status_code == 200
        finally:
            release.set()
            result = await asyncio.wait_for(pending, timeout=2)
        assert result.status_code == 200


@pytest.mark.anyio
async def test_excessive_metric_buckets_are_not_returned_as_complete_truncated_data(environment, monkeypatch):
    app, _, database = environment
    import guardian.metrics as metrics
    monkeypatch.setattr(metrics, "MAX_METRIC_BUCKETS", 2)
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
    await database.guardian_metrics.insert_many([
        {"hour": hour, "agent_name": name, "call_count": 1}
        for name in ("agent-a", "agent-b", "agent-c")
    ])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/guardian/metrics", headers=HEADERS)
    assert response.status_code == 422
    assert "Choose a shorter window" in response.json()["detail"]
