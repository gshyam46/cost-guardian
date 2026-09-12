"""Delivery semantics with explicit mock transactions and isolated transports.

These unit checks cannot establish Mongo rollback or replica-set claim ordering;
the independent real-Mongo harness covers those properties.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.detectors import reliability_anomaly
from guardian.incident import Incident
from guardian.ledger import ObservationLedger
from guardian.models import TraceMetric
from guardian.store import MongoIncidentStore
from identity.settings import Member, Settings
from identity.store import IdentityStore
from notifications import outbox, worker
from notifications.control import NotificationStore, read_head, collection as head_collection
from notifications.errors import NotificationError
from notifications.settings import load_notification_settings
from notifications.transport import DeliveryResult

pytestmark = pytest.mark.anyio
CANARY = "secret-content-and-webhook-must-not-be-retained"


class Clock:
    def __init__(self):
        self.value = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class Sender:
    def __init__(self, *results):
        self.results = list(results) or [DeliveryResult("accepted", accepted=True)]
        self.payloads = []

    async def send(self, configuration, payload):
        self.payloads.append(json.dumps(payload, sort_keys=True))
        return self.results[min(len(self.payloads) - 1, len(self.results) - 1)]


@pytest.fixture
async def environment(monkeypatch):
    db = AsyncMongoMockClient(tz_aware=True)["notification_delivery"]
    clock = Clock()
    settings = Settings(mode="oidc", issuer="https://issuer.example.invalid", client_id="client",
        organization_id="organization", project_id="project", environment="test", connection_id="primary",
        ui_origin="https://guardian.example.invalid", members={"owner": Member("owner", "owner", "Owner")})
    monkeypatch.setenv("GUARDIAN_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/TEST/CHANNEL/" + CANARY)
    configuration = load_notification_settings(settings)
    identity = IdentityStore(db, settings, now=clock)
    token = await identity.create_session({"issuer": settings.issuer, "subject": "owner"})
    principal = await identity.authenticate(token)
    head = await read_head(db, settings.connection_id, create=True)
    head.update(revision=1, binding_id=identity.binding_id, destination_id=configuration.destination_id,
                verified_at=clock().isoformat(), enabled=True, updated_at=clock().isoformat())
    await head_collection(db).replace_one({"_id": head["_id"]}, head)
    monkeypatch.setattr(outbox, "load_settings", lambda: settings)
    monkeypatch.setattr(outbox, "utcnow", clock)
    return SimpleNamespace(db=db, settings=settings, configuration=configuration, clock=clock,
        principal=principal, control=NotificationStore(db, settings, configuration, now=clock))


def incident(number=1):
    return Incident(id="signal_v1_" + f"{number:064x}", detector="cost_anomaly", severity="high",
        title=CANARY, summary=CANARY, evidence={"private": CANARY}, trace_ids=[CANARY], agent_name=CANARY)


async def enqueue(env, number=1):
    await outbox.enqueue_created(env.db, env.settings.connection_id, [incident(number)], None)
    return await outbox.collection(env.db).find_one({"incident_id": incident(number).id})


async def row(env, identifier):
    return await outbox.collection(env.db).find_one({"_id": identifier})


async def process(env, sender):
    return await worker.process_once(env.db, env.settings, env.configuration, transport=sender, now=env.clock)


async def test_outbox_and_public_history_exclude_all_arbitrary_incident_content(environment):
    env = environment
    delivery = await enqueue(env)
    assert CANARY not in json.dumps(delivery, default=str)
    assert env.configuration.webhook_url not in json.dumps(delivery, default=str)
    assert "/incidents/" + incident().id in delivery["payload"]["text"]
    sender = Sender()
    assert await process(env, sender) == 1
    public, more = await outbox.recent_deliveries(env.db, "primary", env.configuration.destination_id, can_manage=True)
    assert not more and public[0]["state"] == "accepted"
    assert public[0]["attempts"][0]["outcome"] == "accepted"
    assert not {"payload", "destination_id", "binding_id", "claim_owner", "claim_epoch"} & public[0].keys()
    assert CANARY not in json.dumps(public)


async def test_ledger_replay_and_resolved_incident_do_not_enqueue_again(environment):
    env = environment
    ledger = ObservationLedger(env.db)
    lease = await ledger.acquire("worker")
    candidate = TraceMetric(trace_id="run", observation_id="call", project_id="project", agent_name="agent", model="model",
        cost_usd=None, total_tokens=None, latency_ms=None, status="error", timestamp=env.clock())
    try:
        await ledger.ingest_metrics([candidate], lease)
        assert await ledger.process_pending(lease, [reliability_anomaly]) == (1, 0)
        saved = await env.db.guardian_incidents.find_one({})
        await MongoIncidentStore(env.db).resolve(saved["id"])
        await ledger.ingest_metrics([candidate], lease)
        assert await ledger.process_pending(lease, [reliability_anomaly]) == (0, 0)
    finally:
        await ledger.release(lease)
    assert await outbox.collection(env.db).count_documents({}) == 1
    assert (await env.db.guardian_incidents.find_one({}))["status"] == "resolved"


async def test_enqueue_capacity_failure_does_not_finish_detector_work(environment, monkeypatch):
    env = environment
    await enqueue(env)
    monkeypatch.setattr(outbox, "MAX_PENDING", 1)
    ledger = ObservationLedger(env.db)
    lease = await ledger.acquire("worker")
    candidate = TraceMetric(trace_id="run", observation_id="call", project_id="project", agent_name="agent", model="model",
        cost_usd=None, total_tokens=None, latency_ms=None, status="error", timestamp=env.clock())
    try:
        await ledger.ingest_metrics([candidate], lease)
        with pytest.raises(NotificationError) as failure:
            await ledger.process_pending(lease, [reliability_anomaly])
        assert failure.value.code == "notification_queue_full"
    finally:
        await ledger.release(lease)
    observation = await env.db.guardian_observations.find_one({})
    assert observation["pending"] is True and observation["completed_rules"] == []
    # Incident rollback is deliberately not asserted against a mock transaction.


async def test_destination_pacing_serializes_simultaneous_claims(environment):
    env = environment
    await enqueue(env, 1)
    await enqueue(env, 2)
    first = await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock)
    assert first is not None
    assert await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock) is None
    await worker.complete_attempt(env.db, env.settings, env.configuration, first,
        DeliveryResult("accepted", accepted=True), now=env.clock)
    assert await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock) is None
    env.clock.advance(1)
    assert await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock) is not None


async def test_expired_attempt_is_unconfirmed_and_late_ack_cannot_settle_new_epoch(environment):
    env = environment
    initial = await enqueue(env)
    first = await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock, owner="first")
    env.clock.advance(worker.LEASE_SECONDS + 1)
    assert await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock) is None
    recovered = await row(env, initial["_id"])
    assert recovered["state"] == "retrying"
    assert recovered["attempts"][0]["outcome"] == "worker_lost_unconfirmed"
    env.clock.advance(1)
    second = await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock, owner="second")
    assert second["claim_epoch"] > first["claim_epoch"]
    assert not await worker.complete_attempt(env.db, env.settings, env.configuration, first,
        DeliveryResult("accepted", accepted=True), now=env.clock)
    assert (await row(env, initial["_id"]))["state"] == "sending"
    assert await worker.complete_attempt(env.db, env.settings, env.configuration, second,
        DeliveryResult("accepted", accepted=True), now=env.clock)


async def test_retry_after_pauses_every_job_for_destination(environment):
    env = environment
    await enqueue(env, 1)
    await enqueue(env, 2)
    sender = Sender(DeliveryResult("rate_limited", retryable=True, retry_after=60), DeliveryResult("accepted", accepted=True))
    assert await process(env, sender) == 0
    env.clock.advance(1)
    assert await process(env, sender) == 0
    env.clock.advance(58)
    assert await process(env, sender) == 0
    assert len(sender.payloads) == 1
    env.clock.advance(1)
    assert await process(env, sender) == 1


async def test_retry_preserves_identical_payload_and_has_five_attempt_cycle_limit(environment):
    env = environment
    delivery = await enqueue(env)
    sender = Sender(DeliveryResult("network_unconfirmed", retryable=True, unconfirmed=True))
    for _ in range(5):
        assert await process(env, sender) == 0
        env.clock.advance(20)
    saved = await row(env, delivery["_id"])
    assert saved["state"] == "unconfirmed" and saved["attempt_count"] == 5
    assert saved["last_outcome"] == "attempts_exhausted"
    assert len(set(sender.payloads)) == 1
    assert await process(env, sender) == 0 and len(sender.payloads) == 5
    public, _ = await outbox.recent_deliveries(env.db, "primary", env.configuration.destination_id, can_manage=True)
    assert public[0]["can_retry"] is True


async def test_cycle_deadline_prevents_early_retry_and_owner_retry_caps_total_history(environment):
    env = environment
    delivery = await enqueue(env)
    sender = Sender(DeliveryResult("receiver_unavailable", retryable=True, retry_after=86401))
    for cycle in range(1, 4):
        assert await process(env, sender) == 0
        saved = await row(env, delivery["_id"])
        assert saved["state"] == "failed" and saved["last_outcome"] == "cycle_expired"
        if cycle < 3:
            env.clock.advance(86402)
            head = await read_head(env.db, "primary")
            await outbox.retry_delivery(env.db, head, env.configuration, saved["_id"], env.clock(), None)
    head = await read_head(env.db, "primary")
    with pytest.raises(NotificationError) as failure:
        await outbox.retry_delivery(env.db, head, env.configuration, delivery["_id"], env.clock(), None)
    assert failure.value.code == "delivery_not_retryable"
    assert (await row(env, delivery["_id"]))["cycle"] == 3


async def test_disable_cancels_queued_incidents_but_admitted_attempt_can_finish(environment):
    env = environment
    first = await enqueue(env, 1)
    second = await enqueue(env, 2)
    claim = await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock)
    await env.control.command(env.principal, 1, str(uuid4()), "disable")
    queued_id = second["_id"] if claim["_id"] == first["_id"] else first["_id"]
    assert (await row(env, queued_id))["state"] == "cancelled"
    assert await worker.complete_attempt(env.db, env.settings, env.configuration, claim,
        DeliveryResult("accepted", accepted=True), now=env.clock)
    assert (await row(env, claim["_id"]))["state"] == "accepted"
    assert await process(env, Sender()) == 0


async def test_destination_change_cancels_old_queue_and_never_redirects_it(environment):
    env = environment
    delivery = await enqueue(env)
    changed = replace(env.configuration, destination_id="f" * 64)
    sender = Sender()
    assert await worker.process_once(env.db, env.settings, changed, transport=sender, now=env.clock) == 0
    assert sender.payloads == []
    assert (await row(env, delivery["_id"]))["state"] == "cancelled"
    assert (await row(env, delivery["_id"]))["last_outcome"] == "destination_changed"


async def test_mismatched_identity_cannot_admit_or_send(environment):
    env = environment
    await enqueue(env)
    sender = Sender()
    with pytest.raises(Exception):
        await worker.process_once(env.db, replace(env.settings, project_id="other"), env.configuration,
            transport=sender, now=env.clock)
    assert sender.payloads == []
    assert (await outbox.collection(env.db).find_one({}))["state"] == "queued"


async def test_test_acceptance_verifies_destination_without_enabling_it(environment):
    env = environment
    await env.control.command(env.principal, 1, str(uuid4()), "disable")
    result = await env.control.command(env.principal, 2, str(uuid4()), "test")
    assert result["destination"]["enabled"] is False
    assert await process(env, Sender()) == 1
    saved = await env.control.get(env.principal)
    assert saved["destination"]["verified"] is True
    assert saved["destination"]["enabled"] is False


async def test_retrying_old_test_rejects_another_pending_test(environment):
    env = environment
    head = await read_head(env.db, "primary")
    old = await outbox.enqueue_test(env.db, head, env.configuration, str(uuid4()), env.clock(), None)
    await outbox.collection(env.db).update_one({"_id": old}, {"$set": {"state": "failed", "retryable": True}})
    await outbox.enqueue_test(env.db, head, env.configuration, str(uuid4()), env.clock(), None)
    with pytest.raises(NotificationError) as failure:
        await outbox.retry_delivery(env.db, head, env.configuration, old, env.clock(), None)
    assert failure.value.code == "test_already_pending"


async def test_transport_cancellation_leaves_durable_attempt_for_expiry_recovery(environment):
    env = environment
    delivery = await enqueue(env)
    entered = asyncio.Event()

    class Blocking:
        async def send(self, configuration, payload):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(process(env, Blocking()))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await row(env, delivery["_id"]))["state"] == "sending"
    env.clock.advance(worker.LEASE_SECONDS + 1)
    assert await process(env, Sender()) == 0
    assert (await row(env, delivery["_id"]))["attempts"][0]["outcome"] == "worker_lost_unconfirmed"


async def test_slow_commit_acknowledgement_cannot_send_under_stale_lease(environment, monkeypatch):
    env = environment
    delivery = await enqueue(env)
    original = worker.claim_next

    async def delayed(*args, **kwargs):
        claim = await original(*args, **kwargs)
        env.clock.advance(worker.LEASE_SECONDS)
        return claim

    monkeypatch.setattr(worker, "claim_next", delayed)
    sender = Sender()
    assert await process(env, sender) == 0
    assert sender.payloads == []
    assert (await row(env, delivery["_id"]))["state"] == "sending"


async def test_transaction_callback_uses_fresh_clock_after_retry_delay(environment, monkeypatch):
    env = environment
    await enqueue(env)
    original = ObservationLedger.transaction

    async def delayed(self, callback):
        env.clock.advance(worker.LEASE_SECONDS * 2)
        return await original(self, callback)

    monkeypatch.setattr(ObservationLedger, "transaction", delayed)
    claim = await worker.claim_next(env.db, env.settings, env.configuration, now=env.clock)
    assert outbox.utc(claim["lease_until"]) - env.clock() == timedelta(seconds=worker.LEASE_SECONDS)


@pytest.mark.parametrize("expire", [False, True])
async def test_prior_ambiguous_send_is_not_hidden_by_terminal_failure_or_cycle_expiry(environment, expire):
    env = environment
    delivery = await enqueue(env)
    sender = Sender(DeliveryResult("network_unconfirmed", retryable=True, unconfirmed=True),
                    DeliveryResult("receiver_rejected"))
    assert await process(env, sender) == 0
    env.clock.advance(86401 if expire else 1)
    assert await process(env, sender) == 0
    assert (await row(env, delivery["_id"]))["state"] == "unconfirmed"


async def test_corrupt_payload_cannot_send_arbitrary_stored_content(environment):
    env = environment
    delivery = await enqueue(env)
    await outbox.collection(env.db).update_one({"_id": delivery["_id"]}, {"$set": {"payload.text": CANARY}})
    sender = Sender()
    assert await process(env, sender) == 0
    assert sender.payloads == []
    assert (await row(env, delivery["_id"]))["last_outcome"] == "invalid_delivery"
    assert (await row(env, delivery["_id"]))["retryable"] is False


async def test_receiver_rejection_requires_explicit_owner_retry_after_repair(environment):
    env = environment
    delivery = await enqueue(env)
    sender = Sender(DeliveryResult("receiver_rejected"), DeliveryResult("accepted", accepted=True))
    assert await process(env, sender) == 0
    failed = await row(env, delivery["_id"])
    assert failed["state"] == "failed" and failed["next_attempt_at"] is None
    assert failed["retryable"] is True
    env.clock.advance(60)
    assert await process(env, sender) == 0 and len(sender.payloads) == 1
    status = await env.control.get(env.principal)
    assert status["deliveries"][0]["can_retry"] is True

    await env.control.command(env.principal, 1, str(uuid4()), "retry", delivery["_id"])
    assert await process(env, sender) == 1
    accepted = await row(env, delivery["_id"])
    assert (accepted["state"], accepted["cycle"], accepted["attempt_count"]) == ("accepted", 2, 2)
    assert [attempt["outcome"] for attempt in accepted["attempts"]] == ["receiver_rejected", "accepted"]
    assert len(set(sender.payloads)) == 1
    assert await env.db.guardian_identity_audit.count_documents({"action": "notification_retry"}) == 1
