"""Audited policy saves and immutable first-evaluation snapshots."""
from datetime import datetime, timezone
import hashlib
import hmac
import json

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from guardian.ledger import LedgerError, ObservationLedger
from identity.store import IdentityStore
from .errors import PolicyError, bounded
from .schema import DEFAULT_RULES, MAX_REVISION, valid_revision, validate_rules, validate_snapshot

COLLECTION = "guardian_monitoring_policies"


def utcnow():
    return datetime.now(timezone.utc)


def policy_id(connection_id):
    return "monitoring-policy:" + connection_id


def _collection(db):
    return db.get_collection(COLLECTION, read_concern=ReadConcern("majority"),
                            write_concern=WriteConcern(w="majority", wtimeout=3000))


def _default(connection_id):
    return {"_id": policy_id(connection_id), "connection_id": connection_id, "schema_version": 1,
            "revision": 0, "rules": dict(DEFAULT_RULES), "binding_id": None,
            "updated_at": None, "updated_by": None, "fence": 0}


def _validate(document, connection_id):
    if (type(document) is not dict or document.get("_id") != policy_id(connection_id)
            or document.get("connection_id") != connection_id
            or type(document.get("schema_version")) is not int or document["schema_version"] != 1
            or type(document.get("fence")) is not int or document["fence"] < 0):
        raise ValueError("invalid_policy_state")
    snapshot = validate_snapshot({"revision": document.get("revision"), "rules": document.get("rules")})
    if snapshot["revision"] == 0:
        if any(document.get(name) is not None for name in ("binding_id", "updated_at", "updated_by")):
            raise ValueError("invalid_policy_state")
    else:
        actor, stamp, binding = document.get("updated_by"), document.get("updated_at"), document.get("binding_id")
        if (type(binding) is not str or len(binding) != 64 or type(actor) is not dict
                or set(actor) != {"id", "name", "role"} or actor.get("role") != "owner"
                or any(type(actor.get(key)) is not str or not 1 <= len(actor[key]) <= 120 for key in ("id", "name"))
                or type(stamp) is not str or len(stamp) > 40):
            raise ValueError("invalid_policy_state")
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("invalid_policy_state")
    return snapshot


