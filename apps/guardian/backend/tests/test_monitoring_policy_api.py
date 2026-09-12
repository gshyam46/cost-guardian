"""Actual API/authority/schema checks; real Mongo separately proves atomicity."""
from dataclasses import replace
import json

import pytest

from identity.store import IdentityStore
from policies.errors import PolicyError
from policies.schema import DEFAULT_RULES
from policies.store import COLLECTION, PolicyStore, policy_id
from tests.test_capture_api import environment as capture_environment, login, ORIGIN

pytestmark = pytest.mark.anyio
PATH = "/api/guardian/monitoring-policy"
PRIVATE = "private-provider-content-canary"


@pytest.fixture
async def environment(capture_environment, monkeypatch):
    import policies.routes as routes
    monkeypatch.setattr(routes, "db", capture_environment.db)
    return capture_environment


def body(revision=0, **changes):
    return {"expected_revision": revision, "rules": {**DEFAULT_RULES, **changes}}


async def save(env, value=None, headers=None):
    if headers is None:
        headers = await login(env)
    return await env.client.put(PATH, headers=headers, json=value or body(max_call_cost_usd="0.05", max_call_latency_ms=1000))


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
async def test_default_rules_are_readable_without_writing_configuration(environment, role):
    env = environment
    await login(env, role)
    response = await env.client.get(PATH)
    assert response.status_code == 200, response.text
    assert response.json() == {"schema_version": 1, "revision": 0, "rules": DEFAULT_RULES,
        "updated_at": None, "updated_by": None, "can_manage": role == "owner",
        "project": {"organization_id": "organization-one", "project_id": "project-one", "environment": "test", "name": "Project One"}}
    assert await env.db[COLLECTION].count_documents({}) == 0
    assert "no-store" in response.headers["cache-control"]


async def test_owner_save_and_readback_preserve_exact_values_and_redacted_audit(environment):
    env = environment
    response = await save(env, body(max_call_cost_usd="0.050000000001", max_call_latency_ms=0, alert_on_errors=False))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["revision"] == 1 and value["rules"] == body(max_call_cost_usd="0.050000000001", max_call_latency_ms=0, alert_on_errors=False)["rules"]
    assert value["updated_by"]["role"] == "owner"
    assert value["updated_at"] is not None
    assert (await env.client.get(PATH)).json() == value
    rows = await env.db.guardian_identity_audit.find({"action": "update_monitoring_policy"}).to_list(None)
    assert len(rows) == 1 and rows[0]["revision"] == 1
    assert rows[0]["before"] == DEFAULT_RULES and rows[0]["after"] == value["rules"]
    assert rows[0]["actor"] == value["updated_by"] and rows[0]["project"] == value["project"]
    assert not {"session_id", "csrf_token", "token", "client_secret"} & rows[0].keys()
    assert "no-store" in response.headers["cache-control"]


async def test_stale_revision_including_lost_successful_response_cannot_overwrite(environment):
    env = environment
    first = await save(env)
    repeated = await save(env)
    changed = await save(env, body(max_call_cost_usd="8"))
    assert first.status_code == 200
    assert repeated.status_code == changed.status_code == 409
    assert changed.json()["detail"]["code"] == "policy_revision_conflict"
    assert (await env.client.get(PATH)).json()["rules"] == first.json()["rules"]
    assert await env.db.guardian_identity_audit.count_documents({"action": "update_monitoring_policy"}) == 1
    second = await save(env, body(1, max_call_cost_usd="0"))
    assert second.status_code == 200 and second.json()["revision"] == 2


@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_only_owner_can_write_even_with_valid_csrf(environment, role):
    env = environment
    headers = await login(env, role)
    response = await save(env, headers=headers)
    assert response.status_code == 403
    assert await env.db[COLLECTION].count_documents({}) == 0
    assert await env.db.guardian_identity_audit.count_documents({}) == 0


@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"Origin": "https://foreign.invalid", "X-Guardian-CSRF": PRIVATE},
    [("Origin", ORIGIN), ("X-Guardian-CSRF", PRIVATE), ("X-Guardian-CSRF", PRIVATE)]])
async def test_mutation_requires_exact_origin_and_one_current_csrf(environment, headers):
    await login(environment)
    response = await save(environment, headers=headers)
    assert response.status_code == 403
    assert PRIVATE not in response.text
    assert await environment.db[COLLECTION].count_documents({}) == 0


async def test_machine_key_and_unauthenticated_requests_have_no_policy_authority(environment):
    for method in ("get", "put"):
        for headers in ({}, {"X-Guardian-Ingest-Key": PRIVATE}, {"X-Guardian-Key": PRIVATE}):
            response = await getattr(environment.client, method)(PATH, headers=headers)
            assert response.status_code == 401
            assert PRIVATE not in response.text


