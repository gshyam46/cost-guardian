"""Owner-controlled activation, audited commands and read-only delivery status."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from guardian.ledger import LedgerError, ObservationLedger
from identity.store import IdentityStore
from .errors import NotificationError, bounded
from .schema import MAX_REVISION, validate_command
from .settings import load_notification_settings

COLLECTION = "guardian_notification_settings"


def utcnow():
    return datetime.now(timezone.utc)


def collection(db, name=COLLECTION):
    return db.get_collection(name, read_concern=ReadConcern("majority"),
                             write_concern=WriteConcern(w="majority", wtimeout=3000))


def _default(connection_id):
    return {"_id": "notifications:" + connection_id, "connection_id": connection_id,
            "schema_version": 1, "revision": 0, "fence": 0, "binding_id": None,
            "destination_id": None, "enabled": False, "verified_at": None, "updated_at": None}


def _stamp(value):
    if type(value) is not str or len(value) > 40:
        raise ValueError("invalid_notification_state")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("invalid_notification_state")
    return stamp


async def read_head(db, connection_id, session=None, create=False):
    options = {"session": session} if session is not None else {}
    target = collection(db)
    if create:
        await target.update_one({"_id": "notifications:" + connection_id},
                                {"$setOnInsert": _default(connection_id)}, upsert=True, **options)
    head = await target.find_one({"_id": "notifications:" + connection_id}, max_time_ms=2000, **options)
    head = _default(connection_id) if head is None else head
    if (head.get("_id") != "notifications:" + connection_id or head.get("connection_id") != connection_id
            or type(head.get("schema_version")) is not int or head["schema_version"] != 1
            or type(head.get("revision")) is not int or not 0 <= head["revision"] <= MAX_REVISION
            or type(head.get("fence")) is not int or head["fence"] < 0 or type(head.get("enabled")) is not bool):
        raise ValueError("invalid_notification_state")
    if head.get("destination_id") is not None and (type(head["destination_id"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", head["destination_id"])):
        raise ValueError("invalid_notification_state")
    for key in ("verified_at", "updated_at"):
        if head.get(key) is not None:
            _stamp(head[key])
    if head["revision"] == 0:
        if head["enabled"] or any(head.get(k) is not None for k in ("binding_id", "destination_id", "verified_at", "updated_at")):
            raise ValueError("invalid_notification_state")
    else:
        binding = await db.guardian_state.find_one({"_id": "identity_binding"}, **options)
        fields = ("organization_id", "project_id", "environment", "connection_id", "issuer", "client_id")
        if not binding or binding.get("connection_id") != connection_id or not all(type(binding.get(k)) is str for k in fields):
            raise ValueError("invalid_notification_binding")
        digest = hashlib.sha256(json.dumps({k: binding[k] for k in fields}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if digest != head.get("binding_id") or head.get("updated_at") is None:
            raise ValueError("invalid_notification_binding")
    if head["enabled"] and (not head.get("verified_at") or not head.get("destination_id")):
        raise ValueError("invalid_notification_state")
    return head


async def touch_head(db, head, session):
    options = {"session": session} if session is not None else {}
    result = await collection(db).update_one(
        {"_id": head["_id"], "revision": head["revision"], "fence": head["fence"]},
        {"$inc": {"fence": 1}}, **options)
    if result.matched_count != 1:
        raise LedgerError("notification_settings_changed")


class NotificationStore:
    def __init__(self, db, identity_settings, notification_settings=None, now=utcnow):
        self.db, self.settings, self.now = db, identity_settings, now
        self.notification_settings = notification_settings or load_notification_settings(identity_settings)
        self.identity = IdentityStore(db, identity_settings, now=now)
        self.connection_id = identity_settings.connection_id

    async def _actor(self, principal, session=None, *, owner=False):
        if self.settings.mode != "oidc" or principal is None or type(getattr(principal, "session_id", None)) is not str:
            raise NotificationError(403, "named_owner_required")
        current = await self.identity._authenticate_id(principal.session_id, session, touch=owner)
        if owner and (current.actor["role"] != "owner" or type(getattr(principal, "csrf_token", None)) is not str
                      or not hmac.compare_digest(current.csrf_token.encode(), principal.csrf_token.encode())):
            raise NotificationError(403, "owner_required")
        return current

    @bounded()
    async def get(self, principal, incident_id=None):
        from .outbox import recent_deliveries
        if self.settings.mode == "oidc":
            principal = await self._actor(principal)
        elif principal is not None:
            raise NotificationError(503, "notification_binding_mismatch")
        head = await read_head(self.db, self.connection_id)
        if head["revision"] and (principal is None or head["binding_id"] != self.identity.binding_id):
            raise NotificationError(503, "notification_binding_mismatch")
        if incident_id is not None:
            if (type(incident_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", incident_id)
                    or await self.db.guardian_incidents.find_one({"id": incident_id}, {"_id": 1}, max_time_ms=2000) is None):
                raise NotificationError(404, "incident_not_found")
        configuration = self.notification_settings
        matching = configuration.state == "configured" and head["destination_id"] == configuration.destination_id
        state = configuration.state
        if state == "configured" and head["destination_id"] and not matching:
            state = "changed"
        can_manage = principal is not None and principal.actor["role"] == "owner"
        rows, more = await recent_deliveries(self.db, self.connection_id, configuration.destination_id,
                                             incident_id=incident_id, can_manage=can_manage, now=self.now)
        for row in rows:
            row["can_retry"] = bool(row["can_retry"] and matching
                                    and (row["kind"] == "test" or head["enabled"]))
        heartbeat = await self.db.guardian_state.find_one({"_id": "notification-worker:" + self.connection_id}, max_time_ms=2000)
        worker = {"status": "unknown", "last_seen_at": None}
        if heartbeat:
            stamp = _stamp(heartbeat.get("last_seen_at"))
            age = (self.now() - stamp).total_seconds()
            worker["last_seen_at"] = stamp.astimezone(timezone.utc).isoformat()
            worker["status"] = ("blocked" if configuration.state != "configured"
                                or heartbeat.get("binding_id") != self.identity.binding_id
                                or heartbeat.get("destination_id") != configuration.destination_id
                                or heartbeat.get("status") != "healthy" else
                                "healthy" if 0 <= age <= 30 else "stale")
        return {"schema_version": 1, "revision": head["revision"], "project": principal.project if principal else None,
                "can_manage": can_manage, "updated_at": head["updated_at"],
                "destination": {"channel": "slack", "state": state, "verified": bool(matching and head["verified_at"]),
                                "enabled": bool(matching and head["enabled"])},
                "worker": worker, "deliveries": rows, "has_more": more}

    @bounded(40)
    async def command(self, principal, expected_revision, request_id, action, delivery_id=None):
        from .outbox import enqueue_test, retry_delivery, cancel_pending
        body = {"expected_revision": expected_revision, "request_id": request_id, "action": action}
        if delivery_id is not None:
            body["delivery_id"] = delivery_id
        try:
            validate_command(body)
        except (ValueError, TypeError, AttributeError):
            raise NotificationError(400, "invalid_notification_request") from None
        receipt_id = hashlib.sha256(json.dumps(["notification_command", self.identity.binding_id, request_id], separators=(",", ":")).encode()).hexdigest()
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        configuration = self.notification_settings

        async def commit(session):
            actor = await self._actor(principal, session, owner=True)
            options = {"session": session} if session is not None else {}
            receipts = collection(self.db, "guardian_notification_commands")
            prior = await receipts.find_one({"_id": receipt_id}, **options)
            if prior:
                if prior.get("command_hash") != digest:
                    raise NotificationError(409, "notification_request_conflict")
                return
            head = await read_head(self.db, self.connection_id, session, create=True)
            if head["revision"] and head["binding_id"] != self.identity.binding_id:
                raise NotificationError(503, "notification_binding_mismatch")
            if head["revision"] != expected_revision:
                raise NotificationError(409, "notification_revision_conflict")
            if action != "disable" and configuration.state != "configured":
                raise NotificationError(409, "destination_not_configured")
            if action == "test":
                pending_test = await collection(self.db, "guardian_notification_deliveries").find_one({
                    "connection_id": self.connection_id, "destination_id": configuration.destination_id,
                    "kind": "test", "state": {"$in": ["queued", "sending", "retrying"]}}, {"_id": 1}, **options)
                if pending_test:
                    raise NotificationError(409, "destination_test_pending")
            updated = {**head, "revision": expected_revision + 1, "fence": head["fence"] + 1,
                       "binding_id": self.identity.binding_id, "updated_at": self.now().astimezone(timezone.utc).isoformat()}
            if action == "test" and head["destination_id"] != configuration.destination_id:
                updated.update(destination_id=configuration.destination_id, verified_at=None, enabled=False)
            elif action == "enable":
                if head["destination_id"] != configuration.destination_id or not head["verified_at"]:
                    raise NotificationError(409, "destination_test_required")
                updated["enabled"] = True
            elif action == "disable":
                updated["enabled"] = False
            result = await collection(self.db).replace_one(
                {"_id": head["_id"], "revision": head["revision"], "fence": head["fence"]}, updated, **options)
            if result.matched_count != 1:
                raise NotificationError(409, "notification_revision_conflict")
            now = self.now()
            if action == "test":
                if head["destination_id"] != configuration.destination_id:
                    await cancel_pending(self.db, head, now, session, reason="destination_changed", include_tests=True)
                await enqueue_test(self.db, updated, configuration, request_id, now, session)
            elif action == "disable":
                await cancel_pending(self.db, head, now, session)
            elif action == "retry":
                if head["destination_id"] != configuration.destination_id:
                    raise NotificationError(409, "destination_changed")
                await retry_delivery(self.db, updated, configuration, delivery_id, now, session)
            await receipts.insert_one({"_id": receipt_id, "binding_id": self.identity.binding_id,
                                       "command_hash": digest, "revision": updated["revision"], "created_at": updated["updated_at"]}, **options)
            await self.identity._collection("guardian_identity_audit").insert_one({
                "_id": receipt_id, "action": "notification_" + action, "binding_id": self.identity.binding_id,
                "actor": actor.actor, "project": actor.project, "occurred_at": updated["updated_at"],
                "revision": updated["revision"], "delivery_id": delivery_id,
                "before": {"enabled": head["enabled"], "verified": bool(head["verified_at"])},
                "after": {"enabled": updated["enabled"], "verified": bool(updated["verified_at"])},
            }, **options)
        await ObservationLedger(self.db, self.connection_id).transaction(commit)
        return await self.get(principal)
