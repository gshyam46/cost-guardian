#!/usr/bin/env python
"""Real scoped-credential and direct-capture checks in owned localhost databases.

No arguments print help. Reuses the guardian-r102 owner-marker/failpoint rules.
No .env, provider, identity-provider or Langfuse requests are made. A final case
starts an owned ephemeral loopback HTTP listener and exercises the real API.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
from unittest.mock import patch
from uuid import uuid4

import test_mongo_identity as identity_checks
import test_mongo_ledger as mongo_checks


check = mongo_checks.check
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def load_dependencies():
    os.environ.update({"PYTHON_DOTENV_DISABLED": "1", "GUARDIAN_CAPTURE_MODE": "direct",
                       "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""})
    identity_checks.load_dependencies()
    global IngestionCredentialStore, CaptureError, CaptureService, decode_batch, poll_direct_once
    global IdentityStore, Member, digest, metric_identity, safe_metric
    from capture.credentials import IngestionCredentialStore
    from capture.errors import CaptureError
    from capture.service import CaptureService
    from capture.schema import decode_batch
    from guardian.direct_worker import poll_direct_once
    from guardian.ledger import digest, identity as metric_identity, safe_metric
    from identity.store import IdentityStore
    from identity.settings import Member

    class CaptureEvents(mongo_checks.CommandEvents):
        def __init__(self):
            super().__init__()
            self.validation_failures = 0

        def succeeded(self, event):
            super().succeeded(event)
            self.validation_failures += sum(item.get("code") == 121 for item in event.reply.get("writeErrors", []))

        def failed(self, event):
            super().failed(event)
            self.validation_failures += event.failure.get("code") == 121

    mongo_checks.CommandEvents = CaptureEvents


async def setup(f, configured=None):
    configured = configured or identity_checks.settings()
    identity = IdentityStore(f.db, configured)
    session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
    owner = await identity.authenticate(session)
    keys = IngestionCredentialStore(f.db, configured)
    service = CaptureService(f.db, configured, now=lambda: NOW)
    await service.ensure_indexes()
    created = await keys.create(owner, "Synthetic exporter", 7, str(uuid4()))
    return configured, owner, keys, created, service


def body(*, count=1, seed=None, test=False, failed=False):
    seed = seed or uuid4().hex
    return {"schema_version": 1, "batch_id": str(uuid4()), "test_mode": test, "events": [
        {"observation_id": f"event-{seed}-{index}", "trace_id": "run-" + seed,
         "agent_name": "synthetic-generator", "model": "synthetic/model",
         "started_at": (NOW - timedelta(seconds=2)).isoformat(),
         "ended_at": (NOW - timedelta(seconds=1)).isoformat(),
         "status": "error" if failed and index == 0 else "success",
         "cost_usd": "0.01" if index == 0 else "0.02", "input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
        for index in range(count)]}


def batch(configured, **values):
    return decode_batch(body(**values), configured, now=NOW)


async def denied(awaitable, status, code):
    try:
        await awaitable
    except CaptureError as error:
        check(error.status_code == status, code + "_wrong_status")
    else:
        raise mongo_checks.CheckFailed(code)


async def credential_create_revoke_audit_rollback(f):
    configured = identity_checks.settings()
    identity = IdentityStore(f.db, configured)
    session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
    owner = await identity.authenticate(session)
    keys = IngestionCredentialStore(f.db, configured)
    await f.db.create_collection("guardian_identity_audit", validator={"action": "resolve_incident"})
    await denied(keys.create(owner, "Synthetic", 7, str(uuid4())), 503, "audit_failure_created_key")
    check(await f.db.guardian_ingestion_keys.count_documents({}) == 0, "failed_create_left_key")
    check(await f.db.guardian_identity_audit.count_documents({}) == 0, "failed_create_left_audit")
    await f.db.command({"collMod": "guardian_identity_audit", "validator": {"action": "create_ingestion_key"}})
    created = await keys.create(owner, "Synthetic", 7, str(uuid4()))
    await denied(keys.revoke(owner, created["credential"]["id"]), 503, "audit_failure_revoked_key")
    current = await keys.authenticate_ingestion(created["token"])
    check(current["revoked_at"] is None and current["fence"] == 0, "failed_revoke_left_partial_state")
    check(await f.db.guardian_identity_audit.count_documents({}) == 1, "failed_revoke_changed_audit")
    check(f.events.validation_failures >= 2, "audit_validator_failures_not_observed")


async def concurrent_creation_request_and_active_limit(f):
    configured, owner, keys, first, _ = await setup(f)
    request_id = str(uuid4())
    outcomes = await asyncio.gather(*(
        keys.create(owner, "One request", 7, request_id) for _ in range(6)
    ), return_exceptions=True)
    check(sum(isinstance(value, dict) for value in outcomes) == 1, "request_id_created_multiple_secrets")
    check(all(isinstance(value, dict) or isinstance(value, CaptureError) and value.status_code == 409
              for value in outcomes), "request_id_race_unexpected_failure")
    for index in range(7):
        await keys.create(owner, "Retained " + str(index), 7, str(uuid4()))
    outcomes = await asyncio.gather(keys.create(owner, "Last slot A", 7, str(uuid4())),
                                    keys.create(owner, "Last slot B", 7, str(uuid4())), return_exceptions=True)
    check(sum(isinstance(value, dict) for value in outcomes) == 1, "active_limit_race_admitted_two_keys")
    check(sum(isinstance(value, CaptureError) and value.status_code == 429 for value in outcomes) == 1,
          "active_limit_race_did_not_reject")
    check(await f.db.guardian_ingestion_keys.count_documents({}) == 10, "active_key_limit_not_exact")
    check(await f.db.guardian_identity_audit.count_documents({"action": "create_ingestion_key"}) == 10,
          "create_key_audit_not_exact")


async def concurrent_revoke_preserves_first_actor(f):
    configured = identity_checks.settings()
    configured.members["other-owner"] = Member("other-owner", "owner", "Other Owner")
    _, first_owner, keys, created, _ = await setup(f, configured)
    identity = IdentityStore(f.db, configured)
    token = await identity.create_session({"issuer": configured.issuer, "subject": "other-owner"})
    second_owner = await identity.authenticate(token)
    results = await asyncio.gather(*(
        keys.revoke(first_owner if index % 2 else second_owner, created["credential"]["id"]) for index in range(8)
    ))
    check(all(value == results[0] for value in results), "revoke_replay_changed_metadata")
    rows = await f.db.guardian_identity_audit.find({"action": "revoke_ingestion_key"}).to_list(length=2)
    check(len(rows) == 1 and rows[0]["actor"]["id"] in {first_owner.actor["id"], second_owner.actor["id"]},
          "revoke_race_lost_actor_or_duplicated_audit")
    await denied(keys.authenticate_ingestion(created["token"]), 401, "revoked_key_remained_valid")


async def ambiguous_key_commits(f):
    configured = identity_checks.settings()
    identity = IdentityStore(f.db, configured)
    session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
    owner = await identity.authenticate(session)
    keys = IngestionCredentialStore(f.db, configured)
    request_id = str(uuid4())
    await f.arm(["commitTransaction"], writeConcernError={"code": 64, "errmsg": "synthetic acknowledgement failure"},
                errorLabels=["UnknownTransactionCommitResult"])
    try:
        created = await keys.create(owner, "Synthetic", 7, request_id)
    finally:
        await f.disarm()
    row = await keys.authenticate_ingestion(created["token"])
    check(row["request_id"] == request_id and row["token_hash"] == hashlib.sha256(created["token"].encode()).hexdigest(),
          "ambiguous_create_lost_returned_secret")
    await f.arm(["commitTransaction"], writeConcernError={"code": 64, "errmsg": "synthetic acknowledgement failure"},
                errorLabels=["UnknownTransactionCommitResult"])
    try:
        revoked = await keys.revoke(owner, created["credential"]["id"])
    finally:
        await f.disarm()
    check(revoked["credential"]["status"] == "revoked", "ambiguous_revoke_not_recovered")
    check(f.events.ambiguous_commits == 2, "ambiguous_key_commits_not_observed")
    check(await f.db.guardian_ingestion_keys.count_documents({}) == 1, "ambiguous_commit_duplicated_key")
    check(await f.db.guardian_identity_audit.count_documents({}) == 2, "ambiguous_commit_duplicated_key_audit")
    stored_owner = await f.db.guardian_auth_sessions.find_one({"_id": owner.session_id})
    check(stored_owner["fence"] == 2, "ambiguous_key_commit_reexecuted_callback")


async def receipt_failure_rolls_back_all_admission(f):
    configured, _, keys, created, service = await setup(f)
    await f.db.create_collection("guardian_capture_receipts", validator={"synthetic_required": {"$exists": True}})
    payload = batch(configured, count=2)
    await denied(service.ingest(created["token"], payload), 503, "receipt_failure_acknowledged")
    for name in ("guardian_capture_inbox", "guardian_capture_receipts", "guardian_capture_admission"):
        check(await f.db[name].count_documents({}) == 0, "receipt_failure_left_" + name)
    check(await f.db.guardian_state.find_one({"_id": "direct_capture"}) is None, "receipt_failure_advanced_capture_state")
    key = await keys.authenticate_ingestion(created["token"])
    check(key["fence"] == 0 and key["last_used_at"] is None, "receipt_failure_left_credential_use")
    check(f.events.validation_failures >= 1, "receipt_validator_failure_not_observed")
    await f.db.command({"collMod": "guardian_capture_receipts", "validator": {}})
    result = await service.ingest(created["token"], payload)
    check(result["received"] == 2, "receipt_failure_recovery_lost_events")


async def concurrent_receipt_replay_and_cross_batch_identity(f):
    configured, owner, keys, first, service = await setup(f)
    second = await keys.create(owner, "Other exporter", 7, str(uuid4()))
    original = body(count=2)
    payload = decode_batch(original, configured, now=NOW)
    results = await asyncio.gather(*(
        service.ingest(first["token"] if index % 2 else second["token"], payload) for index in range(8)
    ))
    check(sum(not value["replayed"] for value in results) == 1, "same_receipt_charged_more_than_once")
    check(await f.db.guardian_capture_inbox.count_documents({}) == 2, "receipt_replay_duplicated_inbox")
    check(await f.db.guardian_capture_receipts.count_documents({}) == 1, "receipt_replay_duplicated_receipt")
    charged = await f.db.guardian_capture_admission.find({}).to_list(length=10)
    check(sorted(value["count"] for value in charged) == [1, 1, 2], "receipt_replay_charged_extra_quota")
    other_batch = {**original, "batch_id": str(uuid4())}
    replay = await service.ingest(first["token"], decode_batch(other_batch, configured, now=NOW))
    check(replay["received"] == 0 and replay["duplicate"] == 2, "cross_batch_replay_created_work")
    check(await f.db.guardian_capture_inbox.count_documents({}) == 2, "cross_batch_replay_duplicated_inbox")
    changed = {**original, "events": [{**original["events"][0], "cost_usd": "0.03"}]}
    await denied(service.ingest(first["token"], decode_batch(changed, configured, now=NOW)),
                 409, "changed_receipt_body_accepted")


async def quota_race_and_atomic_rejection(f):
    configured, owner, keys, created, service = await setup(f)
    minute = int(NOW.timestamp()) // 60
    key_counter = digest([keys.binding_id, "key:" + created["credential"]["id"], minute])
    await f.db.guardian_capture_admission.insert_one({"_id": key_counter, "count": 119, "expires_at": NOW + timedelta(minutes=3)})
    outcomes = await asyncio.gather(service.ingest(created["token"], batch(configured)),
                                    service.ingest(created["token"], batch(configured)), return_exceptions=True)
    check(sum(isinstance(value, dict) for value in outcomes) == 1, "quota_race_admitted_two_batches")
    check(sum(isinstance(value, CaptureError) and value.status_code == 429 for value in outcomes) == 1,
          "quota_race_did_not_reject")
    check((await f.db.guardian_capture_admission.find_one({"_id": key_counter}))["count"] == 120,
          "quota_race_counter_incorrect")
    check(await f.db.guardian_capture_inbox.count_documents({}) == 1, "quota_rejection_left_events")
    event_counter = digest([keys.binding_id, "project_events", minute])
    await f.db.guardian_capture_admission.update_one({"_id": event_counter}, {"$set": {"count": 6000}})
    other = await keys.create(owner, "Other exporter", 7, str(uuid4()))
    prior = await f.db.guardian_capture_admission.find({}).to_list(length=10)
    await denied(service.ingest(other["token"], batch(configured)), 429, "project_event_quota_accepted")
    after = await f.db.guardian_capture_admission.find({}).to_list(length=10)
    check(sorted(prior, key=lambda row: row["_id"]) == sorted(after, key=lambda row: row["_id"]),
          "project_event_rejection_left_earlier_counter_writes")
    check(await f.db.guardian_capture_receipts.count_documents({}) == 1, "quota_rejection_left_receipt")


async def backlog_rejection_rolls_back_proposed_event(f):
    from dataclasses import replace
    configured, _, keys, created, service = await setup(f)
    template = batch(configured).metrics[0]
    rows = []
    for index in range(10000):
        metric = replace(template, observation_id="queued-" + str(index))
        value = safe_metric(metric)
        key = metric_identity(metric, configured.connection_id)
        fingerprint = digest(value)
        rows.append({"_id": digest([key, fingerprint]), "observation_key": key, "fingerprint": fingerprint,
                     "binding_id": keys.binding_id, "connection_id": configured.connection_id,
                     "sequence": index + 1, "metric": value, "received_at": NOW, "processed": False, "processed_at": None})
    for start in range(0, len(rows), 1000):
        await f.db.guardian_capture_inbox.insert_many(rows[start:start + 1000])
    await f.db.guardian_state.insert_one({"_id": "direct_capture", "binding_id": keys.binding_id,
                                        "last_sequence": 10000, "received_events": 10000})
    await denied(service.ingest(created["token"], batch(configured)), 429, "full_backlog_admitted_event")
    check(await f.db.guardian_capture_inbox.count_documents({}) == 10000, "backlog_rejection_left_proposed_event")
    check(await f.db.guardian_capture_receipts.count_documents({}) == 0, "backlog_rejection_left_receipt")
    check(await f.db.guardian_capture_admission.count_documents({}) == 0, "backlog_rejection_charged_quota")
    check((await f.db.guardian_state.find_one({"_id": "direct_capture"}))["last_sequence"] == 10000,
          "backlog_rejection_advanced_sequence")
    check((await keys.authenticate_ingestion(created["token"]))["fence"] == 0, "backlog_rejection_left_key_touch")


async def revoke_wins_before_admission(f):
    configured, owner, keys, created, service = await setup(f)
    await keys.authenticate_ingestion(created["token"])
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.credentials.authenticate_ingestion

    async def paused(token, session=None, touch=False):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return await original(token, session=session, touch=touch)

    service.credentials.authenticate_ingestion = paused
    admitting = asyncio.create_task(service.ingest(created["token"], batch(configured)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await keys.revoke(owner, created["credential"]["id"])
        release.set()
        await denied(admitting, 401, "prechecked_revoked_key_committed_intake")
        check(await f.db.guardian_capture_inbox.count_documents({}) == 0, "revoked_admission_left_inbox")
        check(await f.db.guardian_capture_receipts.count_documents({}) == 0, "revoked_admission_left_receipt")
    finally:
        release.set()
        if not admitting.done():
            admitting.cancel()
        await asyncio.gather(admitting, return_exceptions=True)


async def intake_serializes_before_revoke(f):
    configured, owner, keys, created, service = await setup(f)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.credentials.authenticate_ingestion
    payload = batch(configured)

    async def paused(token, session=None, touch=False):
        result = await original(token, session=session, touch=touch)
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return result

    service.credentials.authenticate_ingestion = paused
    admitting = asyncio.create_task(service.ingest(created["token"], payload))
    revoking = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        revoking = asyncio.create_task(keys.revoke(owner, created["credential"]["id"]))
        done, _ = await asyncio.wait({revoking}, timeout=0.15)
        check(not done, "revoke_completed_before_older_authorized_intake_committed")
        release.set()
        check((await admitting)["received"] == 1, "authorized_first_intake_failed")
        await revoking
        service.credentials.authenticate_ingestion = original
        await denied(service.ingest(created["token"], payload), 401, "revoked_key_replayed_receipt")
        check(await f.db.guardian_capture_inbox.count_documents({}) == 1, "revoke_deleted_accepted_history")
    finally:
        release.set()
        tasks = [task for task in (admitting, revoking) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def inbox_ack_and_ledger_are_one_transaction(f):
    configured, _, _, created, service = await setup(f)
    await service.ingest(created["token"], batch(configured, failed=True))
    await f.ledger.release(f.lease)
    await f.db.command({"collMod": "guardian_capture_inbox", "validator": {"processed": False}})
    await poll_direct_once(f.db, configured)
    check(f.events.validation_failures >= 1, "inbox_ack_validator_failure_not_reached")
    check(await f.db.guardian_observations.count_documents({}) == 0, "failed_inbox_ack_committed_ledger")
    check(await f.db.guardian_capture_inbox.count_documents({"processed": False}) == 1, "failed_inbox_ack_lost_work")
    check(await f.db.guardian_metrics.count_documents({}) == 0, "failed_inbox_ack_committed_rollup")
    await f.db.command({"collMod": "guardian_capture_inbox", "validator": {}})
    await poll_direct_once(f.db, configured)
    check(await f.db.guardian_capture_inbox.count_documents({"processed": True}) == 1, "inbox_ack_recovery_did_not_complete")
    check(await f.db.guardian_observations.count_documents({}) == 1, "inbox_ack_recovery_lost_or_duplicated_ledger")
    check(await f.db.guardian_incidents.count_documents({}) == 1, "inbox_ack_recovery_did_not_detect_error")
    await poll_direct_once(f.db, configured)
    rows = await f.db.guardian_metrics.find({}).to_list(length=10)
    check(sum(row["call_count"] for row in rows) == 1, "worker_replay_duplicated_rollup")


async def initial_source_mode_claim_is_exclusive(f):
    configured = identity_checks.settings()
    identity = IdentityStore(f.db, configured)
    token = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
    owner = await identity.authenticate(token)
    keys = IngestionCredentialStore(f.db, configured)
    check(await f.db.guardian_state.find_one({"_id": "capture_binding"}) is None,
          "source_race_fixture_already_bound")
    results = await asyncio.gather(
        keys.create(owner, "Synthetic initial source", 7, str(uuid4())),
        f.ledger.claim_langfuse(f.lease), return_exceptions=True)
    successes = [not isinstance(result, BaseException) for result in results]
    check(sum(successes) == 1, "initial_source_claims_both_committed_or_both_failed")
    winner = "direct" if successes[0] else "langfuse"
    binding = await f.db.guardian_state.find_one({"_id": "capture_binding"})
    check(binding["mode"] == winner, "source_binding_does_not_match_winner")
    check(await f.db.guardian_ingestion_keys.count_documents({}) == int(successes[0]),
          "losing_source_claim_left_credential")
    check(await f.db.guardian_identity_audit.count_documents({"action": "create_ingestion_key"}) == int(successes[0]),
          "losing_source_claim_left_audit")
    if winner == "direct":
        await denied(f.ledger.claim_langfuse(f.lease), 503, "langfuse_overwrote_direct_binding")
    else:
        await denied(keys.create(owner, "Synthetic retry", 7, str(uuid4())), 503,
                     "direct_overwrote_langfuse_binding")
    check((await f.db.guardian_state.find_one({"_id": "capture_binding"}))["mode"] == winner,
          "source_binding_changed_after_rejected_retry")


@asynccontextmanager
async def http_api(f):
    import httpx
    import uvicorn
    owned_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    owned_socket.bind(("127.0.0.1", 0))
    owned_socket.listen(128)
    address = "http://127.0.0.1:" + str(owned_socket.getsockname()[1])
    configured = identity_checks.settings(issuer="http://127.0.0.1:9", public_url=address,
                                          ui_origin=address, allow_loopback_http=True)
    environment = {"PYTHON_DOTENV_DISABLED": "1", "GUARDIAN_CAPTURE_MODE": "direct", "GUARDIAN_AUTH_MODE": "oidc",
        "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "true", "GUARDIAN_OIDC_ISSUER": configured.issuer,
        "GUARDIAN_OIDC_CLIENT_ID": configured.client_id, "GUARDIAN_OIDC_CLIENT_SECRET": configured.client_secret,
        "GUARDIAN_PUBLIC_URL": address, "GUARDIAN_UI_ORIGIN": address,
        "GUARDIAN_ORGANIZATION_ID": configured.organization_id, "GUARDIAN_PROJECT_ID": configured.project_id,
        "GUARDIAN_PROJECT_NAME": configured.project_name, "GUARDIAN_ENVIRONMENT": configured.environment,
        "GUARDIAN_CONNECTION_ID": configured.connection_id, "MONGO_URL": f.suite.uri, "GUARDIAN_DB_NAME": f.name,
        "GUARDIAN_API_KEY": "synthetic-local-dashboard-key", "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([{"subject": member.subject, "role": member.role, "name": member.name}
                                                  for member in configured.members.values()])}
    server = serving = None
    try:
        with patch.dict(os.environ, environment):
            import guardian.langfuse_client as langfuse
            with patch.object(langfuse, "LangfuseTraceSource", side_effect=AssertionError("Direct mode constructed Langfuse")):
                from server import app
                import api.routes as data_routes
                import capture.routes as capture_routes
                import identity.routes as identity_routes
                with patch.object(data_routes, "db", f.db), patch.object(capture_routes, "db", f.db), patch.object(identity_routes, "db", f.db):
                    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
                    serving = asyncio.create_task(server.serve(sockets=[owned_socket]))
                    deadline = asyncio.get_running_loop().time() + 5
                    while not server.started and not serving.done() and asyncio.get_running_loop().time() < deadline:
                        await asyncio.sleep(0.01)
                    check(server.started, "owned_http_listener_did_not_start")
                    async with httpx.AsyncClient(base_url=address, timeout=10, trust_env=False) as client:
                        yield configured, client
    finally:
        if server is not None:
            server.should_exit = True
        if serving is not None:
            try:
                await asyncio.wait_for(serving, 5)
            except TimeoutError:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
        owned_socket.close()


async def real_http_intake_to_worker_metrics_and_incident(f):
    async with http_api(f) as (configured, client):
        identity = IdentityStore(f.db, configured)
        session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
        client.cookies.set(configured.session_cookie, session)
        response = await client.get("/api/guardian/access")
        check(response.status_code == 200, "real_http_named_access_failed")
        headers = {"Origin": configured.ui_origin, "X-Guardian-CSRF": response.json()["csrf_token"]}
        response = await client.post("/api/guardian/ingestion-keys", headers=headers,
                                    json={"label": "Synthetic HTTP exporter", "expires_in_days": 7, "request_id": str(uuid4())})
        check(response.status_code == 201, "real_http_owner_could_not_create_key")
        token = response.json()["token"]
        payload = body(count=2, failed=True)
        denied_count = 0
        for bad_headers in ({}, {"X-Guardian-Key": "synthetic-local-dashboard-key"}, {"Authorization": "Bearer " + token},
                            [("X-Guardian-Ingest-Key", token), ("X-Guardian-Ingest-Key", token)]):
            response = await client.post("/api/guardian/ingest/events", headers=bad_headers, json=payload)
            check(response.status_code == 401, "real_http_ingest_accepted_other_authority")
            denied_count += 1
        machine = {"X-Guardian-Ingest-Key": token}
        test_payload = {**payload, "test_mode": True, "batch_id": str(uuid4())}
        response = await client.post("/api/guardian/ingest/events", headers=machine, json=test_payload)
        check(response.status_code == 202 and response.json()["processing"] == "test_only", "real_http_test_intake_failed")
        check(await f.db.guardian_capture_inbox.count_documents({}) == 0, "test_handshake_created_production_work")
        response = await client.post("/api/guardian/ingest/events", headers=machine, json=payload)
        check(response.status_code == 202 and response.json()["received"] == 2, "real_http_real_intake_failed")
        response = await client.get("/api/guardian/capture")
        check(response.status_code == 200 and response.json()["status"]["pending_events"] == 2
              and response.json()["status"]["processed_events"] == 0, "real_http_stopped_worker_backlog_not_visible")
        response = await client.post("/api/guardian/ingest/events", headers=machine, json=payload)
        check(response.status_code == 202 and response.json()["replayed"], "real_http_receipt_replay_failed")
        await f.ledger.release(f.lease)
        await poll_direct_once(f.db, configured)
        response = await client.get("/api/guardian/metrics")
        check(response.status_code == 200, "real_http_metrics_unavailable")
        points = response.json()
        check(sum(row["call_count"] for row in points) == 2, "real_http_metrics_did_not_reconcile_calls")
        check(abs(sum(row["total_cost_usd"] for row in points) - 0.03) < 1e-12, "real_http_metrics_did_not_reconcile_cost")
        response = await client.get("/api/guardian/incidents")
        check(response.status_code == 200 and len(response.json()) == 1, "real_http_error_incident_missing")
        check(response.json()[0]["trace_urls"] == [], "direct_incident_invented_vendor_link")
        response = await client.get("/api/guardian/live/runs/" + payload["events"][0]["trace_id"])
        check(response.status_code == 200 and len(response.json()["calls"]) == 2, "real_http_internal_run_evidence_missing")
        response = await client.get("/api/guardian/capture")
        status = response.json()["status"]
        check(response.status_code == 200 and status["pending_events"] == 0 and status["processed_events"] == 2,
              "real_http_processing_status_did_not_reconcile")
        f.suite.details["actual_http"] = {"auth_denials": denied_count, "received_events": 2,
            "processed_events": 2, "call_count": 2, "total_cost_usd": 0.03, "incidents": 1,
            "test_mode_separate": True, "langfuse_constructed": False, "transport": "localhost_http"}


async def run_suite(uri):
    suite = mongo_checks.Suite(uri)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        for name, test in (
            ("credential_audit_rollback", credential_create_revoke_audit_rollback),
            ("credential_request_and_limit_race", concurrent_creation_request_and_active_limit),
            ("concurrent_revoke_actor", concurrent_revoke_preserves_first_actor),
            ("ambiguous_key_commits", ambiguous_key_commits),
            ("receipt_admission_rollback", receipt_failure_rolls_back_all_admission),
            ("receipt_and_cross_batch_replay", concurrent_receipt_replay_and_cross_batch_identity),
            ("quota_race_and_rejection_rollback", quota_race_and_atomic_rejection),
            ("backlog_rejection_rollback", backlog_rejection_rolls_back_proposed_event),
            ("revoke_wins_before_admission", revoke_wins_before_admission),
            ("intake_serializes_before_revoke", intake_serializes_before_revoke),
            ("worker_ledger_ack_atomicity", inbox_ack_and_ledger_are_one_transaction),
            ("initial_source_mode_claim_exclusive", initial_source_mode_claim_is_exclusive),
            ("actual_http_intake_worker_metrics_incident", real_http_intake_to_worker_metrics_and_incident),
        ):
            await suite.run(name, test)
        failed = sum(result["status"] != "passed" for result in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
            "finished_at": datetime.now(timezone.utc).isoformat(), "passed": len(suite.results) - failed,
            "failed": failed, "cleanup_complete": not suite.owned,
            "duration_seconds": round(asyncio.get_running_loop().time() - started, 3),
            "tests": suite.results, "evidence": suite.details}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only guardian-r102 replica-set URI")
    parser.add_argument("--report", help="Optional safe JSON artifact under tools/reports")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    report = None
    try:
        uri = mongo_checks.validate_url(args.mongo_url)
        if args.report:
            candidate = Path(args.report).resolve()
            check(candidate.is_relative_to((mongo_checks.ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
            report = candidate
        load_dependencies()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, mongo_checks.CheckFailed):
            result["code"] = str(error)
    rendered = json.dumps(result, indent=2)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
