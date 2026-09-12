"""Project-bound, write-only ingestion credentials.

Only an owner can issue or revoke. The plaintext secret exists solely in the
successful creation response; all subsequent views use an explicit allowlist.
Transaction-aware ingestion authentication deliberately preserves driver errors
so its caller can retry the entire admission transaction safely.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
from uuid import UUID, uuid4

from pymongo import ReturnDocument

from guardian.ledger import ObservationLedger
from identity.errors import IdentityError
from identity.store import IdentityStore, utcnow
from .errors import CaptureError, bounded
from .settings import ensure_direct_binding


MAX_ACTIVE_KEYS = 10
MAX_KEYS = 100
_TOKEN = re.compile(r"cg_ingest_([0-9a-f]{32})_([A-Za-z0-9_-]{43})\Z")
_IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _date(value):
    if not isinstance(value, datetime):
        raise CaptureError(503, "invalid_credential_state")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value):
    return _date(value).isoformat() if value is not None else None


def _status(document, now):
    if document.get("revoked_at") is not None:
        _date(document["revoked_at"])
        return "revoked"
    return "expired" if _date(document["expires_at"]) <= _date(now) else "active"


def _metadata(document, now):
    return {
        "id": document["_id"], "label": document["label"], "prefix": document["prefix"],
        "status": _status(document, now), "created_at": _iso(document["created_at"]),
        "expires_at": _iso(document["expires_at"]), "revoked_at": _iso(document.get("revoked_at")),
        "last_used_at": _iso(document.get("last_used_at")),
    }


def _request_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise CaptureError(400, "invalid_credential_request")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise CaptureError(400, "invalid_credential_request") from None


class IngestionCredentialStore:
    def __init__(self, db, settings, now=utcnow):
        self.db, self.settings, self.now = db, settings, now
        self.identity = IdentityStore(db, settings, now=now)
        self.binding_id = self.identity.binding_id

    def _keys(self):
        return self.identity._collection("guardian_ingestion_keys")

    async def _actor(self, principal, session=None, *, owner=False):
        if principal is None or not isinstance(getattr(principal, "session_id", None), str):
            raise CaptureError(401, "authentication_required")
        try:
            current = await self.identity._authenticate_id(principal.session_id, session, touch=owner)
        except IdentityError as error:
            raise CaptureError(error.status_code, "authentication_required" if error.status_code == 401
                               else "permission_denied" if error.status_code == 403 else "capture_unavailable") from None
        if owner:
            csrf = getattr(principal, "csrf_token", None)
            if (current.actor.get("role") != "owner" or not isinstance(csrf, str)
                    or not hmac.compare_digest(current.csrf_token.encode("utf-8"), csrf.encode("utf-8"))):
                raise CaptureError(403, "permission_denied")
        return current

    async def _audit(self, action, identifier, actor, now, session):
        options = {"session": session} if session is not None else {}
        await self.identity._collection("guardian_identity_audit").insert_one({
            "_id": _hash(json.dumps([self.binding_id, action, identifier], separators=(",", ":"))),
            "action": action, "credential_id": identifier, "binding_id": self.binding_id,
            "actor": actor.actor, "project": actor.project, "occurred_at": _iso(now),
        }, **options)

    @bounded()
    async def list(self, principal):
        await self._actor(principal)
        await ensure_direct_binding(self.db, self.settings)
        rows = await self._keys().find({"binding_id": self.binding_id}).sort(
            [("created_at", -1), ("_id", -1)]).max_time_ms(2000).to_list(length=MAX_KEYS + 1)
        if len(rows) > MAX_KEYS:
            raise CaptureError(503, "credential_history_limit")
        now = self.now()
        return [_metadata(row, now) for row in rows]

    @bounded(35)
    async def create(self, principal, label, expires_in_days, request_id):
        if (not isinstance(label, str) or not 1 <= len(label) <= 80 or not label.strip()
                or not label.isprintable() or type(expires_in_days) is not int or not 1 <= expires_in_days <= 90):
            raise CaptureError(400, "invalid_credential_request")
        request_id = _request_id(request_id)
        identifier = uuid4().hex
        token = "cg_ingest_" + identifier + "_" + secrets.token_urlsafe(32)
        created_at = _date(self.now())
        document = {
            "_id": identifier, "token_hash": _hash(token), "request_id": request_id,
            "binding_id": self.binding_id, "label": label, "prefix": "cg_ingest_" + identifier[:8],
            "created_at": created_at, "expires_at": created_at + timedelta(days=expires_in_days),
            "revoked_at": None, "last_used_at": None, "fence": 0,
        }

        async def write(session):
            actor = await self._actor(principal, session, owner=True)
            await ensure_direct_binding(self.db, self.settings, session=session, touch=True)
            options = {"session": session} if session is not None else {}
            collection = self._keys()
            if await collection.find_one({"binding_id": self.binding_id, "request_id": request_id},
                                         max_time_ms=2000, **options):
                raise CaptureError(409, "credential_already_created")
            total = await collection.count_documents({"binding_id": self.binding_id}, maxTimeMS=2000, **options)
            active = await collection.count_documents({"binding_id": self.binding_id, "revoked_at": None,
                "expires_at": {"$gt": self.now()}}, maxTimeMS=2000, **options)
            if total >= MAX_KEYS or active >= MAX_ACTIVE_KEYS:
                raise CaptureError(429, "credential_limit_reached")
            await collection.insert_one(document, **options)
            await self._audit("create_ingestion_key", identifier, actor, created_at, session)
            return {"credential": _metadata(document, self.now()), "token": token}

        return await ObservationLedger(self.db).transaction(write)

    @bounded(35)
    async def revoke(self, principal, identifier):
        async def write(session):
            actor = await self._actor(principal, session, owner=True)
            await ensure_direct_binding(self.db, self.settings, session=session, touch=True)
            if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
                raise CaptureError(404, "credential_not_found")
            options = {"session": session} if session is not None else {}
            collection = self._keys()
            query = {"_id": identifier, "binding_id": self.binding_id}
            document = await collection.find_one(query, max_time_ms=2000, **options)
            if not document:
                raise CaptureError(404, "credential_not_found")
            now = _date(self.now())
            if document.get("revoked_at") is None:
                document = await collection.find_one_and_update({**query, "revoked_at": None},
                    {"$set": {"revoked_at": now}, "$inc": {"fence": 1}},
                    return_document=ReturnDocument.AFTER, maxTimeMS=2000, **options)
                if document is None:
                    raise CaptureError(503, "credential_changed")
                await self._audit("revoke_ingestion_key", identifier, actor, now, session)
            return {"credential": _metadata(document, now)}

        return await ObservationLedger(self.db).transaction(write)

    async def _authenticate(self, token, session=None, *, touch=False):
        matched = _TOKEN.fullmatch(token) if isinstance(token, str) else None
        if not matched:
            raise CaptureError(401, "invalid_ingestion_key")
        await ensure_direct_binding(self.db, self.settings, session=session, touch=touch)
        query = {"_id": matched.group(1), "binding_id": self.binding_id, "token_hash": _hash(token),
                 "revoked_at": None, "expires_at": {"$gt": self.now()}}
        options = {"session": session} if session is not None else {}
        if touch:
            document = await self._keys().find_one_and_update(query,
                {"$inc": {"fence": 1}, "$set": {"last_used_at": _date(self.now())}},
                return_document=ReturnDocument.AFTER, maxTimeMS=2000, **options)
        else:
            document = await self._keys().find_one(query, max_time_ms=2000, **options)
        if not document:
            raise CaptureError(401, "invalid_ingestion_key")
        return document

    @bounded()
    async def _authenticate_read(self, token):
        return await self._authenticate(token)

    async def authenticate_ingestion(self, token, session=None, touch=False):
        if session is not None or touch:
            # A mock transaction explicitly supplies None; touch still takes the
            # same undecorated path. Production has no nontransactional fallback.
            return await self._authenticate(token, session, touch=touch)
        return await self._authenticate_read(token)
