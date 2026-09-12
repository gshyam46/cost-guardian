"""Real ASGI routing and cookies over a fake provider and isolated mock database.

Provider cryptography has separate signed-token tests; real Mongo transaction
atomicity is checked by tools/test_mongo_identity.py, not this mock suite.
"""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from mongomock_motor import AsyncMongoMockClient
import pytest

from guardian.incident import Incident
from guardian.store import MongoIncidentStore


ORIGIN = "https://guardian.example.invalid"
ISSUER = "https://identity.example.invalid"
PRIVATE_CODE = "synthetic-private-authorization-code"
LEGACY_KEY = "synthetic-existing-key"


class Provider:
    def __init__(self):
        self.started = []
        self.finished = []
        self.subject = "operator-subject"
        self.failure = None

    async def start(self, state, nonce, verifier):
        self.started.append((state, nonce, verifier))
        return ISSUER + "/authorize?state=" + state

    async def finish(self, code, state_data):
        self.finished.append((code, state_data))
        if self.failure:
            raise self.failure
        return {"issuer": ISSUER, "subject": self.subject, "name": "Provider supplied name"}


@pytest.fixture
async def environment(monkeypatch):
    configured = {
        "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_OIDC_ISSUER": ISSUER,
        "GUARDIAN_OIDC_CLIENT_ID": "guardian-test-client",
        "GUARDIAN_OIDC_CLIENT_SECRET": "synthetic-oidc-secret",
        "GUARDIAN_PUBLIC_URL": ORIGIN, "GUARDIAN_UI_ORIGIN": ORIGIN,
        "GUARDIAN_ORGANIZATION_ID": "organization-one", "GUARDIAN_PROJECT_ID": "project-one",
        "GUARDIAN_ENVIRONMENT": "test", "GUARDIAN_PROJECT_NAME": "Project One",
        "GUARDIAN_CONNECTION_ID": "primary", "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "false",
        "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([
            {"subject": "owner-subject", "role": "owner", "name": "Configured Owner"},
            {"subject": "operator-subject", "role": "operator", "name": "Configured Operator"},
            {"subject": "viewer-subject", "role": "viewer", "name": "Configured Viewer"},
        ]),
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)
    import api.routes as data_routes
    import auth
    import identity.routes as identity_routes
    from identity.settings import load_settings
    from server import app

    database = AsyncMongoMockClient(tz_aware=True)["identity_api_tests"]
    provider = Provider()
    monkeypatch.setattr(data_routes, "db", database)
    monkeypatch.setattr(identity_routes, "db", database)
    monkeypatch.setattr(identity_routes, "provider_factory", lambda settings: provider)
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", LEGACY_KEY)
    monkeypatch.setattr(data_routes._trace_source, "trace_url", lambda identifier: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                  base_url=ORIGIN, follow_redirects=False) as client:
        yield SimpleNamespace(client=client, app=app, db=database, provider=provider,
                              settings=load_settings(), data_routes=data_routes)


async def login(env, subject="operator-subject"):
    env.provider.subject = subject
    started = await env.client.get("/api/guardian/auth/login")
    assert started.status_code in (302, 303, 307)
    state = env.provider.started[-1][0]
    callback = await env.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert callback.status_code in (302, 303, 307)
    assert callback.headers["location"] == ORIGIN + "/?guardian_login=complete"
    access = await env.client.get("/api/guardian/access")
    assert access.status_code == 200
    return access.json(), callback


def mutation_headers(access):
    return {"Origin": ORIGIN, "X-Guardian-CSRF": access["csrf_token"]}


def private_response(response):
    assert "no-store" in response.headers.get("cache-control", "").lower()
    assert "cookie" in response.headers.get("vary", "").lower()


async def add_incident(database):
    await MongoIncidentStore(database).save(Incident(id="incident-one", detector="cost_anomaly",
        severity="high", title="Synthetic", summary="Private incident evidence",
        evidence={"provider_payload": "must-not-enter-identity-audit"}, trace_ids=[], agent_name="test-agent"))


@pytest.mark.anyio
async def test_public_auth_configuration_does_not_establish_a_session_or_reveal_credentials(environment):
    response = await environment.client.get("/api/guardian/auth/config")
    assert response.status_code == 200
    assert response.json() == {"auth_mode": "oidc", "login_path": "/api/guardian/auth/login"}
    assert "no-store" in response.headers.get("cache-control", "").lower()
    assert "set-cookie" not in response.headers
    assert "synthetic-oidc-secret" not in response.text
    assert environment.provider.started == environment.provider.finished == []


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [{}, {"X-Guardian-Key": LEGACY_KEY}, {"Authorization": "Bearer " + LEGACY_KEY}])
async def test_oidc_mode_cannot_fall_back_to_the_valid_existing_shared_key(environment, headers):
    response = await environment.client.get("/api/guardian/access", headers=headers)
    assert response.status_code == 401
    private_response(response)
    assert environment.provider.finished == []


