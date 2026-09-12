#!/usr/bin/env python
"""Synthetic notification journeys through localhost HTTP and marker-owned Mongo.

No arguments or --help require only the standard library and perform no work.
Execution requires an explicit localhost guardian-r102 replica. Every case owns
a random, marked database. An injected HTTP boundary routes synthetic Slack
requests to this process's loopback receiver; no Slack account or message is used.
No .env files, existing application data, credentials or receiver text enter reports.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_WEBHOOK = "https://hooks.slack.com/services/SYNTHETIC/LOCAL/NOT-A-REAL-SECRET"
DELIVERIES = "guardian_notification_deliveries"
HEADS = "guardian_notification_settings"
AUDIT = "guardian_identity_audit"
CANARY = "synthetic-private-content-must-not-be-notified"


def dependencies():
    sys.path.insert(0, str(ROOT / "tools"))
    global mongo, capture, identity, policies, NotificationStore, NotificationError, notification_settings
    global worker, SlackTransport, DeliveryResult, httpx
    import test_mongo_ledger as mongo
    import test_mongo_capture as capture
    import test_mongo_identity as identity
    import test_mongo_policies as policies
    policies.dependencies()
    from notifications.control import NotificationStore
    from notifications.errors import NotificationError
    from notifications import settings as notification_settings, worker
    from notifications.transport import SlackTransport, DeliveryResult
    import httpx


class LocalReceiver:
    """Owned bounded HTTP receiver; all retained requests contain synthetic data."""
    def __init__(self):
        self.server = None
        self.tasks = set()
        self.requests = []
        self.mode = "ok"
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=16384)
        self.url = "http://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1]) + "/synthetic-slack"
        return self

    async def __aexit__(self, *_):
        self.release.set()
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout(15):
                header = await reader.readuntil(b"\r\n\r\n")
                fields = dict(line.split(b":", 1) for line in header.split(b"\r\n")[1:-2])
                fields = {key.lower(): value.strip() for key, value in fields.items()}
                size = int(fields.get(b"content-length", b"0"))
                if not 0 < size <= 16384:
                    return
                payload = json.loads(await reader.readexactly(size))
                self.requests.append(payload)
                self.entered.set()
                mode = self.mode
                if mode == "hold":
                    await self.release.wait()
                if mode == "disconnect":
                    return
                status, body, extra = 200, b"ok", b""
                if mode == "rate":
                    status, body, extra = 429, CANARY.encode(), b"Retry-After: 3\r\n"
                elif mode == "reject":
                    status, body = 403, CANARY.encode()
                elif mode == "large":
                    body = b"x" * 9000
                writer.write(b"HTTP/1.1 " + str(status).encode() + b" Synthetic\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\nConnection: close\r\n" + extra + b"\r\n" + body)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)

    def transport(self):
        """Only a test-injected network adapter can replace the trusted Slack URL."""
        local_url = self.url

        class LoopbackTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.inner = httpx.AsyncHTTPTransport(retries=0)

            async def handle_async_request(self, request):
                mongo.check(str(request.url) == SYNTHETIC_WEBHOOK, "unexpected_transport_destination")
                local = httpx.Request(request.method, local_url,
                    headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
                    content=await request.aread(), extensions=request.extensions)
                return await self.inner.handle_async_request(local)

            async def aclose(self):
                await self.inner.aclose()

        return SlackTransport(http_transport=LoopbackTransport())


@asynccontextmanager
async def http_api(f):
    with patch.dict(os.environ, {"GUARDIAN_SLACK_WEBHOOK_URL": SYNTHETIC_WEBHOOK}):
        async with policies.http_api(f) as values:
            import notifications.routes as routes
            with patch.object(routes, "db", f.db):
                yield values


async def setup(f):
    configured, _, _, actor = await policies.owner(f)
    with patch.dict(os.environ, {"GUARDIAN_SLACK_WEBHOOK_URL": SYNTHETIC_WEBHOOK}):
        destination = notification_settings.load_notification_settings(configured)
    return configured, actor, destination, NotificationStore(f.db, configured, destination)


async def command(store, actor, revision, action, delivery_id=None, request_id=None):
    return await store.command(actor, revision, request_id or str(uuid4()), action, delivery_id)


async def denied(awaitable, status, diagnostic):
    try:
        await awaitable
    except Exception as error:
        mongo.check(isinstance(error, (NotificationError, identity.IdentityError))
                    and error.status_code == status, diagnostic + "_wrong_error")
    else:
        raise mongo.CheckFailed(diagnostic)


async def actual_http_customer_path(f):
    async with http_api(f) as (configured, client), LocalReceiver() as receiver:
        _, actor, headers = await policies.http_owner(f, configured, client)
        destination = notification_settings.load_notification_settings(configured)
        current = await client.get("/api/guardian/notifications")
        mongo.check(current.status_code == 200 and current.json()["revision"] == 0
                    and current.json()["can_manage"] and not current.json()["destination"]["verified"],
                    "initial_owner_notification_state_incorrect")
        url = "/api/guardian/notifications/actions"
        body = {"expected_revision": 0, "request_id": str(uuid4()), "action": "test"}
        denied_response = await client.post(url, headers={"Origin": configured.ui_origin}, json=body)
        mongo.check(denied_response.status_code == 403 and await f.db[DELIVERIES].count_documents({}) == 0,
                    "missing_csrf_queued_notification")
        queued = await client.post(url, headers=headers, json=body)
        mongo.check(queued.status_code == 200 and queued.json()["revision"] == 1
                    and queued.json()["deliveries"][0]["state"] == "queued" and not receiver.requests,
                    "owner_test_not_durably_queued_before_network")
        replayed = await client.post(url, headers=headers, json=body)
        mongo.check(replayed.status_code == 200 and replayed.json()["revision"] == 1
                    and await f.db[DELIVERIES].count_documents({}) == 1, "test_command_replay_duplicated_job")
        early = await client.post(url, headers=headers,
            json={"expected_revision": 1, "request_id": str(uuid4()), "action": "enable"})
        mongo.check(early.status_code == 409, "enabled_before_receiver_acceptance")
        await worker.process_once(f.db, configured, destination, transport=receiver.transport())
        accepted = await client.get("/api/guardian/notifications")
        mongo.check(accepted.status_code == 200 and accepted.json()["destination"]["verified"]
                    and not accepted.json()["destination"]["enabled"]
                    and accepted.json()["deliveries"][0]["state"] == "accepted", "accepted_test_not_verified")
        enabled = await client.post(url, headers=headers,
            json={"expected_revision": 1, "request_id": str(uuid4()), "action": "enable"})
        mongo.check(enabled.status_code == 200 and enabled.json()["destination"]["enabled"], "owner_enable_failed")
        credential = await client.post("/api/guardian/ingestion-keys", headers=headers,
            json={"label": "Synthetic notification proof", "expires_in_days": 7, "request_id": str(uuid4())})
        mongo.check(credential.status_code == 201, "notification_fixture_credential_failed")
        token = credential.json()["token"]
        batch = policies.envelope([policies.event("notification-error", cost="0.02", status="error")])
        batch["events"][0]["agent_name"] = CANARY
        receipt = await client.post("/api/guardian/ingest/events", headers={"X-Guardian-Ingest-Key": token}, json=batch)
        mongo.check(receipt.status_code == 202, "notification_fixture_intake_failed")
        await f.ledger.release(f.lease)
        await capture.poll_direct_once(f.db, configured)
        incidents = await client.get("/api/guardian/incidents")
        mongo.check(incidents.status_code == 200 and len(incidents.json()) == 1, "reported_error_missing_incident")
        incident = incidents.json()[0]
        mongo.check(await f.db[DELIVERIES].count_documents({"kind": "incident"}) == 1, "incident_missing_atomic_outbox")
        # Pacing is production behavior; wait once before the second actual send.
        await asyncio.sleep(1.05)
        await worker.process_once(f.db, configured, destination, transport=receiver.transport())
        history = await client.get("/api/guardian/notifications", params={"incident_id": incident["id"]})
        mongo.check(history.status_code == 200 and len(history.json()["deliveries"]) == 1
                    and history.json()["deliveries"][0]["state"] == "accepted", "incident_delivery_history_missing")
        mongo.check(len(receiver.requests) == 2 and incident["id"] in receiver.requests[1]["text"]
                    and "/incidents/" + incident["id"] in receiver.requests[1]["text"], "receiver_incident_link_missing")
        mongo.check(CANARY in json.dumps(incident) and CANARY not in json.dumps(receiver.requests),
                    "receiver_payload_leaked_source_label")
        run = await client.get("/api/guardian/live/runs/" + batch["events"][0]["trace_id"])
        mongo.check(run.status_code == 200 and len(run.json()["calls"]) == 1, "notification_link_run_evidence_missing")
        resolved = await client.post("/api/guardian/incidents/" + incident["id"] + "/resolve", headers=headers)
        mongo.check(resolved.status_code == 200 and resolved.json()["status"] == "resolved", "notification_resolve_failed")
        await client.post("/api/guardian/ingest/events", headers={"X-Guardian-Ingest-Key": token}, json=batch)
        await capture.poll_direct_once(f.db, configured)
        final = await client.get("/api/guardian/incidents/" + incident["id"])
        mongo.check(final.status_code == 200 and final.json()["status"] == "resolved"
                    and await f.db[DELIVERIES].count_documents({}) == 2, "replay_reopened_or_renotified_incident")
        for name in (HEADS, DELIVERIES, "guardian_notification_commands", AUDIT):
            stored = json.dumps(await f.db[name].find({}).to_list(100), default=str)
            mongo.check(SYNTHETIC_WEBHOOK not in stored and token not in stored and CANARY not in stored,
                        "notification_storage_secret_leak")
        mongo.check(SYNTHETIC_WEBHOOK not in history.text and "payload" not in history.text,
                    "notification_public_history_private_fields")
        f.suite.details["customer_path"] = {"api_transport": "localhost_http", "receiver_transport": "localhost_http",
            "test_accepted_before_enable": True, "incident_deliveries": 1, "receiver_requests": 2,
            "resolved_after_replay": True, "actual_slack_messages": 0}


async def audit_failure_and_concurrent_commands(f):
    _, actor, _, store = await setup(f)
    await f.db.create_collection(AUDIT, validator={"synthetic_required_field": {"$exists": True}})
    await denied(command(store, actor, 0, "test"), 503, "audit_failure_committed_notification")
    mongo.check(await f.db[DELIVERIES].count_documents({}) == 0
                and (await store.get(actor))["revision"] == 0, "notification_audit_rollback_incomplete")
    await f.db.command({"collMod": AUDIT, "validator": {}})
    outcomes = await asyncio.gather(command(store, actor, 0, "test"), command(store, actor, 0, "test"),
                                   return_exceptions=True)
    winners = [value for value in outcomes if isinstance(value, dict)]
    losers = [value for value in outcomes if isinstance(value, NotificationError)]
    mongo.check(len(winners) == len(losers) == 1 and losers[0].status_code == 409
                and await f.db[DELIVERIES].count_documents({}) == 1
                and await f.db[AUDIT].count_documents({"action": "notification_test"}) == 1,
                "concurrent_notification_command_not_single_winner")


async def accept_test(f, configured, actor, destination, store):
    queued = await command(store, actor, 0, "test")
    moment = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
    claim = await worker.claim_next(f.db, configured, destination, now=moment)
    mongo.check(claim is not None and await worker.complete_attempt(f.db, configured, destination, claim,
        DeliveryResult("accepted", accepted=True), now=moment), "synthetic_test_settlement_failed")
    return queued, moment


async def concurrent_claim_and_stale_ack(f):
    configured, actor, destination, store = await setup(f)
    await command(store, actor, 0, "test")
    moment = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
    claims = await asyncio.gather(*(worker.claim_next(f.db, configured, destination, now=moment,
                                    owner="synthetic-worker-" + str(i)) for i in range(2)))
    claims = [claim for claim in claims if claim is not None]
    mongo.check(len(claims) == 1, "concurrent_workers_admitted_same_destination")
    old = claims[0]
    expired = moment + timedelta(seconds=worker.LEASE_SECONDS + 1)
    mongo.check(not await worker.complete_attempt(f.db, configured, destination, old,
        DeliveryResult("accepted", accepted=True), now=expired), "expired_attempt_acknowledgement_committed")
    mongo.check(await worker.claim_next(f.db, configured, destination, now=expired) is None,
                "crash_recovery_skipped_backoff")
    recovering = await f.db[DELIVERIES].find_one({"_id": old["_id"]})
    mongo.check(recovering["state"] == "retrying" and recovering["attempts"][0]["outcome"] == "worker_lost_unconfirmed",
                "crash_recovery_lost_unconfirmed_history")
    replacement = await worker.claim_next(f.db, configured, destination, now=expired + timedelta(seconds=2))
    mongo.check(replacement is not None and replacement["claim_epoch"] > old["claim_epoch"],
                "replacement_worker_did_not_advance_fence")
    mongo.check(not await worker.complete_attempt(f.db, configured, destination, old,
        DeliveryResult("accepted", accepted=True), now=expired + timedelta(seconds=2)), "stale_ack_overwrote_replacement")
    mongo.check(await worker.complete_attempt(f.db, configured, destination, replacement,
        DeliveryResult("accepted", accepted=True), now=expired + timedelta(seconds=2)), "replacement_ack_rejected")
    final = await f.db[DELIVERIES].find_one({"_id": old["_id"]})
    mongo.check(final["state"] == "accepted" and final["attempt_count"] == 2
                and [row["outcome"] for row in final["attempts"]] == ["worker_lost_unconfirmed", "accepted"],
                "fenced_delivery_history_incorrect")


async def actual_transport_retry_timeout_and_redaction(f):
    configured, actor, destination, store = await setup(f)
    await command(store, actor, 0, "test")
    moment = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
    async with LocalReceiver() as receiver:
        receiver.mode = "rate"
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment)
        row = await f.db[DELIVERIES].find_one({})
        mongo.check(row["state"] == "retrying" and row["last_outcome"] == "rate_limited"
                    and worker.outbox.utc(row["next_attempt_at"]) >= moment + timedelta(seconds=3), "retry_after_not_respected")
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=2))
        mongo.check(len(receiver.requests) == 1, "receiver_retry_sent_before_hint")
        receiver.mode = "reject"
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=4))
        row = await f.db[DELIVERIES].find_one({})
        mongo.check(row["state"] == "failed" and row["next_attempt_at"] is None and row["last_outcome"] == "receiver_rejected",
                    "terminal_receiver_rejection_was_retried")
        requests_before = len(receiver.requests)
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=5))
        mongo.check(len(receiver.requests) == requests_before, "terminal_receiver_rejection_automatically_sent_again")
        retried = await command(store, actor, 1, "retry", delivery_id=row["_id"])
        mongo.check(retried["revision"] == 2 and retried["deliveries"][0]["cycle"] == 2,
                    "owner_could_not_retry_after_receiver_permissions_fix")
        receiver.mode = "ok"
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=6))
        recovered = await f.db[DELIVERIES].find_one({"_id": row["_id"]})
        mongo.check(recovered["state"] == "accepted" and recovered["cycle"] == 2
                    and await f.db[AUDIT].count_documents({"action": "notification_retry"}) == 1,
                    "owner_receiver_recovery_missing_acceptance_or_audit")
        await command(store, actor, 2, "test")
        receiver.mode = "hold"
        receiver.entered.clear()
        import notifications.transport as transport_module
        started = asyncio.get_running_loop().time()
        with patch.object(transport_module, "TOTAL_SECONDS", 0.1), patch.object(worker, "TOTAL_SECONDS", 0.2):
            await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=8))
        elapsed = asyncio.get_running_loop().time() - started
        timed = await f.db[DELIVERIES].find_one({"state": "retrying"})
        mongo.check(timed is not None and timed["last_outcome"] == "timeout_unconfirmed"
                    and receiver.entered.is_set() and elapsed < 3, "actual_http_timeout_not_bounded_unconfirmed")
        receiver.release.set()
        receiver.mode = "large"
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=10))
        large = await f.db[DELIVERIES].find_one({"_id": timed["_id"]})
        mongo.check(large["last_outcome"] == "response_too_large" and large["state"] == "retrying", "response_limit_not_enforced")
        receiver.mode = "ok"
        await worker.process_once(f.db, configured, destination, transport=receiver.transport(), now=moment + timedelta(seconds=13))
        final = await store.get(actor)
        mongo.check(final["destination"]["verified"] and CANARY not in json.dumps(final), "receiver_body_persisted_or_acceptance_missing")
        stored = json.dumps(await f.db[DELIVERIES].find({}).to_list(20), default=str)
        mongo.check(CANARY not in stored and SYNTHETIC_WEBHOOK not in stored, "private_receiver_text_or_secret_persisted")
        f.suite.details["http_failure_boundaries"] = {"rate_hint_seconds": 3, "early_retry_requests": 0,
            "terminal_rejection_stops_automatic_retry": True, "audited_owner_retry_after_rejection_accepted": True,
            "deadline_test_seconds": 0.1, "unconfirmed_timeout": True,
            "response_bytes_limit_enforced": True, "raw_receiver_text_persisted": False}


async def incident_outbox_atomic_rollback(f):
    async with http_api(f) as (configured, client):
        _, actor, headers = await policies.http_owner(f, configured, client)
        destination = notification_settings.load_notification_settings(configured)
        store = NotificationStore(f.db, configured, destination)
        await accept_test(f, configured, actor, destination, store)
        await command(store, actor, 1, "enable")
        response = await client.post("/api/guardian/ingestion-keys", headers=headers,
            json={"label": "Synthetic rollback proof", "expires_in_days": 7, "request_id": str(uuid4())})
        mongo.check(response.status_code == 201, "rollback_fixture_key_failed")
        await client.post("/api/guardian/ingest/events", headers={"X-Guardian-Ingest-Key": response.json()["token"]},
            json=policies.envelope([policies.event("rollback-error", cost="0.01", status="error")]))
        await f.db.command({"collMod": DELIVERIES, "validator": {"kind": {"$ne": "incident"}}})
        await f.ledger.release(f.lease)
        await capture.poll_direct_once(f.db, configured)
        mongo.check(await f.db.guardian_incidents.count_documents({}) == 0
                    and await f.db[DELIVERIES].count_documents({"kind": "incident"}) == 0
                    and await f.db.guardian_observations.count_documents({"state": "accepted", "pending": True}) == 1,
                    "outbox_failure_committed_incident_or_completed_observation")
        await f.db.command({"collMod": DELIVERIES, "validator": {}})
        await capture.poll_direct_once(f.db, configured)
        mongo.check(await f.db.guardian_incidents.count_documents({}) == 1
                    and await f.db[DELIVERIES].count_documents({"kind": "incident"}) == 1,
                    "outbox_recovery_lost_incident_or_delivery")
        await capture.poll_direct_once(f.db, configured)
        mongo.check(await f.db[DELIVERIES].count_documents({"kind": "incident"}) == 1, "outbox_recovery_replay_duplicated_delivery")


async def disable_and_destination_rotation(f):
    configured, actor, destination, store = await setup(f)
    await accept_test(f, configured, actor, destination, store)
    await command(store, actor, 1, "enable")
    # A queued synthetic incident uses the real outbox shape; this case tests
    # delivery fencing. The separate HTTP case proves actual incident insertion.
    test = await f.db[DELIVERIES].find_one({})
    copied = {**test, "_id": "d" * 64, "kind": "incident", "incident_id": "signal_v1_" + "e" * 64,
        "state": "queued", "attempt_count": 0, "cycle_attempts": 0, "attempts": [],
        "next_attempt_at": datetime.now(timezone.utc), "last_outcome": None}
    await f.db[DELIVERIES].insert_one(copied)
    disabled = await command(store, actor, 2, "disable")
    mongo.check(not disabled["destination"]["enabled"]
                and (await f.db[DELIVERIES].find_one({"_id": copied["_id"]}))["state"] == "cancelled",
                "disable_did_not_cancel_queued_incident")
    await command(store, actor, 3, "test")
    with patch.dict(os.environ, {"GUARDIAN_SLACK_WEBHOOK_URL": SYNTHETIC_WEBHOOK + "-ROTATED"}):
        rotated = notification_settings.load_notification_settings(configured)
    new_store = NotificationStore(f.db, configured, rotated)
    changed = await new_store.get(actor)
    mongo.check(changed["destination"]["state"] == "changed" and not changed["destination"]["verified"]
                and not changed["destination"]["enabled"], "rotation_reused_old_destination_authority")
    mongo.check(await worker.claim_next(f.db, configured, rotated, now=datetime.now(timezone.utc) + timedelta(seconds=5)) is None,
                "rotation_claimed_old_destination_work")
    mongo.check(await f.db[DELIVERIES].count_documents({"state": {"$in": ["queued", "retrying"]}}) == 0,
                "rotation_left_old_queued_work_deliverable")
    await denied(command(new_store, actor, 4, "enable"), 409, "rotated_destination_enabled_without_test")


async def logout_command_ordering(f):
    configured, actor, destination, store = await setup(f)
    # Precreate the namespace so this is a document-write ordering check rather
    # than Mongo's separately tested first-collection catalog creation race.
    await f.db.create_collection(HEADS)
    entered, release = asyncio.Event(), asyncio.Event()
    proxy = policies.DatabaseProxy(f.db, "guardian_auth_sessions",
        policies.PauseWrite(f.db.guardian_auth_sessions, entered, release, after=True))
    action = asyncio.create_task(command(NotificationStore(proxy, configured, destination), actor, 0, "test"))
    logout = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        logout = asyncio.create_task(capture.IdentityStore(f.db, configured).logout(actor))
        done, _ = await asyncio.wait({logout}, timeout=0.1)
        mongo.check(not done, "logout_bypassed_notification_authority_write")
        release.set()
        # The mutation commits before releasing its authority write. Its separate
        # authenticated read-back may lose to logout and correctly return 401.
        # Prove durable ordering without requiring post-logout read authority.
        try:
            acknowledgement = await action
            mongo.check(acknowledgement["revision"] == 1, "admitted_owner_command_not_committed")
        except identity.IdentityError as error:
            mongo.check(error.status_code == 401, "notification_readback_failed_unexpectedly")
        await logout
        await denied(command(store, actor, 1, "disable"), 401, "logged_out_actor_changed_notification_state")
        mongo.check((await f.db[HEADS].find_one({}))["revision"] == 1
                    and await f.db[DELIVERIES].count_documents({}) == 1
                    and await f.db.guardian_notification_commands.count_documents({}) == 1
                    and await f.db[AUDIT].count_documents({"action": "notification_test"}) == 1,
                    "logout_ordering_duplicated_or_removed_admitted_command")
    finally:
        await policies.stop_tasks(release, action, logout)


async def run_suite(uri):
    suite = mongo.Suite(uri)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        for name, function in (("owner_http_test_enable_incident_delivery_resolve_replay", actual_http_customer_path),
                ("notification_audit_rollback_and_concurrent_commands", audit_failure_and_concurrent_commands),
                ("concurrent_claim_crash_recovery_and_stale_ack", concurrent_claim_and_stale_ack),
                ("actual_http_retry_after_timeout_response_cap_redaction", actual_transport_retry_timeout_and_redaction),
                ("incident_outbox_and_completion_atomic_rollback", incident_outbox_atomic_rollback),
                ("disable_and_destination_rotation_fencing", disable_and_destination_rotation),
                ("logout_and_notification_command_transaction_order", logout_command_ordering)):
            await suite.run(name, function)
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
        sys.path.insert(0, str(ROOT / "tools"))
        import test_mongo_ledger as safe_mongo
        uri = safe_mongo.validate_url(args.mongo_url)
        if args.report:
            candidate = Path(args.report).resolve()
            safe_mongo.check(candidate.is_relative_to((ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
            report = candidate
        dependencies()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("guardian.incident_engine").setLevel(logging.WARNING)
        result = asyncio.run(run_suite(uri))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if "safe_mongo" in locals() and isinstance(error, safe_mongo.CheckFailed):
            result["code"] = str(error)
    rendered = json.dumps(result, indent=2)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
