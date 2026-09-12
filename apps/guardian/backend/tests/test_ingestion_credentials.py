"""Credential authority and secret handling against actual store predicates.

Mongo mocks test semantics only. Atomic rollback, quota serialization and
revocation/intake ordering are independently exercised on a real replica set.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from unittest.mock import AsyncMock
from uuid import uuid4

from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import OperationFailure
import pytest

from capture.credentials import IngestionCredentialStore
from capture.errors import CaptureError
from guardian.ledger import ObservationLedger
from identity.errors import IdentityError
from identity.settings import Member, Settings
from identity.store import IdentityStore


ISSUER = "https://identity.example.invalid"
META_FIELDS = {"id", "label", "prefix", "status", "created_at", "expires_at", "revoked_at", "last_used_at"}


def settings(**changes):
    return replace(Settings(mode="oidc", issuer=ISSUER, client_id="synthetic-client",
        client_secret="synthetic-client-secret", public_url="https://guardian.example.invalid",
        ui_origin="https://guardian.example.invalid", organization_id="organization-one", project_id="project-one",
        environment="test", project_name="Project One", connection_id="primary", members={
            "owner": Member("owner", "owner", "Configured Owner"),
            "second-owner": Member("second-owner", "owner", "Second Owner"),
            "operator": Member("operator", "operator", "Configured Operator"),
            "viewer": Member("viewer", "viewer", "Configured Viewer"),
        }), **changes)


class Clock:
    def __init__(self):
        self.value = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self):
        return self.value


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "direct")
    database = AsyncMongoMockClient(tz_aware=True)["ingestion_credential_tests"]
    configured, clock = settings(), Clock()
    return database, configured, clock, IngestionCredentialStore(database, configured, now=clock)


async def actor(database, configured, clock, subject="owner"):
    identity = IdentityStore(database, configured, now=clock)
    token = await identity.create_session({"issuer": ISSUER, "subject": subject})
    return await identity.authenticate(token)


async def issue(env, **changes):
    database, configured, clock, store = env
    principal = await actor(database, configured, clock)
    values = {"label": "Backend exporter", "expires_in_days": 7, "request_id": str(uuid4())}
    values.update(changes)
    return principal, await store.create(principal, **values)


@pytest.mark.anyio
async def test_owner_gets_one_secret_and_every_later_view_is_redacted(environment, caplog):
    database, _, _, store = environment
    owner, result = await issue(environment)
    token, metadata = result["token"], result["credential"]
    assert re.fullmatch(r"cg_ingest_[0-9a-f]{32}_[A-Za-z0-9_-]{43}", token)
    assert set(metadata) == META_FIELDS
    assert metadata["prefix"] == "cg_ingest_" + metadata["id"][:8]
    assert metadata["status"] == "active"
    assert metadata["last_used_at"] is None
    row = await database.guardian_ingestion_keys.find_one({"_id": metadata["id"]})
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(row, default=str)
    assert token[-43:] not in json.dumps(row, default=str)
    views = await store.list(owner)
    assert views == [metadata]
    assert "token_hash" not in json.dumps(views)
    assert "request_id" not in json.dumps(views)
    audit = await database.guardian_identity_audit.find({}).to_list(None)
    assert len(audit) == 1
    assert audit[0]["actor"]["id"] == owner.actor["id"]
    assert audit[0]["project"] == owner.project
    assert audit[0]["action"] == "create_ingestion_key"
    assert not {"token", "token_hash", "request_id", "label"} & set(audit[0])
    assert token not in json.dumps(audit, default=str)
    assert token not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("subject", ["owner", "operator", "viewer"])
async def test_named_roles_can_read_only_the_same_redacted_project_metadata(environment, subject):
    database, configured, clock, store = environment
    _, result = await issue(environment)
    current = await actor(database, configured, clock, subject)
    assert await store.list(current) == [result["credential"]]


@pytest.mark.anyio
@pytest.mark.parametrize("subject", ["operator", "viewer"])
@pytest.mark.parametrize("operation", ["create", "revoke"])
async def test_nonowners_cannot_manage_keys_even_with_forged_owner_claims(environment, monkeypatch, subject, operation):
    database, configured, clock, store = environment
    principal = await actor(database, configured, clock, subject)
    principal = replace(principal, actor={**principal.actor, "role": "owner"}, permissions=["read", "resolve_incidents"])
    touched = []

    def no_key_reads():
        touched.append(True)
        raise AssertionError("Permission must be checked before reading a credential target")

    monkeypatch.setattr(store, "_keys", no_key_reads)
    with pytest.raises(CaptureError) as denied:
        if operation == "create":
            await store.create(principal, "Server", 7, str(uuid4()))
        else:
            await store.revoke(principal, uuid4().hex)
    assert denied.value.status_code == 403
    assert touched == []


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "revoke"])
async def test_owner_with_wrong_session_csrf_cannot_mutate(environment, operation):
    _, _, _, store = environment
    owner, result = await issue(environment)
    owner = replace(owner, csrf_token="wrong-token-\u00e9")
    with pytest.raises(CaptureError) as denied:
        if operation == "create":
            await store.create(owner, "Server", 7, str(uuid4()))
        else:
            await store.revoke(owner, result["credential"]["id"])
    assert denied.value.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"label": ""}, {"label": "   "}, {"label": "a" * 81}, {"label": "hidden\ntext"},
    {"label": "hidden\x7ftext"}, {"expires_in_days": 0}, {"expires_in_days": 91},
    {"expires_in_days": True}, {"expires_in_days": 1.0}, {"expires_in_days": "7"},
    {"request_id": "invalid"}, {"request_id": None},
])
async def test_invalid_create_input_never_leaves_a_credential_or_audit(environment, changes):
    database, _, _, _ = environment
    with pytest.raises(CaptureError) as denied:
        await issue(environment, **changes)
    assert denied.value.status_code == 400
    assert await database.guardian_ingestion_keys.count_documents({}) == 0
    assert await database.guardian_identity_audit.count_documents({}) == 0


@pytest.mark.anyio
async def test_repeated_request_id_never_reveals_or_creates_another_secret(environment):
    database, _, _, store = environment
    request_id = str(uuid4())
    owner, first = await issue(environment, request_id=request_id)
    with pytest.raises(CaptureError) as replay:
        await store.create(owner, "Changed label", 90, request_id.upper())
    assert replay.value.status_code == 409
    assert replay.value.code == "credential_already_created"
    assert first["token"] not in str(replay.value.detail)
    assert await database.guardian_ingestion_keys.count_documents({}) == 1
    assert await database.guardian_identity_audit.count_documents({}) == 1
    assert await store.list(owner) == [first["credential"]]


@pytest.mark.anyio
async def test_revoke_is_idempotent_preserves_first_actor_and_does_not_delete_history(environment):
    database, configured, clock, store = environment
    first_actor, created = await issue(environment)
    identifier = created["credential"]["id"]
    first = await store.revoke(first_actor, identifier)
    clock.value += timedelta(minutes=1)
    second_actor = await actor(database, configured, clock, "second-owner")
    repeated = await store.revoke(second_actor, identifier)
    assert first == repeated
    assert first["credential"]["status"] == "revoked"
    assert await store.list(second_actor) == [first["credential"]]
    audit = await database.guardian_identity_audit.find({"action": "revoke_ingestion_key"}).to_list(None)
    assert len(audit) == 1
    assert audit[0]["actor"]["id"] == first_actor.actor["id"]
    with pytest.raises(CaptureError) as denied:
        await store.authenticate_ingestion(created["token"])
    assert denied.value.status_code == 401
    assert await database.guardian_ingestion_keys.count_documents({}) == 1


@pytest.mark.anyio
async def test_expiry_is_enforced_at_the_exact_boundary_and_metadata_remains(environment):
    database, configured, clock, store = environment
    _, created = await issue(environment, expires_in_days=1)
    clock.value += timedelta(days=1) - timedelta(milliseconds=1)
    await store.authenticate_ingestion(created["token"])
    clock.value += timedelta(milliseconds=1)
    with pytest.raises(CaptureError) as denied:
        await store.authenticate_ingestion(created["token"])
    assert denied.value.status_code == 401
    renewed_owner = await actor(database, configured, clock)
    assert (await store.list(renewed_owner))[0]["status"] == "expired"
    assert await database.guardian_ingestion_keys.count_documents({}) == 1


@pytest.mark.anyio
async def test_keys_belong_to_project_and_survive_creating_owner_logout_or_removal(environment):
    database, configured, clock, store = environment
    owner, created = await issue(environment)
    await IdentityStore(database, configured, now=clock).logout(owner)
    members = dict(configured.members)
    del members["owner"]
    changed = IngestionCredentialStore(database, replace(configured, members=members), now=clock)
    key = await changed.authenticate_ingestion(created["token"])
    assert key["_id"] == created["credential"]["id"]
    with pytest.raises(IdentityError) as wrong_authority:
        await IdentityStore(database, configured, now=clock).authenticate(created["token"])
    assert wrong_authority.value.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("lost_authority", ["logout", "expired", "downgraded"])
async def test_captured_owner_cannot_create_after_losing_authority(environment, lost_authority):
    database, configured, clock, store = environment
    principal = await actor(database, configured, clock)
    status = 401
    if lost_authority == "logout":
        await IdentityStore(database, configured, now=clock).logout(principal)
    elif lost_authority == "expired":
        clock.value += timedelta(hours=8)
    else:
        members = dict(configured.members)
        members["owner"] = Member("owner", "operator", "No longer an owner")
        store = IngestionCredentialStore(database, replace(configured, members=members), now=clock)
        status = 403
    with pytest.raises(CaptureError) as denied:
        await store.create(principal, "Exporter", 7, str(uuid4()))
    assert denied.value.status_code == status
    assert await database.guardian_ingestion_keys.count_documents({}) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("token", [None, "", b"bytes", "cg_ingest_wrong", "\xff", " bearer-key ", "x" * 10000])
async def test_malformed_keys_fail_closed_without_crashing(environment, token):
    _, _, _, store = environment
    with pytest.raises(CaptureError) as denied:
        await store.authenticate_ingestion(token)
    assert denied.value.status_code == 401


@pytest.mark.anyio
async def test_secret_or_fixed_binding_mismatch_cannot_authorize_ingestion(environment):
    database, configured, clock, store = environment
    _, created = await issue(environment)
    token = created["token"]
    wrong = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(CaptureError) as bad_secret:
        await store.authenticate_ingestion(wrong)
    assert bad_secret.value.status_code == 401
    changed = IngestionCredentialStore(database, replace(configured, project_id="other-project"), now=clock)
    with pytest.raises((CaptureError, IdentityError)) as bad_scope:
        await changed.authenticate_ingestion(token)
    assert bad_scope.value.status_code == 503


@pytest.mark.anyio
async def test_active_limit_allows_explicit_rotation_after_revocation(environment):
    database, configured, clock, store = environment
    owner = await actor(database, configured, clock)
    keys = [await store.create(owner, "Exporter " + str(index), 7, str(uuid4())) for index in range(10)]
    with pytest.raises(CaptureError) as capped:
        await store.create(owner, "Over limit", 7, str(uuid4()))
    assert capped.value.status_code == 429
    await store.revoke(owner, keys[0]["credential"]["id"])
    await store.create(owner, "Replacement", 7, str(uuid4()))
    records = await store.list(owner)
    assert len(records) == 11
    assert sum(record["status"] == "active" for record in records) == 10


@pytest.mark.anyio
async def test_retained_limit_and_listing_never_silently_drop_history(environment):
    database, _, clock, store = environment
    owner, key = await issue(environment)
    template = await database.guardian_ingestion_keys.find_one({"_id": key["credential"]["id"]})
    rows = []
    for index in range(99):
        identifier = uuid4().hex
        rows.append({**template, "_id": identifier, "request_id": str(uuid4()), "label": "Historical " + str(index),
            "prefix": "cg_ingest_" + identifier[:8], "token_hash": hashlib.sha256(identifier.encode()).hexdigest(),
            "revoked_at": clock.value - timedelta(days=1)})
    await database.guardian_ingestion_keys.insert_many(rows)
    assert len(await store.list(owner)) == 100
    with pytest.raises(CaptureError) as full:
        await store.create(owner, "No capacity", 1, str(uuid4()))
    assert full.value.status_code == 429
    await database.guardian_ingestion_keys.insert_one({**rows[0], "_id": uuid4().hex})
    with pytest.raises(CaptureError) as oversized:
        await store.list(owner)
    assert oversized.value.status_code == 503


@pytest.mark.anyio
async def test_plain_authentication_does_not_claim_intake_but_transaction_touch_records_use(environment):
    database, _, clock, store = environment
    owner, created = await issue(environment)
    await store.authenticate_ingestion(created["token"])
    assert (await store.list(owner))[0]["last_used_at"] is None
    clock.value += timedelta(minutes=1)

    async def admitted(session):
        return await store.authenticate_ingestion(created["token"], session=session, touch=True)

    key = await ObservationLedger(database).transaction(admitted)
    assert key["fence"] == 1
    assert (await store.list(owner))[0]["last_used_at"] == clock.value.isoformat()


@pytest.mark.anyio
async def test_transaction_guard_preserves_transient_database_error_for_outer_retry(environment, monkeypatch):
    _, _, _, store = environment
    _, created = await issue(environment)
    failure = OperationFailure("synthetic write conflict", 112, {"errorLabels": ["TransientTransactionError"]})

    class FailedCollection:
        async def find_one_and_update(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr(store, "_keys", lambda: FailedCollection())
    monkeypatch.setattr("capture.credentials.ensure_direct_binding", AsyncMock())
    with pytest.raises(OperationFailure) as actual:
        await store.authenticate_ingestion(created["token"], session=object(), touch=True)
    assert actual.value is failure


@pytest.mark.anyio
async def test_database_auth_failure_has_safe_unavailable_response(environment, monkeypatch):
    _, _, _, store = environment
    _, created = await issue(environment)

    class FailedCollection:
        async def find_one(self, *args, **kwargs):
            raise RuntimeError("mongodb://private-credential@host")

    monkeypatch.setattr(store, "_keys", lambda: FailedCollection())
    with pytest.raises(CaptureError) as denied:
        await store.authenticate_ingestion(created["token"])
    assert denied.value.status_code == 503
    assert "private-credential" not in str(denied.value.detail)


@pytest.mark.anyio
async def test_langfuse_mode_cannot_use_a_direct_project_key(environment, monkeypatch):
    _, _, _, store = environment
    _, created = await issue(environment)
    monkeypatch.setenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    with pytest.raises(CaptureError) as denied:
        await store.authenticate_ingestion(created["token"])
    assert denied.value.status_code == 503