@pytest.mark.parametrize("changes", [
    {"max_call_cost_usd": True}, {"max_call_cost_usd": 1}, {"max_call_cost_usd": 0.1},
    {"max_call_cost_usd": "-1"}, {"max_call_cost_usd": "1e-3"}, {"max_call_cost_usd": "01"},
    {"max_call_cost_usd": "0.1234567890123"}, {"max_call_cost_usd": "1000000000"},
    {"max_call_cost_usd": "0\n"}, {"max_call_cost_usd": "NaN"}, {"max_call_cost_usd": PRIVATE},
    {"max_call_latency_ms": True}, {"max_call_latency_ms": -1}, {"max_call_latency_ms": 86400001},
    {"max_call_latency_ms": 1.0}, {"max_call_latency_ms": "1000"},
    {"alert_on_errors": 1}, {"alert_on_errors": None}, {"alert_on_errors": "true"},
    {"project_id": PRIVATE}, {"prompt": PRIVATE},
])
async def test_invalid_rules_reject_without_echo_or_write(environment, changes):
    response = await save(environment, body(**changes))
    assert response.status_code == 400, response.text
    assert PRIVATE not in response.text
    assert await environment.db[COLLECTION].count_documents({}) == 0


@pytest.mark.parametrize("value", [None, [], {}, {"expected_revision": 0},
    {"expected_revision": -1, "rules": DEFAULT_RULES}, {"expected_revision": True, "rules": DEFAULT_RULES},
    {"expected_revision": "0", "rules": DEFAULT_RULES}, {"expected_revision": 0.0, "rules": DEFAULT_RULES},
    {"expected_revision": 2**31 - 1, "rules": DEFAULT_RULES},
    {"expected_revision": 0, "rules": DEFAULT_RULES, "project": PRIVATE}])
async def test_strict_envelope_and_revision(environment, value):
    headers = await login(environment)
    response = await environment.client.put(PATH, headers={**headers, "Content-Type": "application/json"}, content=json.dumps(value))
    assert response.status_code == 400
    assert PRIVATE not in response.text


@pytest.mark.parametrize("raw", ['{"expected_revision":0,"expected_revision":0,"rules":{}}',
    '{"expected_revision":0,"rules":{"max_call_cost_usd":null,"max_call_latency_ms":null,"alert_on_errors":true,"alert_on_errors":false}}',
    '{"expected_revision":NaN,"rules":{}}', '{broken'])
async def test_duplicate_json_and_nonstandard_constants_are_rejected(environment, raw):
    headers = await login(environment)
    response = await environment.client.put(PATH, headers={**headers, "Content-Type": "application/json"}, content=raw)
    assert response.status_code == 400
    assert await environment.db[COLLECTION].count_documents({}) == 0


@pytest.mark.parametrize("headers,content,status", [
    ({"Content-Type": "text/plain"}, "{}", 415),
    ({"Content-Type": "application/json", "Content-Encoding": "gzip"}, "{}", 413),
    ({"Content-Type": "application/json"}, " " * 8193, 413),
])
async def test_body_limits(environment, headers, content, status):
    auth = await login(environment)
    response = await environment.client.put(PATH, headers={**auth, **headers}, content=content)
    assert response.status_code == status


@pytest.mark.parametrize("changes", [{"rules": {}}, {"revision": True}, {"revision": -1}, {"fence": -1},
    {"binding_id": "a" * 64}, {"updated_at": "2026-09-12"}, {"updated_by": {"role": "owner", "name": PRIVATE}},
    {"schema_version": True}, {"connection_id": "other-project"}])
async def test_corrupt_saved_configuration_never_falls_back_to_defaults(environment, changes):
    assert (await save(environment)).status_code == 200
    await environment.db[COLLECTION].update_one({"_id": policy_id("primary")}, {"$set": changes})
    response = await environment.client.get(PATH)
    assert response.status_code == 503
    assert PRIVATE not in response.text


async def test_store_rechecks_real_role_csrf_and_logout_instead_of_trusting_principal(environment):
    env = environment
    token = await env.identity.create_session({"issuer": env.settings.issuer, "subject": "viewer-subject"})
    viewer = await env.identity.authenticate(token)
    forged = replace(viewer, actor={**viewer.actor, "role": "owner"})
    store = PolicyStore(env.db, env.settings)
    with pytest.raises(PolicyError) as denied:
        await store.save(forged, 0, DEFAULT_RULES)
    assert denied.value.status_code == 403
    token = await env.identity.create_session({"issuer": env.settings.issuer, "subject": "owner-subject"})
    owner = await env.identity.authenticate(token)
    with pytest.raises(PolicyError) as denied:
        await store.save(replace(owner, csrf_token=PRIVATE), 0, DEFAULT_RULES)
    assert denied.value.status_code == 403
    await env.identity.logout(owner)
    with pytest.raises(Exception) as denied:
        await store.save(owner, 0, DEFAULT_RULES)
    assert denied.value.status_code == 401
    assert await env.db[COLLECTION].count_documents({}) == 0


async def test_database_failure_is_safe_unavailable(environment, monkeypatch):
    import policies.store as module
    await login(environment)
    def failure(_db):
        raise RuntimeError(PRIVATE)
    monkeypatch.setattr(module, "_collection", failure)
    response = await environment.client.get(PATH)
    assert response.status_code == 503 and PRIVATE not in response.text


async def test_local_key_mode_is_readonly_and_never_grants_owner_authority(environment, monkeypatch):
    import auth
    monkeypatch.setenv("GUARDIAN_AUTH_MODE", "api_key")
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    headers = {"X-Guardian-Key": auth.GUARDIAN_API_KEY}
    response = await environment.client.get(PATH, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["project"] is None and response.json()["can_manage"] is False
    response = await environment.client.put(PATH, headers={**headers, "Origin": ORIGIN}, json=body())
    assert response.status_code == 403
    assert await environment.db[COLLECTION].count_documents({}) == 0