@pytest.mark.anyio
@pytest.mark.parametrize("subject,role,permissions", [
    ("owner-subject", "owner", ["read", "resolve_incidents"]),
    ("operator-subject", "operator", ["read", "resolve_incidents"]),
    ("viewer-subject", "viewer", ["read"]),
])
async def test_login_returns_configured_actor_scope_and_role_with_secure_opaque_cookie(environment, subject, role, permissions):
    access, callback = await login(environment, subject)
    assert access["authenticated"] is True
    assert access["auth_mode"] == "oidc"
    assert access["deployment_mode"] == "single_project"
    assert access["actor"]["role"] == role
    assert access["actor"]["name"] == "Configured " + role.capitalize()
    assert access["permissions"] == permissions
    assert access["project"] == {"organization_id": "organization-one", "project_id": "project-one",
                                 "environment": "test", "name": "Project One"}
    cookies = callback.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith(environment.settings.session_cookie + "="))
    assert environment.settings.session_cookie.startswith("__Host-")
    for attribute in ("HttpOnly", "Secure", "Path=/", "SameSite=lax"):
        assert attribute.lower() in session_cookie.lower()
    assert "domain=" not in session_cookie.lower()
    token = environment.client.cookies.get(environment.settings.session_cookie)
    assert token not in json.dumps(access)
    assert PRIVATE_CODE not in callback.headers["location"]
    assert environment.client.cookies.get(environment.settings.login_cookie) is None
    response = await environment.client.get("/api/guardian/access")
    private_response(response)


@pytest.mark.anyio
async def test_callback_state_without_its_browser_cookie_cannot_contact_provider(environment):
    started = await environment.client.get("/api/guardian/auth/login")
    assert started.is_redirect
    state = environment.provider.started[-1][0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=environment.app), base_url=ORIGIN) as stranger:
        failed = await stranger.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert failed.headers["location"] == ORIGIN + "/?guardian_login=failed"
    assert environment.provider.finished == []
    # Failure in an unrelated browser cannot consume the legitimate transaction.
    accepted = await environment.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert accepted.headers["location"] == ORIGIN + "/?guardian_login=complete"


@pytest.mark.anyio
async def test_callback_replay_never_exchanges_the_code_twice(environment):
    await login(environment)
    state = environment.provider.started[-1][0]
    replay = await environment.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert replay.headers["location"] == ORIGIN + "/?guardian_login=failed"
    assert len(environment.provider.finished) == 1


@pytest.mark.anyio
async def test_failed_code_exchange_consumes_state_and_leaks_no_provider_diagnostic(environment, caplog):
    from identity.oidc_provider import ProviderError
    environment.provider.failure = ProviderError("token_exchange_failed")
    await environment.client.get("/api/guardian/auth/login")
    state = environment.provider.started[-1][0]
    failed = await environment.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert failed.headers["location"] == ORIGIN + "/?guardian_login=failed"
    assert environment.client.cookies.get(environment.settings.session_cookie) is None
    environment.provider.failure = None
    await environment.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert len(environment.provider.finished) == 1
    assert PRIVATE_CODE not in caplog.text
    assert state not in caplog.text


@pytest.mark.anyio
async def test_unlisted_provider_identity_does_not_receive_a_session(environment):
    environment.provider.subject = "not-a-member"
    await environment.client.get("/api/guardian/auth/login")
    state = environment.provider.started[-1][0]
    failed = await environment.client.get("/api/guardian/auth/callback", params={"code": PRIVATE_CODE, "state": state})
    assert failed.headers["location"] == ORIGIN + "/?guardian_login=failed"
    assert await environment.db.guardian_auth_sessions.count_documents({}) == 0
    assert environment.client.cookies.get(environment.settings.session_cookie) is None


@pytest.mark.anyio
async def test_client_scope_and_role_claims_cannot_select_a_different_project(environment):
    original, _ = await login(environment, "viewer-subject")
    response = await environment.client.get("/api/guardian/access?project_id=other&role=owner",
        headers={"X-Project-ID": "other", "X-Role": "owner", "X-Guardian-Key": LEGACY_KEY})
    assert response.status_code == 200
    assert response.json() == original


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [
    {}, {"Origin": ORIGIN}, {"Origin": "null", "X-Guardian-CSRF": "valid"},
    {"Origin": "https://attacker.example.invalid", "X-Guardian-CSRF": "valid"},
    {"Origin": ORIGIN + ":443", "X-Guardian-CSRF": "valid"},
    {"Origin": ORIGIN, "X-Guardian-CSRF": "wrong-token"},
])
async def test_resolution_requires_exact_origin_and_session_csrf(environment, headers):
    access, _ = await login(environment)
    await add_incident(environment.db)
    headers = {key: access["csrf_token"] if value == "valid" else value for key, value in headers.items()}
    response = await environment.client.post("/api/guardian/incidents/incident-one/resolve", headers=headers)
    assert response.status_code == 403
    assert (await MongoIncidentStore(environment.db).get("incident-one")).status == "open"
    assert await environment.db.guardian_identity_audit.count_documents({}) == 0


