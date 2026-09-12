"""Separately supervised, leased delivery worker. No HTTP inside Mongo commits."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from pymongo import ReturnDocument

from guardian.ledger import ObservationLedger
from identity.store import IdentityStore
from . import outbox
from .control import read_head, touch_head, collection as control_collection
from .errors import NotificationError
from .transport import DeliveryResult, SlackTransport, TOTAL_SECONDS

LEASE_SECONDS = 20
PACING_SECONDS = 1
logger = logging.getLogger(__name__)
UNCONFIRMED = frozenset({"network_unconfirmed", "timeout_unconfirmed", "worker_lost_unconfirmed",
                        "invalid_response", "response_too_large"})


def utcnow():
    return datetime.now(timezone.utc)


def lease_id(connection_id):
    return "notification-delivery:" + connection_id


async def _authority(db, identity_settings, session):
    from capture.settings import load_capture_mode
    if identity_settings.mode != "oidc":
        raise NotificationError(503, "notification_binding_mismatch")
    identity = IdentityStore(db, identity_settings)
    await identity._check_binding(session, touch=True)
    source = await db.guardian_state.find_one({"_id": "capture_binding"}, **outbox.options(session))
    if source:
        if source.get("mode") != load_capture_mode() or source.get("connection_id", identity_settings.connection_id) != identity_settings.connection_id:
            raise NotificationError(503, "notification_binding_mismatch")
        if source["mode"] == "direct" and source.get("binding_id") != identity.binding_id:
            raise NotificationError(503, "notification_binding_mismatch")
        await db.guardian_state.update_one({"_id": source["_id"], "mode": source["mode"]},
                                          {"$inc": {"notification_fence": 1}}, **outbox.options(session))
    return identity.binding_id


async def _health(db, settings, configuration, now, status, session=None):
    await db.guardian_state.update_one({"_id": "notification-worker:" + settings.connection_id},
        {"$set": {"binding_id": IdentityStore(db, settings).binding_id,
            "destination_id": configuration.destination_id, "last_seen_at": outbox.iso(now), "status": status}},
        upsert=True, **outbox.options(session))


def _transition(row, result, now):
    attempts = [dict(item) for item in row["attempts"]]
    attempts[-1].update(finished_at=now, outcome=result.outcome)
    uncertain = result.unconfirmed or any(item["outcome"] in UNCONFIRMED for item in attempts)
    fields = {"attempts": attempts, "updated_at": now, "last_outcome": result.outcome,
              "next_attempt_at": None, "retryable": False}
    if result.accepted:
        fields["state"] = "accepted"
        return fields
    if not result.retryable:
        fields["state"] = "unconfirmed" if uncertain else "failed"
        # Receiver rejection stops automatic work. An owner may start another
        # bounded cycle after repairing channel permissions at the same URL.
        fields["retryable"] = result.outcome == "receiver_rejected"
        return fields
    delay = max(2 ** (row["cycle_attempts"] - 1), result.retry_after or 0, PACING_SECONDS)
    next_at = now + timedelta(seconds=delay)
    if row["cycle_attempts"] >= outbox.MAX_ATTEMPTS or next_at >= outbox.utc(row["cycle_deadline"]):
        fields.update(state="unconfirmed" if uncertain else "failed", retryable=True,
            last_outcome="attempts_exhausted" if row["cycle_attempts"] >= outbox.MAX_ATTEMPTS else "cycle_expired")
    else:
        fields.update(state="retrying", next_attempt_at=next_at)
    return fields


async def claim_next(db, identity_settings, notification_settings, *, now=utcnow, owner=None):
    """Return a durable sending row, or None. The caller must send only after return."""
    owner = owner or uuid4().hex
    connection = identity_settings.connection_id
    if notification_settings.state != "configured":
        async with asyncio.timeout(5):
            await _health(db, identity_settings, notification_settings, outbox.utc(now), "blocked")
        return None

    async def commit(session):
        moment = outbox.utc(now)
        opts = outbox.options(session)
        binding_id = await _authority(db, identity_settings, session)
        head = await read_head(db, connection, session, create=True)
        await touch_head(db, head, session)
        matches = head["destination_id"] == notification_settings.destination_id and head["binding_id"] == binding_id
        await _health(db, identity_settings, notification_settings, moment, "healthy" if matches else "blocked", session)
        # One global destination lease serializes admissions even during a
        # configuration change; an already admitted request may still be running.
        await db.guardian_leases.update_one({"_id": lease_id(connection)}, {"$setOnInsert": {
            "owner": None, "epoch": 0, "expires_at": datetime(1970, 1, 1, tzinfo=timezone.utc),
            "next_admission_at": datetime(1970, 1, 1, tzinfo=timezone.utc)}}, upsert=True, **opts)
        lease = await db.guardian_leases.find_one({"_id": lease_id(connection)}, **opts)
        if outbox.utc(lease["expires_at"]) > moment:
            return None
        expired = await outbox.collection(db).find({"connection_id": connection, "state": "sending",
            "lease_until": {"$lte": moment}}, **opts).limit(100).to_list(100)
        for row in expired:
            fields = _transition(row, DeliveryResult("worker_lost_unconfirmed", retryable=True, unconfirmed=True), moment)
            await outbox.collection(db).update_one({"_id": row["_id"], "state": "sending", "claim_epoch": row["claim_epoch"]},
                {"$set": fields}, **opts)
        # Never route an old destination's pending work to the new secret.
        await outbox.collection(db).update_many({"connection_id": connection,
            "destination_id": {"$ne": notification_settings.destination_id}, "state": {"$in": ["queued", "retrying"]}},
            {"$set": {"state": "cancelled", "updated_at": moment, "next_attempt_at": None,
                "retryable": False, "last_outcome": "destination_changed"}}, **opts)
        if not matches:
            await outbox.cancel_pending(db, head, moment, session, reason="destination_changed", include_tests=True)
            return None
        if not head["enabled"]:
            await outbox.cancel_pending(db, head, moment, session)
        if outbox.utc(lease["next_admission_at"]) > moment:
            return None
        # Settle expired cycles without posting. Limit each pass's cleanup work.
        expired_cycles = await outbox.collection(db).find({"connection_id": connection,
            "destination_id": notification_settings.destination_id, "state": {"$in": ["queued", "retrying"]},
            "cycle_deadline": {"$lte": moment}}, **opts).limit(100).to_list(100)
        for expired_row in expired_cycles:
            uncertain = any(item["outcome"] in UNCONFIRMED for item in expired_row["attempts"])
            await outbox.collection(db).update_one({"_id": expired_row["_id"], "state": expired_row["state"]},
                {"$set": {"state": "unconfirmed" if uncertain else "failed", "updated_at": moment,
                    "last_outcome": "cycle_expired", "next_attempt_at": None, "retryable": True}}, **opts)
        row = await outbox.collection(db).find_one({"connection_id": connection,
            "binding_id": binding_id, "destination_id": notification_settings.destination_id,
            "state": {"$in": ["queued", "retrying"]}, "next_attempt_at": {"$lte": moment},
            "cycle_deadline": {"$gt": moment}},
            sort=[("next_attempt_at", 1), ("created_at", 1), ("_id", 1)], **opts)
        if row is None:
            return None
        if not outbox.valid_payload(row, notification_settings):
            await outbox.collection(db).update_one({"_id": row["_id"], "state": row["state"]},
                {"$set": {"state": "failed", "updated_at": moment, "next_attempt_at": None,
                    "retryable": False, "last_outcome": "invalid_delivery"}}, **opts)
            return None
        claimed = await db.guardian_leases.find_one_and_update({"_id": lease_id(connection), "epoch": lease["epoch"],
            "expires_at": {"$lte": moment}, "next_admission_at": {"$lte": moment}},
            {"$set": {"owner": owner, "expires_at": moment + timedelta(seconds=LEASE_SECONDS),
                "next_admission_at": moment + timedelta(seconds=PACING_SECONDS)}, "$inc": {"epoch": 1}},
            return_document=ReturnDocument.AFTER, **opts)
        if claimed is None:
            return None
        count = row["attempt_count"] + 1
        attempts = [*row["attempts"], {"number": count, "started_at": moment, "finished_at": None, "outcome": None}]
        if count > 15 or row["cycle_attempts"] >= outbox.MAX_ATTEMPTS or not outbox.ID.fullmatch(row["_id"]):
            raise NotificationError(503, "invalid_delivery")
        fields = {"state": "sending", "claim_owner": owner, "claim_epoch": claimed["epoch"],
            "lease_until": claimed["expires_at"], "attempt_count": count, "cycle_attempts": row["cycle_attempts"] + 1,
            "attempts": attempts, "updated_at": moment, "next_attempt_at": None}
        await outbox.collection(db).update_one({"_id": row["_id"], "state": row["state"]}, {"$set": fields}, **opts)
        return {**row, **fields}

    async with asyncio.timeout(35):
        return await ObservationLedger(db, connection).transaction(commit)


async def complete_attempt(db, identity_settings, notification_settings, claim, result, *, now=utcnow):
    """Fence a late acknowledgement against both the delivery and destination lease."""
    connection = identity_settings.connection_id

    async def commit(session):
        moment = outbox.utc(now)
        opts = outbox.options(session)
        binding_id = await _authority(db, identity_settings, session)
        head = await read_head(db, connection, session, create=True)
        await touch_head(db, head, session)
        predicate = {"_id": lease_id(connection), "owner": claim["claim_owner"], "epoch": claim["claim_epoch"],
                     "expires_at": {"$gt": moment}}
        current_lease = await db.guardian_leases.find_one(predicate, **opts)
        if not current_lease:
            return False
        row = await outbox.collection(db).find_one({"_id": claim["_id"], "connection_id": connection,
            "binding_id": binding_id, "destination_id": notification_settings.destination_id, "state": "sending",
            "claim_owner": claim["claim_owner"], "claim_epoch": claim["claim_epoch"]}, **opts)
        if row is None:
            return False
        fields = _transition(row, result, moment)
        await outbox.collection(db).update_one({"_id": row["_id"], "state": "sending", "claim_epoch": claim["claim_epoch"]},
                                             {"$set": fields}, **opts)
        released = {"owner": None, "expires_at": moment}
        if result.retry_after:
            released["next_admission_at"] = max(outbox.utc(current_lease["next_admission_at"]),
                moment + timedelta(seconds=result.retry_after))
        await db.guardian_leases.update_one(predicate, {"$set": released}, **opts)
        if (result.accepted and row["kind"] == "test" and head["destination_id"] == notification_settings.destination_id
                and head["binding_id"] == binding_id):
            await control_collection(db).update_one({"_id": head["_id"], "revision": head["revision"], "fence": head["fence"] + 1},
                {"$set": {"verified_at": outbox.iso(moment)}}, **opts)
        await _health(db, identity_settings, notification_settings, moment,
            "healthy" if head["destination_id"] == notification_settings.destination_id else "blocked", session)
        return True

    async with asyncio.timeout(35):
        return await ObservationLedger(db, connection).transaction(commit)


async def process_once(db, identity_settings, notification_settings, *, transport=None, now=utcnow):
    """Admit at most one request; return 1 only for a newly recorded acceptance."""
    claim = await claim_next(db, identity_settings, notification_settings, now=now)
    if claim is None:
        return 0
    if (outbox.utc(claim["lease_until"]) - outbox.utc(now)).total_seconds() <= TOTAL_SECONDS + 1:
        # A delayed commit acknowledgement can consume the lease before return.
        # Leave the durable admission for conservative expiration recovery.
        return 0
    sender = transport or SlackTransport()
    try:
        async with asyncio.timeout(TOTAL_SECONDS):
            result = await sender.send(notification_settings, claim["payload"])
        if not isinstance(result, DeliveryResult):
            result = DeliveryResult("network_unconfirmed", retryable=True, unconfirmed=True)
    except TimeoutError:
        result = DeliveryResult("timeout_unconfirmed", retryable=True, unconfirmed=True)
    except Exception:
        result = DeliveryResult("network_unconfirmed", retryable=True, unconfirmed=True)
    settled = await complete_attempt(db, identity_settings, notification_settings, claim, result, now=now)
    return int(settled and result.accepted)


async def run_forever():
    from db import db, close_database
    from identity.settings import load_settings
    from .settings import load_notification_settings
    settings = load_settings()
    configuration = load_notification_settings(settings)
    try:
        await outbox.ensure_indexes(db)
        while True:
            try:
                await process_once(db, settings, configuration)
            except Exception:
                logger.warning("Notification delivery pass blocked; durable work remains available")
                try:
                    async with asyncio.timeout(5):
                        await _health(db, settings, configuration, utcnow(), "blocked")
                except Exception:
                    pass
            await asyncio.sleep(1)
    finally:
        await close_database()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
