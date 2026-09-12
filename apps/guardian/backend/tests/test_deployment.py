"""Deployment acceptance; mocks verify predicates, real Mongo proves transactions."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings
from unittest.mock import AsyncMock

import httpx
from mongomock_motor import AsyncMongoMockClient
import pytest

from deployment.bootstrap import bootstrap, MARKER_ID
from deployment.configuration import load_configuration, prepare_environment, validate_mongo_url
from deployment.errors import DeploymentError
from deployment.readiness import ready
from deployment.runtime import supervised, worker_loop

BACKEND = Path(__file__).resolve().parents[1]
HELLO = {"setName": "synthetic-replica", "isWritablePrimary": True,
         "logicalSessionTimeoutMinutes": 30, "maxWireVersion": 25}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    directory = tmp_path / "build"
    (directory / "static/js").mkdir(parents=True)
    js = "/static/js/main.12345678.js"
    (directory / js[1:]).write_text("console.log('synthetic')", encoding="utf-8")
    (directory / "index.html").write_text(f'<html><script src="{js}"></script></html>', encoding="utf-8")
    (directory / "asset-manifest.json").write_text(json.dumps({"files": {"index.html": "/index.html", "main.js": js},
        "entrypoints": [js[1:]]}), encoding="utf-8")
    for key in ("MONGO_URL", "GUARDIAN_OIDC_CLIENT_SECRET", "GUARDIAN_OIDC_MEMBERS_JSON", "GUARDIAN_SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(key + "_FILE", raising=False)
    values = {"MONGO_URL": "mongodb://synthetic:synthetic@database.invalid/?replicaSet=guardian&tls=true",
        "GUARDIAN_DB_NAME": "guardian_deployment_test", "GUARDIAN_CAPTURE_MODE": "direct", "GUARDIAN_AUTH_MODE": "oidc",
        "GUARDIAN_STATIC_DIR": str(directory), "GUARDIAN_OIDC_ISSUER": "https://identity.invalid",
        "GUARDIAN_OIDC_CLIENT_ID": "synthetic-client", "GUARDIAN_OIDC_CLIENT_SECRET": "private-secret-canary",
        "GUARDIAN_OIDC_MEMBERS_JSON": '[{"subject":"owner-subject","role":"owner","name":"Owner"}]',
        "GUARDIAN_PUBLIC_URL": "https://guardian.invalid", "GUARDIAN_UI_ORIGIN": "https://guardian.invalid",
        "GUARDIAN_ORGANIZATION_ID": "organization-one", "GUARDIAN_PROJECT_ID": "project-one",
        "GUARDIAN_ENVIRONMENT": "test", "GUARDIAN_PROJECT_NAME": "Test Project", "GUARDIAN_CONNECTION_ID": "primary",
        "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "false", "GUARDIAN_POLL_INTERVAL_SECONDS": "60",
        "GUARDIAN_PORT": "8001", "GUARDIAN_BIND_HOST": "127.0.0.1", "GUARDIAN_TRUSTED_PROXY_IPS": "",
        "GUARDIAN_SLACK_WEBHOOK_URL": ""}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return load_configuration()


@pytest.fixture
def database(monkeypatch):
    db = AsyncMongoMockClient(tz_aware=True)["deployment_test"]
    monkeypatch.setattr(db, "command", AsyncMock(return_value=HELLO))
    return db


def test_check_validates_without_database_dns_or_provider(configured, monkeypatch):
    import socket
    def denied(*_args, **_kwargs):
        pytest.fail("configuration check attempted DNS")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    assert load_configuration() == configured
    assert "private-secret-canary" not in repr(configured)
    assert "synthetic:synthetic" not in repr(configured)


@pytest.mark.parametrize("key,value", [
    ("GUARDIAN_DB_NAME", "admin"), ("GUARDIAN_DB_NAME", "local"), ("GUARDIAN_DB_NAME", "config"),
    ("GUARDIAN_DB_NAME", ""), ("GUARDIAN_DB_NAME", "a.b"), ("GUARDIAN_CONNECTION_ID", ""),
    ("GUARDIAN_CAPTURE_MODE", "langfuse"), ("GUARDIAN_AUTH_MODE", "api_key"),
    ("GUARDIAN_POLL_INTERVAL_SECONDS", "0"), ("GUARDIAN_POLL_INTERVAL_SECONDS", "-1"),
    ("GUARDIAN_POLL_INTERVAL_SECONDS", "301"), ("GUARDIAN_POLL_INTERVAL_SECONDS", "1.5"),
    ("GUARDIAN_PORT", "0"), ("GUARDIAN_PORT", "65536"),
    ("GUARDIAN_TRUSTED_PROXY_IPS", "*"), ("GUARDIAN_TRUSTED_PROXY_IPS", "172.18.0.0/16"),
    ("GUARDIAN_TRUSTED_PROXY_IPS", "proxy.invalid"), ("GUARDIAN_UI_ORIGIN", "https://other.invalid"),
    ("GUARDIAN_OIDC_MEMBERS_JSON", "[]"), ("GUARDIAN_STATIC_DIR", "missing-private-path")])
def test_invalid_deployment_configuration_is_safe(configured, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(DeploymentError) as error:
        load_configuration()
    assert str(error.value) == "invalid_deployment_configuration"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("uri", [
    "mongodb://database.invalid/?tls=true", "mongodb://u:p@database.invalid/", "mongodb://u:p@database.invalid/?tls=false",
    "mongodb://u:p@database.invalid/?tls=true&tlsAllowInvalidCertificates=true",
    "mongodb+srv://u:p@database.invalid/?tlsInsecure=true", "mongodb+srv://u:p@database.invalid/?ssl=false",
    "mongodb://u:p@database.invalid/?tls=true&TLS=true", "mongodb://u:p@database.invalid/?tls=true&loadBalanced=true"])
def test_production_mongo_requires_authenticated_verified_tls(uri):
    with pytest.raises(DeploymentError) as error:
        validate_mongo_url(uri)
    assert str(error.value) == "invalid_mongo_configuration"


def test_srv_check_has_no_dns_and_local_exception_cannot_reach_remote(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("unexpected DNS"))
    assert validate_mongo_url("mongodb+srv://u:p@database.invalid/")
    assert validate_mongo_url("mongodb://127.0.0.1:27019/?replicaSet=test", local=True)
    assert validate_mongo_url("mongodb://[::1]:27019/?replicaSet=test", local=True)
    with pytest.raises(DeploymentError):
        validate_mongo_url("mongodb://127.0.0.1:27019,remote.invalid:27019/", local=True)


def test_invalid_mongo_options_never_warn_with_operator_values():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(DeploymentError) as error:
            validate_mongo_url("mongodb://u:p@database.invalid/?tls=true&private-option-canary=private-value")
    assert str(error.value) == "invalid_mongo_configuration"
    assert not caught


def test_file_secrets_are_bounded_private_and_idempotent(configured, tmp_path, monkeypatch):
    path = tmp_path / "secret-file"
    path.write_bytes(b" secret-spaces-preserved \r\n")
    monkeypatch.delenv("GUARDIAN_OIDC_CLIENT_SECRET")
    monkeypatch.setenv("GUARDIAN_OIDC_CLIENT_SECRET_FILE", str(path))
    prepare_environment()
    assert os.environ["GUARDIAN_OIDC_CLIENT_SECRET"] == " secret-spaces-preserved "
    assert "GUARDIAN_OIDC_CLIENT_SECRET_FILE" not in os.environ
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    prepare_environment()


@pytest.mark.parametrize("content", [b"", b"\n", b"\xff", b"x" * 4097, b"null\x00secret"])
def test_bad_file_secrets_do_not_echo_values_or_paths(configured, tmp_path, monkeypatch, content):
    path = tmp_path / "private-path-canary"
    path.write_bytes(content)
    monkeypatch.delenv("GUARDIAN_OIDC_CLIENT_SECRET")
    monkeypatch.setenv("GUARDIAN_OIDC_CLIENT_SECRET_FILE", str(path))
    with pytest.raises(DeploymentError) as error:
        prepare_environment()
    assert str(error.value) == "invalid_secret_configuration"
    assert "GUARDIAN_OIDC_CLIENT_SECRET" not in os.environ


def test_secret_conflict_directory_and_missing_file_fail_safely(configured, tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_OIDC_CLIENT_SECRET_FILE", str(tmp_path))
    with pytest.raises(DeploymentError):
        prepare_environment()
    monkeypatch.delenv("GUARDIAN_OIDC_CLIENT_SECRET")
    with pytest.raises(DeploymentError):
        prepare_environment()
    monkeypatch.setenv("GUARDIAN_OIDC_CLIENT_SECRET_FILE", str(tmp_path / "absent-private"))
    with pytest.raises(DeploymentError):
        prepare_environment()


def test_no_argument_help_is_standalone_and_inert():
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP"}}
    environment.update(MONGO_URL="invalid-private-credential", GUARDIAN_PORT="invalid-private-value")
    result = subprocess.run([sys.executable, "-S", "-m", "deployment"], cwd=BACKEND,
        env=environment, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and "usage:" in result.stdout and not result.stderr
    assert "private" not in result.stdout


@pytest.mark.anyio
async def test_fresh_bootstrap_is_ready_before_login_or_traffic_and_repeats_safely(configured, database):
    assert not await ready(database, configured)
    await bootstrap(database, configured)
    assert await ready(database, configured)
    marker = await database.guardian_state.find_one({"_id": MARKER_ID})
    assert marker and await database.guardian_auth_sessions.count_documents({}) == 0
    assert await database.guardian_capture_inbox.count_documents({}) == 0
    assert await database.guardian_state.find_one({"_id": "guardian_worker_cursor"}) is None
    await bootstrap(database, configured)
    assert await database.guardian_state.find_one({"_id": MARKER_ID}) == marker
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_incidents.count_documents({}) == 0
    assert "identity_expiry" in await database.guardian_auth_sessions.index_information()
    assert "incident_status_created_utc" in await database.guardian_incidents.index_information()
    assert "notification_due" in await database.guardian_notification_deliveries.index_information()


@pytest.mark.anyio
async def test_bootstrap_rejects_scope_mismatch_without_new_state(configured, database):
    await bootstrap(database, configured)
    before = await database.guardian_state.find({}).to_list(20)
    changed = replace(configured, identity=replace(configured.identity, project_id="other-project"))
    with pytest.raises(DeploymentError, match="deployment_binding_mismatch"):
        await bootstrap(database, changed)
    assert await database.guardian_state.find({}).to_list(20) == before
    assert not await ready(database, changed)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["metrics", "incidents", "source", "ledger"])
async def test_existing_legacy_or_other_source_is_not_silently_initialized(configured, database, kind):
    if kind == "metrics":
        await database.guardian_metrics.insert_one({"_id": "old-rollup", "total_cost_usd": 20})
    elif kind == "incidents":
        await database.guardian_incidents.insert_one({"_id": "old-incident", "status": "resolved"})
    elif kind == "source":
        await database.guardian_state.insert_one({"_id": "capture_binding", "mode": "langfuse"})
    else:
        await database.guardian_state.insert_one({"_id": "ledger_configuration", "connection_id": "primary", "version": "ledger-1"})
    before = await database.guardian_state.find({}).to_list(10)
    with pytest.raises(DeploymentError):
        await bootstrap(database, configured)
    assert await database.guardian_state.find({}).to_list(10) == before
    assert await database.guardian_state.find_one({"_id": MARKER_ID}) is None


@pytest.mark.anyio
async def test_standalone_refusal_precedes_any_state_or_index_mutation(configured, database, monkeypatch):
    monkeypatch.setattr(database, "command", AsyncMock(return_value={"isWritablePrimary": True, "maxWireVersion": 25}))
    with pytest.raises(DeploymentError, match="transaction_database_required"):
        await bootstrap(database, configured)
    assert await database.list_collection_names() == []


@pytest.mark.anyio
async def test_readiness_does_not_write_and_outage_is_not_ready(configured, database, monkeypatch):
    await bootstrap(database, configured)
    before = await database.guardian_state.find({}).to_list(20)
    assert await ready(database, configured)
    assert await database.guardian_state.find({}).to_list(20) == before
    monkeypatch.setattr(database, "command", AsyncMock(side_effect=RuntimeError("private-db-uri-canary")))
    assert not await ready(database, configured)


@pytest.mark.anyio
async def test_http_readiness_has_fixed_private_response_without_auth_or_heartbeat(configured, database, monkeypatch):
    import server
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server.app.state, "deployment_configuration", configured, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="https://guardian.invalid") as client:
        assert (await client.get("/api/health")).status_code == 200
        response = await client.get("/api/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "service": "cost-guardian"}
        assert response.headers["cache-control"] == "no-store"
        await bootstrap(database, configured)
        response = await client.get("/api/ready")
        assert response.status_code == 200 and response.json() == {"status": "ready", "service": "cost-guardian"}
        assert not response.headers.get("set-cookie")


@pytest.mark.anyio
async def test_shutdown_cancels_inflight_loop_before_closing_resources():
    stop, entered = asyncio.Event(), asyncio.Event()
    order = []
    async def operation():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            order.append("pending-work-released")
    async def close():
        order.append("database-closed")
    running = asyncio.create_task(supervised(operation, close, stop=stop))
    await entered.wait()
    stop.set()
    await asyncio.wait_for(running, 1)
    assert order == ["pending-work-released", "database-closed"]


@pytest.mark.anyio
async def test_worker_pass_failure_retries_but_cancellation_is_not_swallowed(configured, database, monkeypatch):
    import guardian.direct_worker as worker
    calls = []
    reached = asyncio.Event()
    async def poll(db, settings):
        calls.append((db, settings))
        if len(calls) == 1:
            raise RuntimeError("private-database-error")
        reached.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(worker, "poll_direct_once", poll)
    running = asyncio.create_task(worker_loop(database, replace(configured, poll_interval=0), "worker"))
    await asyncio.wait_for(reached.wait(), 1)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert len(calls) == 2 and calls[0] == (database, configured.identity)
