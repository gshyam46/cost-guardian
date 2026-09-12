"""Named session and resolution semantics using isolated Mongo mocks.

These exercise real storage predicates. Mock transactions do not establish
rollback, write-conflict isolation or uncertain commit handling; the owned local
replica-set harness in tools/test_mongo_identity.py covers those boundaries.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

from mongomock_motor import AsyncMongoMockClient
import pytest

from guardian.incident import Incident
from guardian.store import MongoIncidentStore
from identity.errors import IdentityError
from identity.settings import Member, Settings
from identity.store import IdentityStore


ISSUER = "https://identity.example.invalid"


def settings(**changes):
    configured = Settings(
        mode="oidc", issuer=ISSUER, client_id="guardian-test-client",
        client_secret="synthetic-client-secret", public_url="https://guardian.example.invalid",
        ui_origin="https://guardian.example.invalid", organization_id="organization-one",
        project_id="project-one", environment="test", project_name="Project One",
        connection_id="primary", allow_loopback_http=False,
        members={
            "owner-subject": Member("owner-subject", "owner", "Configured Owner"),
            "operator-subject": Member("operator-subject", "operator", "Configured Operator"),
            "viewer-subject": Member("viewer-subject", "viewer", "Configured Viewer"),
        },
    )
    return replace(configured, **changes)


class Clock:
    def __init__(self):
        self.value = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self):
        return self.value


@pytest.fixture
def environment():
    database = AsyncMongoMockClient(tz_aware=True)["identity_unit_tests"]
    configured = settings()
    clock = Clock()
    return database, configured, clock, IdentityStore(database, configured, now=clock)


async def session(store, subject="operator-subject", **claims):
    return await store.create_session({"issuer": ISSUER, "subject": subject,
                                       "name": "Untrusted Provider Label", **claims})


async def incident(database, identifier="incident-one", **changes):
    values = dict(id=identifier, detector="cost_anomaly", severity="high", title="Synthetic",
                  summary="Synthetic incident", evidence={"safe": True}, trace_ids=[], agent_name="test-agent")
    values.update(changes)
    value = Incident(**values)
    await MongoIncidentStore(database).save(value)
    return value


def assert_denied(error, status):
    assert error.value.status_code == status


@pytest.mark.anyio
async def test_flow_is_bound_to_its_browser_and_consumed_once(environment):
    database, _, _, store = environment
    flow = await store.create_flow("127.0.0.1")
    other = await store.create_flow("127.0.0.2")
    with pytest.raises(Exception) as denied:
        await store.consume_flow(flow["state"], other["browser_token"])
    assert_denied(denied, 401)
    consumed = await store.consume_flow(flow["state"], flow["browser_token"])
    assert consumed["nonce"] == flow["nonce"]
    assert consumed["code_verifier"] == flow["code_verifier"]
    with pytest.raises(Exception) as replay:
        await store.consume_flow(flow["state"], flow["browser_token"])
    assert_denied(replay, 401)
    # Independent flow remains usable after the swapped-cookie request.
    await store.consume_flow(other["state"], other["browser_token"])


@pytest.mark.anyio
async def test_concurrent_flow_consumption_has_exactly_one_winner(environment):
    _, _, _, store = environment
    flow = await store.create_flow("127.0.0.1")
    outcomes = await asyncio.gather(*(
        store.consume_flow(flow["state"], flow["browser_token"]) for _ in range(8)
    ), return_exceptions=True)
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert all(isinstance(value, dict) or getattr(value, "status_code", None) == 401 for value in outcomes)


@pytest.mark.anyio
async def test_flow_expiry_is_enforced_without_waiting_for_ttl_cleanup(environment):
    _, _, clock, store = environment
    flow = await store.create_flow("127.0.0.1")
    clock.value += timedelta(minutes=10)
    with pytest.raises(Exception) as denied:
        await store.consume_flow(flow["state"], flow["browser_token"])
    assert_denied(denied, 401)


@pytest.mark.anyio
async def test_session_token_is_opaque_hashed_at_rest_and_not_returned_as_actor(environment):
    database, configured, _, store = environment
    token = await session(store)
    principal = await store.authenticate(token)
    assert isinstance(token, str) and len(token) >= 32
    row = await database.guardian_auth_sessions.find_one({})
    assert token not in json.dumps(row, default=str)
    access = principal.access_response()
    assert token not in json.dumps(access)
    assert "synthetic-client-secret" not in json.dumps(access)
    assert access["actor"]["name"] == "Configured Operator"
    assert access["actor"]["role"] == "operator"
    assert access["permissions"] == ["read", "resolve_incidents"]
    assert access["project"] == {"organization_id": configured.organization_id,
        "project_id": configured.project_id, "environment": configured.environment, "name": configured.project_name}


@pytest.mark.anyio
@pytest.mark.parametrize("subject,permissions", [
    ("owner-subject", ["read", "resolve_incidents"]),
    ("operator-subject", ["read", "resolve_incidents"]),
    ("viewer-subject", ["read"]),
])
async def test_membership_is_configured_subject_authority_not_provider_role(environment, subject, permissions):
    _, _, _, store = environment
    token = await session(store, subject, role="owner", email="owner@example.invalid")
    principal = await store.authenticate(token)
    assert principal.access_response()["permissions"] == permissions


@pytest.mark.anyio
@pytest.mark.parametrize("claims", [
    {"issuer": ISSUER, "subject": "unknown-subject", "email": "owner@example.invalid"},
    {"issuer": "https://other-issuer.example.invalid", "subject": "owner-subject"},
])
async def test_unlisted_or_wrong_issuer_identity_cannot_create_a_session(environment, claims):
    database, _, _, store = environment
    with pytest.raises(Exception) as denied:
        await store.create_session(claims)
    assert_denied(denied, 403)
    assert await database.guardian_auth_sessions.count_documents({}) == 0


@pytest.mark.anyio
async def test_expiry_is_absolute_and_reads_do_not_extend_the_session(environment):
    _, _, clock, store = environment
    token = await session(store)
    clock.value += timedelta(hours=7, minutes=59)
    await store.authenticate(token)
    clock.value += timedelta(minutes=1)
    with pytest.raises(Exception) as denied:
        await store.authenticate(token)
    assert_denied(denied, 401)


@pytest.mark.anyio
async def test_logout_revokes_server_session_and_relogin_rotates_previous_token(environment):
    _, _, _, store = environment
    first = await session(store)
    second = await store.create_session({"issuer": ISSUER, "subject": "operator-subject"}, previous_token=first)
    assert first != second
    with pytest.raises(Exception) as replaced:
        await store.authenticate(first)
    assert_denied(replaced, 401)
    principal = await store.authenticate(second)
    await store.logout(principal)
    with pytest.raises(Exception) as logged_out:
        await store.authenticate(second)
    assert_denied(logged_out, 401)


@pytest.mark.anyio
async def test_membership_removal_or_downgrade_applies_to_existing_sessions(environment):
    database, configured, clock, store = environment
    token = await session(store)
    downgraded = dict(configured.members)
    downgraded["operator-subject"] = Member("operator-subject", "viewer", "Current Viewer Label")
    changed = IdentityStore(database, replace(configured, members=downgraded), now=clock)
    principal = await changed.authenticate(token)
    assert principal.access_response()["permissions"] == ["read"]
    assert principal.access_response()["actor"]["name"] == "Current Viewer Label"
    del downgraded["operator-subject"]
    removed = IdentityStore(database, replace(configured, members=downgraded), now=clock)
    with pytest.raises(Exception) as denied:
        await removed.authenticate(token)
    assert_denied(denied, 403)


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [
    ("organization_id", "other-org"), ("project_id", "other-project"),
    ("environment", "production"), ("connection_id", "other-connection"),
    ("issuer", "https://other-issuer.example.invalid"), ("client_id", "other-client"),
])
async def test_database_binding_cannot_be_silently_reassigned(environment, field, value):
    database, configured, clock, store = environment
    token = await session(store)
    original = await database.guardian_state.find_one({"_id": "identity_binding"})
    changed = IdentityStore(database, replace(configured, **{field: value}), now=clock)
    with pytest.raises(Exception) as denied:
        await changed.authenticate(token)
    assert_denied(denied, 503)
    assert await database.guardian_state.find_one({"_id": "identity_binding"}) == original


@pytest.mark.anyio
async def test_existing_ledger_connection_blocks_incompatible_identity_binding(environment):
    database, _, _, store = environment
    await database.guardian_state.insert_one({"_id": "ledger_configuration", "connection_id": "different"})
    with pytest.raises(Exception) as denied:
        await store.ensure_binding()
    assert_denied(denied, 503)


@pytest.mark.anyio
async def test_resolve_records_actor_once_and_replay_preserves_first_resolution(environment):
    database, _, clock, store = environment
    await incident(database)
    principal = await store.authenticate(await session(store))
    resolved = await store.resolve(principal, "incident-one")
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    first_time = resolved.resolved_at
    clock.value += timedelta(minutes=1)
    second_actor = await store.authenticate(await session(store, "owner-subject"))
    replay = await store.resolve(second_actor, "incident-one")
    assert replay.resolved_at == first_time
    rows = await database.guardian_identity_audit.find({}).to_list(None)
    assert len(rows) == 1
    serialized = json.dumps(rows, default=str)
    assert principal.actor["id"] in serialized
    assert second_actor.actor["id"] not in serialized
    assert "incident-one" in serialized
    assert "project-one" in serialized
    assert "synthetic-client-secret" not in serialized
    assert "\"evidence\"" not in serialized  # Incident content is not an audit payload.


@pytest.mark.anyio
async def test_existing_resolved_incident_does_not_gain_an_invented_actor_or_new_timestamp(environment):
    database, _, clock, store = environment
    original = clock.value - timedelta(days=3)
    await incident(database, status="resolved", resolved_at=original)
    principal = await store.authenticate(await session(store))
    current = await store.resolve(principal, "incident-one")
    assert current.resolved_at == original
    assert await database.guardian_identity_audit.count_documents({}) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("invalidate", ["expiry", "logout", "membership"])
async def test_principal_checked_earlier_cannot_resolve_after_authority_is_lost(environment, invalidate):
    database, configured, clock, store = environment
    await incident(database)
    principal = await store.authenticate(await session(store))
    expected = 401
    if invalidate == "expiry":
        clock.value += timedelta(hours=8)
    elif invalidate == "logout":
        await store.logout(principal)
    else:
        members = dict(configured.members)
        members["operator-subject"] = Member("operator-subject", "viewer", "Viewer")
        store = IdentityStore(database, replace(configured, members=members), now=clock)
        expected = 403
    with pytest.raises(Exception) as denied:
        await store.resolve(principal, "incident-one")
    assert_denied(denied, expected)
    assert (await MongoIncidentStore(database).get("incident-one")).status == "open"
    assert await database.guardian_identity_audit.count_documents({}) == 0


@pytest.mark.anyio
async def test_missing_incident_never_creates_audit(environment):
    database, _, _, store = environment
    principal = await store.authenticate(await session(store))
    with pytest.raises(Exception) as denied:
        await store.resolve(principal, "not-present")
    assert_denied(denied, 404)
    assert await database.guardian_identity_audit.count_documents({}) == 0