@pytest.mark.anyio
async def test_viewer_mutation_is_denied_before_incident_read_but_viewer_can_logout(environment, monkeypatch):
    from identity.store import IdentityStore
    access, _ = await login(environment, "viewer-subject")
    target_read = AsyncMock(side_effect=AssertionError("Viewer must be denied before target read"))
    monkeypatch.setattr(IdentityStore, "resolve", target_read)
    denied = await environment.client.post("/api/guardian/incidents/unknown/resolve", headers=mutation_headers(access))
    assert denied.status_code == 403
    target_read.assert_not_awaited()
    logout = await environment.client.post("/api/guardian/auth/logout", headers=mutation_headers(access))
    assert logout.status_code == 204
    assert (await environment.client.get("/api/guardian/access")).status_code == 401


@pytest.mark.anyio
async def test_resolution_is_authorized_audited_and_idempotent_through_real_routes(environment):
    access, _ = await login(environment)
    await add_incident(environment.db)
    headers = mutation_headers(access)
    first = await environment.client.post("/api/guardian/incidents/incident-one/resolve", headers=headers)
    second = await environment.client.post("/api/guardian/incidents/incident-one/resolve", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "resolved"
    assert first.json()["resolved_at"] == second.json()["resolved_at"]
    audit = await environment.db.guardian_identity_audit.find({}).to_list(None)
    assert len(audit) == 1
    assert access["actor"]["id"] in json.dumps(audit, default=str)
    assert "must-not-enter-identity-audit" not in json.dumps(audit, default=str)


@pytest.mark.anyio
async def test_session_expiry_and_logout_revoke_the_actual_browser_credential(environment):
    access, _ = await login(environment)
    token = environment.client.cookies.get(environment.settings.session_cookie)
    response = await environment.client.post("/api/guardian/auth/logout", headers=mutation_headers(access))
    assert response.status_code == 204
    assert environment.client.cookies.get(environment.settings.session_cookie) is None
    environment.client.cookies.set(environment.settings.session_cookie, token)
    assert (await environment.client.get("/api/guardian/access")).status_code == 401
    environment.client.cookies.clear()
    await login(environment)
    await environment.db.guardian_auth_sessions.update_many({}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert (await environment.client.get("/api/guardian/access")).status_code == 401


@pytest.mark.anyio
async def test_database_failure_is_safe_unavailable_without_shared_key_fallback(environment, monkeypatch):
    await login(environment)

    class FailedSessions:
        async def find_one(self, *args, **kwargs):
            raise RuntimeError("mongodb://private-credentials")

    class FailedDatabase:
        guardian_auth_sessions = FailedSessions()

        def with_options(self, **kwargs):
            return self

        def __getattr__(self, name):
            return getattr(environment.db, name)

        def get_collection(self, name, **kwargs):
            if name == "guardian_auth_sessions":
                return self.guardian_auth_sessions
            return environment.db.get_collection(name, **kwargs)

    monkeypatch.setattr(environment.data_routes, "db", FailedDatabase())
    response = await environment.client.get("/api/guardian/access", headers={"X-Guardian-Key": LEGACY_KEY})
    assert response.status_code == 503
    private_response(response)
    assert "private-credentials" not in response.text


@pytest.mark.anyio
async def test_binding_mismatch_denies_existing_session_before_source_reads(environment, monkeypatch):
    await login(environment)
    monkeypatch.setenv("GUARDIAN_PROJECT_ID", "different-project")
    source_read = AsyncMock(side_effect=AssertionError("Cannot read another deployment's source"))
    monkeypatch.setattr(environment.data_routes, "run_source_read", source_read)
    response = await environment.client.get("/api/guardian/live")
    assert response.status_code == 503
    source_read.assert_not_awaited()


@pytest.mark.anyio
async def test_callback_ignores_request_return_urls_and_untrusted_host(environment):
    await environment.client.get("/api/guardian/auth/login", params={"return_to": "https://attacker.example.invalid"})
    state = environment.provider.started[-1][0]
    response = await environment.client.get("/api/guardian/auth/callback",
        params={"code": PRIVATE_CODE, "state": state, "return_to": "//attacker.example.invalid"},
        headers={"X-Forwarded-Host": "attacker.example.invalid"})
    assert response.headers["location"] == ORIGIN + "/?guardian_login=complete"
