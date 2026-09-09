"""Guardian API endpoints exercised over real HTTP (FastAPI TestClient) against a
mocked Mongo backend (mongomock-motor). Real routing, real auth, real
request/response serialization -- only the database underneath is a fake.

Auth here is Guardian's own API key, not a monitored app's session cookie: Guardian
is a standalone service and no longer shares a process with anything it watches.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient


def _run(coro):
    """Run an async call from a sync TestClient test without a stale event loop."""
    return asyncio.run(coro)


@pytest.fixture
def mock_db():
    client = AsyncMongoMockClient()
    return client["guardian_test_db"]


TEST_API_KEY = "test-guardian-key"


@pytest.fixture
def client(monkeypatch, mock_db):
    # api.routes bound `db` at import time via `from db import db`, so patch that
    # module's own reference rather than the db module, or the app would still reach
    # for the real cluster.
    import api.routes as routes
    import auth as auth_module

    monkeypatch.setattr(routes, "db", mock_db)
    monkeypatch.setattr(auth_module, "GUARDIAN_API_KEY", TEST_API_KEY)

    from server import app

    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-Guardian-Key": TEST_API_KEY}


def test_overview_requires_auth(client):
    response = client.get("/api/guardian/overview")
    assert response.status_code == 401


def test_overview_empty_state(client, auth_headers):
    response = client.get("/api/guardian/overview", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "open_incidents": 0,
        "open_by_severity": {},
        "open_by_detector": {},
        "incidents_last_7_days": 0,
    }


def test_incidents_list_and_detail(client, auth_headers, mock_db):
    from guardian.incident import Incident
    from guardian.store import MongoIncidentStore

    incident = Incident(
        detector="cost_anomaly",
        severity="high",
        title="Cost spike in profile_analyst",
        summary="z=4.1",
        evidence={"cost_usd": 0.5, "baseline_mean_usd": 0.01},
        trace_ids=["trace-1"],
        agent_name="profile_analyst",
    )

    _run(MongoIncidentStore(mock_db).save(incident))

    list_response = client.get("/api/guardian/incidents", headers=auth_headers)
    assert list_response.status_code == 200
    incidents = list_response.json()
    assert len(incidents) == 1
    assert incidents[0]["title"] == "Cost spike in profile_analyst"
    assert incidents[0]["evidence"]["cost_usd"] == 0.5

    detail_response = client.get(f"/api/guardian/incidents/{incident.id}", headers=auth_headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == incident.id


def test_incident_detail_404_for_unknown_id(client, auth_headers):
    response = client.get("/api/guardian/incidents/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


def test_resolve_incident(client, auth_headers, mock_db):
    from guardian.incident import Incident
    from guardian.store import MongoIncidentStore

    incident = Incident(
        detector="pii", severity="high", title="PII found", summary="ssn",
        evidence={"pii_types": ["ssn"]}, trace_ids=["trace-2"], agent_name="tooling_advisor",
    )
    _run(MongoIncidentStore(mock_db).save(incident))

    response = client.post(f"/api/guardian/incidents/{incident.id}/resolve", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"

    overview = client.get("/api/guardian/overview", headers=auth_headers).json()
    assert overview["open_incidents"] == 0


def test_trends_returns_one_point_per_day(client, auth_headers):
    response = client.get("/api/guardian/trends?days=7", headers=auth_headers)

    assert response.status_code == 200
    points = response.json()
    assert len(points) == 7
    assert all("date" in p and "count" in p for p in points)
