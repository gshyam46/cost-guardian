"""Content-free delivery records, inserted in their caller's transaction."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from types import SimpleNamespace

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from identity.settings import load_settings
from identity.store import IdentityStore
from .errors import NotificationError
from .settings import load_notification_settings

COLLECTION = "guardian_notification_deliveries"
NONTERMINAL = ("queued", "sending", "retrying")
MAX_PENDING = 10000
MAX_ATTEMPTS = 5
MAX_CYCLES = 3
CYCLE_SECONDS = 86400
ID = re.compile(r"[0-9a-f]{64}\Z")
INCIDENT_ID = re.compile(r"signal_v1_[0-9a-f]{64}\Z")


def utcnow():
    return datetime.now(timezone.utc)


def utc(value):
    value = value() if callable(value) else value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # BSON fixtures may decode naive UTC.
    return value.astimezone(timezone.utc)


def iso(value):
    return utc(value).isoformat() if value is not None else None


def collection(db):
    return db.get_collection(COLLECTION, read_concern=ReadConcern("majority"),
                            write_concern=WriteConcern(w="majority", wtimeout=3000))


def options(session):
    return {"session": session} if session is not None else {}


async def ensure_indexes(db):
    for keys, name in (([("connection_id", 1), ("state", 1), ("next_attempt_at", 1)], "notification_due"),
                       ([("connection_id", 1), ("created_at", -1), ("_id", -1)], "notification_history"),
                       ([("connection_id", 1), ("incident_id", 1), ("created_at", -1)], "notification_incident_history")):
        await collection(db).create_index(keys, name=name, maxTimeMS=2000)


def delivery_id(kind, connection_id, destination_id, identity):
    raw = json.dumps([kind, connection_id, destination_id, identity], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def payload(kind, identifier, origin, incident=None):
    lines = ["Cost Guardian notification test" if kind == "test" else "Cost Guardian incident recorded",
             "Delivery: " + identifier]
    if incident is not None:
        if not INCIDENT_ID.fullmatch(incident.id):
            raise NotificationError(503, "invalid_delivery")
        category = incident.detector if incident.detector in ("cost_anomaly", "reliability_anomaly", "pii") else "unknown"
        severity = incident.severity if incident.severity in ("high", "medium", "low") else "unknown"
        lines += ["Category: " + category, "Severity: " + severity, "Incident: " + incident.id,
                  "Open Guardian: " + origin + "/incidents/" + incident.id]
    else:
        lines += ["This verifies receiver acceptance only. Check Notifications in Guardian for incident delivery status.",
                  "Open Guardian: " + origin + "/setup"]
    return {"text": "\n".join(lines), "mrkdwn": False, "unfurl_links": False, "unfurl_media": False}


def document(head, settings, kind, identifier, now, incident=None):
    now = utc(now)
    return {"_id": identifier, "connection_id": head["connection_id"], "binding_id": head["binding_id"],
        "destination_id": settings.destination_id, "kind": kind, "incident_id": incident.id if incident else None,
        "payload_schema": 1,
        "category": incident.detector if incident and incident.detector in ("cost_anomaly", "reliability_anomaly", "pii") else "unknown",
        "severity": incident.severity if incident and incident.severity in ("high", "medium", "low") else "unknown",
        "payload": payload(kind, identifier, settings.public_origin, incident), "state": "queued",
        "created_at": now, "updated_at": now, "attempt_count": 0, "cycle": 1, "cycle_attempts": 0,
        "cycle_started_at": now, "cycle_deadline": now + timedelta(seconds=CYCLE_SECONDS),
        "next_attempt_at": now, "last_outcome": None, "retryable": False, "attempts": []}


def valid_payload(row, settings):
    """Reconstruct the fixed payload from enums and opaque IDs before any send."""
    try:
        if (row["payload_schema"] != 1 or row["kind"] not in ("test", "incident")
                or not ID.fullmatch(row["_id"]) or type(row["payload"]) is not dict):
            return False
        incident = None
        if row["kind"] == "incident":
            if row["category"] not in ("cost_anomaly", "reliability_anomaly", "pii", "unknown") or row["severity"] not in ("high", "medium", "low", "unknown"):
                return False
            incident = SimpleNamespace(id=row["incident_id"], detector=row["category"], severity=row["severity"])
        elif row["incident_id"] is not None:
            return False
        return row["payload"] == payload(row["kind"], row["_id"], settings.public_origin, incident)
    except (KeyError, TypeError, NotificationError):
        return False


async def ensure_capacity(db, connection_id, session):
    count = await collection(db).count_documents({"connection_id": connection_id, "state": {"$in": NONTERMINAL}},
                                                 limit=MAX_PENDING, maxTimeMS=2000, **options(session))
    if count >= MAX_PENDING:
        raise NotificationError(503, "notification_queue_full")


async def enqueue_created(db, connection_id, incidents, session):
    if not incidents:
        return []
    from .control import read_head, touch_head
    identity_settings = load_settings()
    settings = load_notification_settings(identity_settings)
    head = await read_head(db, connection_id, session=session, create=settings.state == "configured")
    if settings.state == "configured" or head["revision"]:
        await touch_head(db, head, session)
    if (identity_settings.mode != "oidc" or settings.state != "configured" or not head["enabled"]
            or not head["verified_at"] or head["destination_id"] != settings.destination_id):
        return []
    authority = IdentityStore(db, identity_settings)
    if identity_settings.connection_id != connection_id or authority.binding_id != head["binding_id"]:
        raise NotificationError(503, "notification_binding_mismatch")
    await authority._check_binding(session, touch=True)
    identifiers = []
    for incident in incidents:
        identifier = delivery_id("incident-created", connection_id, settings.destination_id, incident.id)
        if await collection(db).find_one({"_id": identifier}, {"_id": 1}, **options(session)):
            continue
        await ensure_capacity(db, connection_id, session)
        await collection(db).insert_one(document(head, settings, "incident", identifier, utcnow(), incident), **options(session))
        identifiers.append(identifier)
    return identifiers


async def enqueue_test(db, head, notification_settings, request_id, now, session):
    if await collection(db).find_one({"connection_id": head["connection_id"],
            "destination_id": notification_settings.destination_id, "kind": "test", "state": {"$in": NONTERMINAL}},
            {"_id": 1}, **options(session)):
        raise NotificationError(409, "test_already_pending")
    await ensure_capacity(db, head["connection_id"], session)
    identifier = delivery_id("test", head["connection_id"], notification_settings.destination_id, request_id)
    await collection(db).insert_one(document(head, notification_settings, "test", identifier, now), **options(session))
    return identifier


async def retry_delivery(db, head, notification_settings, delivery_id, now, session):
    row = await collection(db).find_one({"_id": delivery_id, "connection_id": head["connection_id"],
        "binding_id": head["binding_id"], "destination_id": notification_settings.destination_id}, **options(session))
    if row is None:
        raise NotificationError(404, "delivery_not_found")
    if not retry_eligible(row, notification_settings.destination_id):
        raise NotificationError(409, "delivery_not_retryable")
    if row["kind"] == "incident" and not head["enabled"]:
        raise NotificationError(409, "notifications_disabled")
    if row["kind"] == "test" and await collection(db).find_one({"connection_id": head["connection_id"],
            "destination_id": notification_settings.destination_id, "kind": "test", "state": {"$in": NONTERMINAL}},
            {"_id": 1}, **options(session)):
        raise NotificationError(409, "test_already_pending")
    await ensure_capacity(db, head["connection_id"], session)
    now = utc(now)
    await collection(db).update_one({"_id": row["_id"], "state": row["state"], "cycle": row["cycle"]},
        {"$set": {"state": "queued", "cycle_attempts": 0, "cycle_started_at": now,
            "cycle_deadline": now + timedelta(seconds=CYCLE_SECONDS), "next_attempt_at": now,
            "updated_at": now, "last_outcome": "retry_requested", "retryable": False}, "$inc": {"cycle": 1}},
        **options(session))
    return delivery_id


async def cancel_pending(db, head, now, session, *, reason="notifications_disabled", include_tests=False):
    query = {"connection_id": head["connection_id"], "state": {"$in": ["queued", "retrying"]}}
    if not include_tests:
        query["kind"] = "incident"
    await collection(db).update_many(query, {"$set": {"state": "cancelled", "updated_at": utc(now),
        "next_attempt_at": None, "retryable": False, "last_outcome": reason}}, **options(session))


def retry_eligible(row, destination_id):
    return (row["destination_id"] == destination_id and row["state"] in ("failed", "unconfirmed")
            and row.get("retryable") is True and row["cycle"] < MAX_CYCLES)


async def recent_deliveries(db, connection_id, destination_id, *, incident_id=None, can_manage=False, now=utcnow):
    query = {"connection_id": connection_id}
    if incident_id is not None:
        query["incident_id"] = incident_id
    rows = await collection(db).find(query).sort([("created_at", -1), ("_id", -1)]).limit(51).to_list(51)
    public = []
    for row in rows[:50]:
        public.append({"id": row["_id"], "incident_id": row["incident_id"], "kind": row["kind"],
            "state": row["state"], "created_at": iso(row["created_at"]), "updated_at": iso(row["updated_at"]),
            "attempt_count": row["attempt_count"], "cycle": row["cycle"],
            "next_attempt_at": iso(row["next_attempt_at"]), "last_outcome": row["last_outcome"],
            "can_retry": bool(can_manage and retry_eligible(row, destination_id)),
            "attempts": [{"number": attempt["number"], "started_at": iso(attempt["started_at"]),
                "finished_at": iso(attempt["finished_at"]), "outcome": attempt["outcome"]}
                for attempt in row["attempts"][-15:]]})
    return public, len(rows) > 50
