"""Real ASGI native capture with synthetic sessions and explicitly mocked Mongo."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from mongomock_motor import AsyncMongoMockClient
import pytest
from starlette.requests import Request

from capture.errors import CaptureError
from guardian.direct_worker import poll_direct_once
from identity.settings import load_settings
from identity.store import IdentityStore
from server import app

pytestmark = pytest.mark.anyio
ORIGIN = "https://guardian.example.invalid"
ISSUER = "https://identity.example.invalid"
PRIVATE = "private-prompt-and-secret-canary"


@pytest.fixture
async def environment(monkeypatch):
    configured = {
        "GUARDIAN_CAPTURE_MODE": "direct", "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_OIDC_ISSUER": ISSUER,
        "GUARDIAN_OIDC_CLIENT_ID": "guardian-test-client", "GUARDIAN_OIDC_CLIENT_SECRET": "synthetic-client-secret",
        "GUARDIAN_PUBLIC_URL": ORIGIN, "GUARDIAN_UI_ORIGIN": ORIGIN,
        "GUARDIAN_ORGANIZATION_ID": "organization-one", "GUARDIAN_PROJECT_ID": "project-one",
        "GUARDIAN_ENVIRONMENT": "test", "GUARDIAN_PROJECT_NAME": "Project One", "GUARDIAN_CONNECTION_ID": "primary",
        "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "false", "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([
            {"subject": role + "-subject", "role": role, "name": role.title()} for role in ("owner", "operator", "viewer")]),
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)
    import api.routes as data_routes
    import capture.routes as capture_routes
    import identity.routes as identity_routes
    database = AsyncMongoMockClient(tz_aware=True)["capture_api_tests"]
    for module in (data_routes, capture_routes, identity_routes):
        monkeypatch.setattr(module, "db", database)
    settings = load_settings()
    identity = IdentityStore(database, settings)
    await identity.ensure_binding()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url=ORIGIN, follow_redirects=False) as client:
        yield SimpleNamespace(client=client, db=database, settings=settings, identity=identity, routes=capture_routes)


async def login(env, role="owner"):
    token = await env.identity.create_session({"issuer": ISSUER, "subject": role + "-subject"})
    env.client.cookies.clear()
    env.client.cookies.set(env.settings.session_cookie, token)
    access = await env.client.get("/api/guardian/access")
    assert access.status_code == 200
    return {"Origin": ORIGIN, "X-Guardian-CSRF": access.json()["csrf_token"]}


async def key(env):
    headers = await login(env)
    response = await env.client.post("/api/guardian/ingestion-keys", headers=headers,
        json={"request_id": str(uuid4()), "label": "Synthetic capture", "expires_in_days": 7})
    assert response.status_code == 201, response.text
    return response.json(), headers


def batch(*, test_mode=False, **changes):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    event = {"observation_id": "call-one", "trace_id": "trace-one", "agent_name": "answer-agent", "model": "provider/model",
        "started_at": (now - timedelta(seconds=1)).isoformat(), "ended_at": now.isoformat(), "status": "error",
        "cost_usd": "0.0012", "input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    return {"schema_version": 1, "batch_id": str(uuid4()), "test_mode": test_mode, "events": [event], **changes}


async def submit(env, token, body):
    return await env.client.post("/api/guardian/ingest/events", headers={"X-Guardian-Ingest-Key": token}, json=body)


async def test_owner_key_capture_worker_live_metrics_and_incident_end_to_end(environment):
    env = environment
    credential, _ = await key(env)
    status = await env.client.get("/api/guardian/capture")
    assert status.status_code == 200
    assert status.json()["status"]["worker_status"] == "not_started"
    received = await submit(env, credential["token"], batch())
    assert received.status_code == 202, received.text
    assert received.json()["processing"] == "queued"
    assert received.json()["received"] == 1
    queued = (await env.client.get("/api/guardian/capture")).json()["status"]
    assert (queued["received_events"], queued["pending_events"], queued["processed_events"]) == (1, 1, 0)
    assert queued["last_processed_at"] is None
    waiting_live = await env.client.get("/api/guardian/live")
    assert waiting_live.status_code == 200
    assert waiting_live.json()["coverage"]["reason"] == "capture_pending"
    assert await poll_direct_once(env.db, env.settings) == 1
    metrics = await env.client.get("/api/guardian/metrics")
    assert metrics.status_code == 200
    assert metrics.json()[0]["call_count"] == 1
    assert metrics.json()[0]["total_cost_usd"] == .0012
    assert metrics.json()[0]["total_tokens"] == 12
    live = await env.client.get("/api/guardian/live")
    assert live.status_code == 200, live.text
    assert live.json()["coverage"]["status"] == "complete"
    assert live.json()["source_kind"] == "guardian_direct"
    assert live.json()["stats"]["call_count"] == 1
    run = await env.client.get("/api/guardian/live/runs/trace-one")
    assert run.status_code == 200
    assert run.json()["langfuse_url"] is None
    incidents = await env.client.get("/api/guardian/incidents")
    assert len(incidents.json()) == 1
    assert incidents.json()[0]["detector"] == "reliability_anomaly"
    assert incidents.json()[0]["trace_urls"] == []
    current = (await env.client.get("/api/guardian/capture")).json()["status"]
    assert current["worker_status"] == "current"
    assert (current["pending_events"], current["processed_events"]) == (0, 1)
    assert current["last_processed_at"] is not None
    for response in (received, status, live, metrics, incidents):
        assert "no-store" in response.headers.get("cache-control", "")
        assert credential["token"] not in response.text


async def test_one_time_key_metadata_and_lost_create_response_cannot_reveal_again(environment):
    env = environment
    headers = await login(env)
    request = {"request_id": str(uuid4()), "label": "Synthetic", "expires_in_days": 7}
    first = await env.client.post("/api/guardian/ingestion-keys", headers=headers, json=request)
    assert first.status_code == 201
    secret = first.json()["token"]
    repeated = await env.client.post("/api/guardian/ingestion-keys", headers=headers, json=request)
    assert repeated.status_code == 409
    listed = await env.client.get("/api/guardian/ingestion-keys")
    assert listed.status_code == 200
    assert len(listed.json()["credentials"]) == 1
    assert secret not in listed.text + repeated.text
    for name in await env.db.list_collection_names():
        assert secret not in json.dumps(await env.db[name].find({}).to_list(100), default=str)


@pytest.mark.parametrize("role", ["viewer", "operator"])
async def test_readers_can_inspect_but_only_owner_can_create_or_revoke(environment, role):
    env = environment
    credential, _ = await key(env)
    headers = await login(env, role)
    assert (await env.client.get("/api/guardian/ingestion-keys")).status_code == 200
    capture = await env.client.get("/api/guardian/capture")
    assert capture.json()["can_manage_keys"] is False
    created = await env.client.post("/api/guardian/ingestion-keys", headers=headers,
        json={"request_id": str(uuid4()), "label": "Forbidden", "expires_in_days": 1})
    revoked = await env.client.post("/api/guardian/ingestion-keys/" + credential["credential"]["id"] + "/revoke", headers=headers)
    assert created.status_code == revoked.status_code == 403


@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"Origin": "https://foreign.invalid", "X-Guardian-CSRF": "invalid"},
    [("Origin", ORIGIN), ("X-Guardian-CSRF", "one"), ("X-Guardian-CSRF", "two")]])
async def test_owner_mutations_require_origin_and_unique_current_csrf(environment, headers):
    env = environment
    await login(env)
    response = await env.client.post("/api/guardian/ingestion-keys", headers=headers,
        json={"request_id": str(uuid4()), "label": "Rejected", "expires_in_days": 1})
    assert response.status_code == 403
    assert await env.db.guardian_ingestion_keys.count_documents({}) == 0


async def test_machine_key_cannot_read_data_and_dashboard_session_cannot_ingest(environment):
    env = environment
    credential, _ = await key(env)
    assert (await env.client.post("/api/guardian/ingest/events", json=batch())).status_code == 401
    env.client.cookies.clear()
    for path in ("capture", "ingestion-keys", "metrics", "live", "incidents", "access"):
        response = await env.client.get("/api/guardian/" + path, headers={"X-Guardian-Ingest-Key": credential["token"]})
        assert response.status_code == 401
    assert await env.db.guardian_capture_inbox.count_documents({}) == 0


async def test_authentication_precedes_any_request_body_read(environment):
    env = environment
    async def receive():
        pytest.fail("Unauthorized request body was consumed")
    for headers in ([], [(b"x-guardian-ingest-key", b"invalid")]):
        request = Request({"type": "http", "method": "POST", "path": "/api/guardian/ingest/events", "headers": headers}, receive)
        with pytest.raises(CaptureError) as error:
            await env.routes.ingest_events(request)
        assert error.value.status_code == 401


async def test_exact_batch_and_cross_batch_replay_do_not_duplicate_accounting(environment):
    env = environment
    credential, _ = await key(env)
    payload = batch()
    first = await submit(env, credential["token"], payload)
    repeated = await submit(env, credential["token"], payload)
    another = await submit(env, credential["token"], {**payload, "batch_id": str(uuid4())})
    assert first.status_code == repeated.status_code == another.status_code == 202
    assert repeated.json()["replayed"] is True
    assert another.json()["received"] == 0
    assert another.json()["duplicate"] == 1
    assert await env.db.guardian_capture_inbox.count_documents({}) == 1
    await poll_direct_once(env.db, env.settings)
    assert await env.db.guardian_observations.count_documents({}) == 1
    assert await env.db.guardian_incidents.count_documents({}) == 1


async def test_changed_batch_is_rejected_changed_observation_quarantines_conflict(environment):
    env = environment
    credential, _ = await key(env)
    payload = batch()
    assert (await submit(env, credential["token"], payload)).status_code == 202
    changed = {**payload, "events": [{**payload["events"][0], "cost_usd": "5"}]}
    assert (await submit(env, credential["token"], changed)).status_code == 409
    changed["batch_id"] = str(uuid4())
    response = await submit(env, credential["token"], changed)
    assert response.status_code == 202
    assert response.json()["conflict_candidates"] == 1
    await poll_direct_once(env.db, env.settings)
    metric = (await env.client.get("/api/guardian/metrics")).json()[0]
    assert metric["call_count"] == 1
    assert metric["total_cost_usd"] is None
    assert (await env.client.get("/api/guardian/capture")).json()["status"]["conflicted_events"] == 1


async def test_test_receipt_is_separate_and_does_not_establish_real_traffic(environment):
    env = environment
    credential, _ = await key(env)
    response = await submit(env, credential["token"], batch(test_mode=True))
    assert response.status_code == 202
    assert response.json()["processing"] == "test_only"
    await poll_direct_once(env.db, env.settings)
    state = (await env.client.get("/api/guardian/capture")).json()["status"]
    assert state["last_test_received_at"] is not None
    assert state["last_received_at"] is None
    assert state["received_events"] == state["processed_events"] == state["pending_events"] == 0
    for name in ("guardian_capture_inbox", "guardian_observations", "guardian_metrics", "guardian_incidents"):
        assert await env.db[name].count_documents({}) == 0


async def test_revoked_key_cannot_replay_previously_successful_batch(environment):
    env = environment
    credential, headers = await key(env)
    payload = batch()
    assert (await submit(env, credential["token"], payload)).status_code == 202
    revoked = await env.client.post("/api/guardian/ingestion-keys/" + credential["credential"]["id"] + "/revoke", headers=headers)
    assert revoked.status_code == 200
    assert (await submit(env, credential["token"], payload)).status_code == 401
    assert await poll_direct_once(env.db, env.settings) == 1


async def test_invalid_body_has_no_raw_echo_or_persistence(environment, caplog):
    env = environment
    credential, _ = await key(env)
    payload = batch()
    payload["events"][0]["output"] = PRIVATE
    response = await submit(env, credential["token"], payload)
    assert response.status_code == 400
    assert PRIVATE not in response.text + caplog.text
    for name in await env.db.list_collection_names():
        assert PRIVATE not in json.dumps(await env.db[name].find({}).to_list(100), default=str)
    assert await env.db.guardian_capture_inbox.count_documents({}) == 0


async def test_invalid_and_changed_mode_fail_closed_without_source_fallback(environment, monkeypatch):
    env = environment
    credential, _ = await key(env)
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "unexpected")
    assert (await submit(env, credential["token"], batch())).status_code == 503
    assert (await env.client.get("/api/guardian/live")).status_code == 503
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    assert (await env.client.get("/api/guardian/live")).status_code == 503
    assert await env.db.guardian_capture_inbox.count_documents({}) == 0