async def _head(db, connection_id, session=None, *, create=False):
    options = {"session": session} if session is not None else {}
    collection = _collection(db)
    if create:
        await collection.update_one({"_id": policy_id(connection_id)},
                                    {"$setOnInsert": _default(connection_id)}, upsert=True, **options)
    document = await collection.find_one({"_id": policy_id(connection_id)}, max_time_ms=2000, **options)
    document = _default(connection_id) if document is None else document
    _validate(document, connection_id)
    if document["revision"]:
        binding = await db.guardian_state.find_one({"_id": "identity_binding"}, **options)
        fields = ("organization_id", "project_id", "environment", "connection_id", "issuer", "client_id")
        if not binding or binding.get("connection_id") != connection_id or not all(type(binding.get(key)) is str for key in fields):
            raise ValueError("invalid_policy_binding")
        digest = hashlib.sha256(json.dumps({key: binding[key] for key in fields}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if digest != document["binding_id"]:
            raise ValueError("invalid_policy_binding")
    return document


class PolicyStore:
    def __init__(self, db, settings, now=utcnow):
        self.db, self.settings, self.now = db, settings, now
        self.identity = IdentityStore(db, settings, now=now)
        self.connection_id = settings.connection_id

    async def _actor(self, principal, session=None, *, owner=False):
        if self.settings.mode != "oidc" or principal is None or type(getattr(principal, "session_id", None)) is not str:
            raise PolicyError(403, "named_owner_required")
        current = await self.identity._authenticate_id(principal.session_id, session, touch=owner)
        if owner and (current.actor["role"] != "owner" or type(getattr(principal, "csrf_token", None)) is not str
                      or not hmac.compare_digest(current.csrf_token.encode(), principal.csrf_token.encode())):
            raise PolicyError(403, "owner_required")
        return current

    def _response(self, document, principal):
        if document["revision"] and (principal is None or document["binding_id"] != self.identity.binding_id):
            raise PolicyError(503, "policy_binding_mismatch")
        return {"schema_version": 1, "revision": document["revision"], "rules": dict(document["rules"]),
                "updated_at": document["updated_at"], "updated_by": document["updated_by"],
                "can_manage": principal is not None and principal.actor["role"] == "owner",
                "project": principal.project if principal else None}

    @bounded()
    async def get(self, principal):
        if self.settings.mode == "oidc":
            principal = await self._actor(principal)
        elif principal is not None:
            raise PolicyError(503, "policy_binding_mismatch")
        document = await _head(self.db, self.connection_id)
        return self._response(document, principal)

    @bounded(35)
    async def save(self, principal, expected_revision, rules):
        try:
            if not valid_revision(expected_revision) or expected_revision >= MAX_REVISION:
                raise ValueError()
            rules = validate_rules(rules)
        except ValueError:
            raise PolicyError(400, "invalid_policy_request") from None

        async def commit(session):
            actor = await self._actor(principal, session, owner=True)
            options = {"session": session} if session is not None else {}
            document = await _head(self.db, self.connection_id, session, create=True)
            if document["revision"] and document["binding_id"] != self.identity.binding_id:
                raise PolicyError(503, "policy_binding_mismatch")
            if document["revision"] != expected_revision:
                raise PolicyError(409, "policy_revision_conflict")
            revision = expected_revision + 1
            updated = {**document, "revision": revision, "rules": rules, "binding_id": self.identity.binding_id,
                       "updated_at": self.now().astimezone(timezone.utc).isoformat(), "updated_by": dict(actor.actor),
                       "fence": document["fence"] + 1}
            _validate(updated, self.connection_id)
            result = await _collection(self.db).replace_one(
                {"_id": document["_id"], "revision": expected_revision, "fence": document["fence"]}, updated, **options)
            if result.matched_count != 1:
                raise PolicyError(409, "policy_revision_conflict")
            await self.identity._collection("guardian_identity_audit").insert_one({
                "_id": hashlib.sha256(json.dumps([self.identity.binding_id, "monitoring_policy", revision], separators=(",", ":")).encode()).hexdigest(),
                "action": "update_monitoring_policy", "binding_id": self.identity.binding_id,
                "revision": revision, "actor": actor.actor, "project": actor.project,
                "occurred_at": updated["updated_at"], "before": dict(document["rules"]), "after": dict(rules),
            }, **options)
            return self._response(updated, actor)
        return await ObservationLedger(self.db, self.connection_id).transaction(commit)


async def pin_policy(ledger, lease, row):
    """Pin once before evaluation; policy/head writes serialize with owner saves."""
    async def commit(session):
        await ledger._touch(lease, session)
        options = {"session": session} if session is not None else {}
        query = {"_id": row["_id"], "connection_id": ledger.connection_id, "version": row["version"],
                 "state": "accepted", "pending": True}
        current = await ledger.db.guardian_observations.find_one(query, **options)
        if current is None:
            return None
        if "monitoring_policy" in current:
            return validate_snapshot(current["monitoring_policy"])
        document = await _head(ledger.db, ledger.connection_id, session, create=True)
        snapshot = {"revision": 0, "rules": dict(DEFAULT_RULES)} if current.get("completed_rules") else _validate(document, ledger.connection_id)
        touched = await _collection(ledger.db).update_one(
            {"_id": document["_id"], "revision": document["revision"], "fence": document["fence"]},
            {"$inc": {"fence": 1}}, **options)
        if touched.matched_count != 1:
            raise LedgerError("policy_changed")
        result = await ledger.db.guardian_observations.update_one(
            {**query, "monitoring_policy": {"$exists": False}}, {"$set": {"monitoring_policy": snapshot}}, **options)
        if result.matched_count != 1:
            raise LedgerError("policy_changed")
        return snapshot
    try:
        return await ledger.transaction(commit)
    except (ValueError, KeyError, TypeError):
        raise LedgerError("invalid_monitoring_policy") from None
