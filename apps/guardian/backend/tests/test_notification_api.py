"""Notification authority and request behavior; real Mongo proves rollback separately."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from notifications.control import NotificationStore, COLLECTION
from notifications.errors import NotificationError
from notifications.settings import load_notification_settings
from tests.test_capture_api import environment as capture_environment, login, ORIGIN

pytestmark = pytest.mark.anyio
PATH = "/api/guardian/notifications"
SECRET = "https://hooks.slack.com/services/T_SYNTHETIC/B_TEST/private_url_canary"


@pytest.fixture
async def environment(capture_environment, monkeypatch):
    import notifications.routes as routes
    monkeypatch.setattr(routes, "db", capture_environment.db)
    monkeypatch.delenv("GUARDIAN_SLACK_WEBHOOK_URL", raising=False)
    return capture_environment


def body(revision=0, action="disable", **extra):
    return {"expected_revision": revision, "request_id": str(uuid4()), "action": action, **extra}


async def command(env, value=None, headers=None):
    if headers is None:
        headers = await login(env)
    return await env.client.post(PATH + "/actions", headers=headers, json=value or body())


@pytest.mark.parametrize("role", ["owner", "operator", "viewer"])
async def test_default_status_is_readable_without_creating_configuration(environment, role):
    env = environment
    await login(env, role)
    response = await env.client.get(PATH)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["revision"] == 0 and data["can_manage"] is (role == "owner")
    assert data["destination"] == {"channel": "slack", "state": "not_configured", "verified": False, "enabled": False}
    assert data["worker"] == {"status": "unknown", "last_seen_at": None}
    assert data["deliveries"] == [] and data["has_more"] is False
    assert await env.db[COLLECTION].count_documents({}) == 0
    assert "no-store" in response.headers["cache-control"]


async def test_owner_test_receipt_and_redacted_audit(environment, monkeypatch):
    env = environment
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    value = body(action="test")
    auth = await login(env)
    first = await command(env, value, auth)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["revision"] == 1 and data["destination"]["enabled"] is False
    assert data["destination"]["verified"] is False
    assert len(data["deliveries"]) == 1 and data["deliveries"][0]["state"] == "queued"
    assert data["deliveries"][0]["kind"] == "test" and data["deliveries"][0]["attempt_count"] == 0
    repeated = await command(env, value, auth)
    assert repeated.status_code == 200 and repeated.json() == data
    collision = await command(env, {**value, "action": "disable"}, auth)
    assert collision.status_code == 409
    pending = await command(env, body(1, "test"), auth)
    assert pending.status_code == 409 and pending.json()["detail"]["code"] == "destination_test_pending"
    assert await env.db.guardian_notification_commands.count_documents({}) == 1
    audits = await env.db.guardian_identity_audit.find({"action": "notification_test"}).to_list(None)
    assert len(audits) == 1 and audits[0]["actor"]["role"] == "owner"
    for name in (COLLECTION, "guardian_notification_commands", "guardian_notification_deliveries", "guardian_identity_audit"):
        stored = await env.db[name].find({}).to_list(None)
        assert SECRET not in repr(stored) and "private_url_canary" not in repr(stored)
    assert SECRET not in first.text and "private_url_canary" not in first.text


async def test_enable_requires_verified_current_destination_and_rotation_is_visible(environment, monkeypatch):
    env = environment
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    auth = await login(env)
    assert (await command(env, body(action="enable"), auth)).status_code == 409
    assert (await command(env, body(action="test"), auth)).status_code == 200
    assert (await command(env, body(1, "enable"), auth)).status_code == 409
    await env.db[COLLECTION].update_one({}, {"$set": {"verified_at": datetime.now(timezone.utc).isoformat()}})
    enabled = await command(env, body(1, "enable"), auth)
    assert enabled.status_code == 200 and enabled.json()["destination"]["enabled"] is True
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET + "_rotated")
    rotated = (await env.client.get(PATH)).json()
    assert rotated["destination"] == {"channel": "slack", "state": "changed", "verified": False, "enabled": False}
    assert (await command(env, body(2, "enable"), auth)).status_code == 409
    # Disabling must remain available even when the deployment secret is invalid.
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", "https://untrusted.invalid/private_url_canary")
    disabled = await command(env, body(2), auth)
    assert disabled.status_code == 200 and disabled.json()["destination"]["state"] == "invalid"
    assert disabled.json()["destination"]["enabled"] is False


async def test_retesting_active_destination_does_not_pause_incident_delivery(environment, monkeypatch):
    env = environment
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    auth = await login(env)
    first = await command(env, body(action="test"), auth)
    assert first.status_code == 200
    await env.db.guardian_notification_deliveries.update_one({}, {"$set": {"state": "accepted", "next_attempt_at": None}})
    await env.db[COLLECTION].update_one({}, {"$set": {"verified_at": datetime.now(timezone.utc).isoformat()}})
    assert (await command(env, body(1, "enable"), auth)).status_code == 200
    repeated = await command(env, body(2, "test"), auth)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["destination"]["enabled"] is True
    assert repeated.json()["destination"]["verified"] is True
    assert len(repeated.json()["deliveries"]) == 2


@pytest.mark.parametrize("role", ["operator", "viewer"])
@pytest.mark.parametrize("action", ["test", "enable", "disable", "retry"])
async def test_nonowners_have_no_mutation_authority(environment, role, action):
    env = environment
    headers = await login(env, role)
    response = await command(env, body(action=action), headers)
    assert response.status_code == 403
    assert await env.db[COLLECTION].count_documents({}) == 0


@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"Origin": "https://foreign.invalid", "X-Guardian-CSRF": "private_url_canary"},
    [("Origin", ORIGIN), ("X-Guardian-CSRF", "canary"), ("X-Guardian-CSRF", "canary")]])
async def test_mutations_require_current_csrf_and_exact_origin(environment, headers):
    await login(environment)
    response = await command(environment, headers=headers)
    assert response.status_code == 403
    assert "private_url_canary" not in response.text


async def test_unauthenticated_and_machine_keys_cannot_read_or_write(environment):
    for headers in ({}, {"X-Guardian-Ingest-Key": "canary"}, {"X-Guardian-Key": "canary"}):
        assert (await environment.client.get(PATH, headers=headers)).status_code == 401
        assert (await command(environment, headers=headers)).status_code == 401


@pytest.mark.parametrize("changes", [
    {"expected_revision": True}, {"expected_revision": -1}, {"expected_revision": 2**31 - 1},
    {"expected_revision": "0"}, {"expected_revision": 0.0}, {"request_id": "invalid"},
    {"request_id": None}, {"request_id": "A" * 36}, {"action": "send"},
    {"webhook_url": SECRET}, {"project_id": "foreign"}, {"delivery_id": "a" * 64},
    {"action": "retry"}, {"action": "retry", "delivery_id": "invalid"},
])
async def test_invalid_commands_are_rejected_without_echo(environment, changes):
    response = await command(environment, {**body(), **changes})
    assert response.status_code == 400, response.text
    assert "private_url_canary" not in response.text
    assert await environment.db[COLLECTION].count_documents({}) == 0


@pytest.mark.parametrize("raw", ['{"action":"test","action":"disable"}', '{"action":NaN}', '[]', '{broken'])
async def test_ambiguous_json_rejected(environment, raw):
    auth = await login(environment)
    response = await environment.client.post(PATH + "/actions", headers={**auth, "Content-Type": "application/json"}, content=raw)
    assert response.status_code == 400


@pytest.mark.parametrize("headers,content,status", [
    ({"Content-Type": "text/plain"}, "{}", 415),
    ({"Content-Type": "application/json", "Content-Encoding": "gzip"}, "{}", 413),
    ({"Content-Type": "application/json"}, " " * 4097, 413),
])
async def test_bounded_body(environment, headers, content, status):
    auth = await login(environment)
    response = await environment.client.post(PATH + "/actions", headers={**auth, **headers}, content=content)
    assert response.status_code == status


async def test_store_reauthenticates_forged_owner_csrf_and_logged_out_actor(environment):
    env = environment
    token = await env.identity.create_session({"issuer": env.settings.issuer, "subject": "viewer-subject"})
    viewer = await env.identity.authenticate(token)
    store = NotificationStore(env.db, env.settings)
    with pytest.raises(NotificationError) as denied:
        await store.command(replace(viewer, actor={**viewer.actor, "role": "owner"}), **body())
    assert denied.value.status_code == 403
    token = await env.identity.create_session({"issuer": env.settings.issuer, "subject": "owner-subject"})
    owner = await env.identity.authenticate(token)
    with pytest.raises(NotificationError) as denied:
        await store.command(replace(owner, csrf_token="canary"), **body())
    assert denied.value.status_code == 403
    await env.identity.logout(owner)
    with pytest.raises(Exception) as denied:
        await store.command(owner, **body())
    assert denied.value.status_code == 401


@pytest.mark.parametrize("changes", [{"revision": True}, {"fence": -1}, {"binding_id": "a" * 64},
    {"destination_id": SECRET}, {"verified_at": "2026-09-12"}, {"enabled": "yes"},
    {"schema_version": True}, {"connection_id": "foreign"}])
async def test_corrupt_state_is_unavailable_not_disabled(environment, changes):
    assert (await command(environment)).status_code == 200
    await environment.db[COLLECTION].update_one({}, {"$set": changes})
    response = await environment.client.get(PATH)
    assert response.status_code == 503 and "private_url_canary" not in response.text


async def test_worker_health_distinguishes_fresh_stale_and_wrong_destination(environment, monkeypatch):
    env = environment
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    await login(env)
    configuration = load_notification_settings(env.settings)
    stamp = datetime.now(timezone.utc)
    heartbeat = {"_id": "notification-worker:primary", "binding_id": env.identity.binding_id,
                 "destination_id": configuration.destination_id, "status": "healthy", "last_seen_at": stamp.isoformat()}
    await env.db.guardian_state.insert_one(heartbeat)
    assert (await env.client.get(PATH)).json()["worker"]["status"] == "healthy"
    await env.db.guardian_state.update_one({"_id": heartbeat["_id"]}, {"$set": {"last_seen_at": (stamp - timedelta(seconds=31)).isoformat()}})
    assert (await env.client.get(PATH)).json()["worker"]["status"] == "stale"
    await env.db.guardian_state.update_one({"_id": heartbeat["_id"]}, {"$set": {"destination_id": "foreign"}})
    assert (await env.client.get(PATH)).json()["worker"]["status"] == "blocked"


async def test_incident_filter_requires_existing_incident_and_rejects_extra_query(environment):
    env = environment
    await login(env)
    assert (await env.client.get(PATH + "?incident_id=missing")).status_code == 404
    assert (await env.client.get(PATH + "?incident_id=one&incident_id=two")).status_code == 400
    assert (await env.client.get(PATH + "?project=foreign")).status_code == 400
    from tests.test_identity_store import incident
    await incident(env.db)
    response = await env.client.get(PATH + "?incident_id=incident-one")
    assert response.status_code == 200 and response.json()["deliveries"] == []


async def test_legacy_key_mode_is_readonly(environment, monkeypatch):
    import auth
    monkeypatch.setenv("GUARDIAN_AUTH_MODE", "api_key")
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    headers = {"X-Guardian-Key": auth.GUARDIAN_API_KEY}
    response = await environment.client.get(PATH, headers=headers)
    assert response.status_code == 200 and response.json()["can_manage"] is False
    assert response.json()["destination"]["state"] == "not_configured"
    assert (await command(environment, headers=headers)).status_code == 403


@pytest.mark.parametrize("url", ["http://hooks.slack.com/services/T/B/token", "https://hooks.slack.com:443/services/T/B/token",
    "https://hooks.slack.com.evil.invalid/services/T/B/token", "https://hooks.slack.com@evil.invalid/services/T/B/token",
    "https://hooks.slack.com/services/T/B/token?secret=1", "https://hooks.slack.com/services/T/B/token#fragment",
    "https://127.0.0.1/services/T/B/token", "https://hooks.slack.com/services/T/B/token\n",
    "https://hooks.slack.com/services/T/B/%2e%2e", "https://hooks.slack.com/services/T/B/token/extra"])
async def test_destination_grammar_rejects_arbitrary_egress(environment, monkeypatch, url):
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", url)
    configured = load_notification_settings(environment.settings)
    assert configured.state == "invalid" and configured.webhook_url == "" and configured.destination_id == ""


async def test_secret_is_excluded_from_settings_repr_and_origin_change_rotates_identity(environment, monkeypatch):
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", SECRET)
    current = load_notification_settings(environment.settings)
    changed = load_notification_settings(replace(environment.settings, ui_origin="https://changed.example.invalid"))
    assert current.state == "configured" and current.destination_id != changed.destination_id
    assert SECRET not in repr(current) and "private_url_canary" not in repr(current)
