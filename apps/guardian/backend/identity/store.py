"""Opaque browser sessions, one-use login state and transactional human actions.

Mongo TTL is cleanup only. Every authorization query checks absolute expiry.
Operations are bounded even when Mongo server selection cannot complete.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import hmac
import json
import re
import secrets

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from guardian.incident import Incident
from guardian.ledger import ObservationLedger
from .errors import IdentityError

SESSION_SECONDS = 8 * 60 * 60
FLOW_SECONDS = 10 * 60
DB_SECONDS = 5
TRANSACTION_SECONDS = 35
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}\Z")


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key(value):
    return digest(value) if isinstance(value, str) and TOKEN.fullmatch(value) else None


def bounded(seconds=DB_SECONDS):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            try:
                async with asyncio.timeout(seconds):
                    return await function(*args, **kwargs)
            except IdentityError:
                raise
            except Exception:
                raise IdentityError(503, "identity_store_unavailable") from None
        return wrapped
    return decorate


@dataclass(frozen=True)
class Principal:
    session_id: str
    actor: dict
    project: dict
    csrf_token: str
    permissions: list

    def access_response(self):
        return {"authenticated": True, "auth_mode": "oidc", "deployment_mode": "single_project",
                "permissions": self.permissions, "actor": self.actor, "project": self.project,
                "csrf_token": self.csrf_token}


class IdentityStore:
    def __init__(self, db, settings, now=utcnow):
        self.db, self.settings, self.now = db, settings, now
        self.binding_id = digest(json.dumps(settings.binding, sort_keys=True, separators=(",", ":")))

    def _collection(self, name):
        # Consumed state and revoked sessions must survive a primary change.
        # Transactions override read concern with snapshot and write with majority.
        return self.db.get_collection(name, read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority", wtimeout=3000))

    async def _check_binding(self, session=None, *, touch=False):
        options = {"session": session} if session is not None else {}
        expected = {"_id": "identity_binding", **self.settings.binding}
        if touch:
            result = await self._collection("guardian_state").update_one(expected, {"$inc": {"fence": 1}}, **options)
            found = result.matched_count
        else:
            found = await self._collection("guardian_state").find_one(expected, max_time_ms=2000, **options)
        if not found:
            raise IdentityError(503, "identity_binding_mismatch")
        ledger = await self._collection("guardian_state").find_one({"_id": "ledger_configuration"}, max_time_ms=2000, **options)
        if ledger and ledger.get("connection_id") != self.settings.connection_id:
            raise IdentityError(503, "identity_binding_mismatch")

    @bounded()
    async def ensure_binding(self):
        ledger = await self._collection("guardian_state").find_one({"_id": "ledger_configuration"}, max_time_ms=2000)
        if ledger and ledger.get("connection_id") != self.settings.connection_id:
            raise IdentityError(503, "identity_binding_mismatch")
        try:
            await self._collection("guardian_state").update_one(
                {"_id": "identity_binding"}, {"$setOnInsert": {**self.settings.binding, "fence": 0}}, upsert=True)
        except DuplicateKeyError:
            pass  # Concurrent first use must still match the winner below.
        await self._check_binding()

    async def _indexes(self):
        # Idempotent requests, no process-local cache that could hide a changed DB.
        for name in ("guardian_auth_flows", "guardian_auth_sessions", "guardian_auth_admission"):
            await self._collection(name).create_index("expires_at", expireAfterSeconds=0, name="identity_expiry", maxTimeMS=2000)

    @bounded()
    async def create_flow(self, peer):
        await self.ensure_binding()
        await self._indexes()
        now = self.now()
        bucket = int(now.timestamp()) // 300
        # The ASGI server supplies the peer; trusted-proxy configuration is an
        # operator boundary. Do not parse caller-supplied forwarding headers here.
        # A global per-deployment cap bounds storage even across many peers.
        for identity, limit in (("global", 200), ("peer:" + digest(str(peer)), 20)):
            counter = await self._collection("guardian_auth_admission").find_one_and_update(
                {"_id": digest(f"{self.binding_id}:{identity}:{bucket}")},
                {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": now + timedelta(seconds=600)}},
                upsert=True, return_document=ReturnDocument.AFTER, maxTimeMS=2000)
            if counter["count"] > limit:
                raise IdentityError(429, "login_rate_limited")
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        flow = {"_id": digest(state), "browser_hash": digest(browser), "binding_id": self.binding_id,
                "nonce": secrets.token_urlsafe(32), "code_verifier": secrets.token_urlsafe(48),
                "expires_at": now + timedelta(seconds=FLOW_SECONDS)}
        await self._collection("guardian_auth_flows").insert_one(flow)
        return {"state": state, "browser_token": browser, "nonce": flow["nonce"], "code_verifier": flow["code_verifier"]}

    @bounded()
    async def consume_flow(self, state, browser_token):
        state_key, browser_key = _key(state), _key(browser_token)
        if not state_key or not browser_key:
            raise IdentityError(401, "invalid_state")
        await self._check_binding()
        flow = await self._collection("guardian_auth_flows").find_one_and_delete(
            {"_id": state_key, "browser_hash": browser_key, "binding_id": self.binding_id,
             "expires_at": {"$gt": self.now()}}, maxTimeMS=2000)
        if not flow:
            raise IdentityError(401, "invalid_state")
        return flow

    def _member(self, issuer, subject):
        if issuer != self.settings.issuer or not isinstance(subject, str) or subject not in self.settings.members:
            raise IdentityError(403, "member_not_allowed")
        return self.settings.members[subject]

    @bounded(TRANSACTION_SECONDS)
    async def create_session(self, claims, previous_token=None):
        self._member(claims.get("issuer"), claims.get("subject"))
        await self.ensure_binding()
        await self._indexes()
        token = secrets.token_urlsafe(32)
        doc = {"_id": digest(token), "binding_id": self.binding_id, "issuer": claims["issuer"],
               "subject": claims["subject"], "csrf_token": secrets.token_urlsafe(32),
               "created_at": self.now(), "expires_at": self.now() + timedelta(seconds=SESSION_SECONDS), "fence": 0}
        async def write(session):
            options = {"session": session} if session is not None else {}
            await self._check_binding(session, touch=True)
            await self._collection("guardian_auth_sessions").insert_one(doc, **options)
            previous = _key(previous_token)
            if previous:
                await self._collection("guardian_auth_sessions").delete_one({"_id": previous, "binding_id": self.binding_id}, **options)
        await ObservationLedger(self.db).transaction(write)
        return token

    async def _authenticate_id(self, session_id, session=None, *, touch=False):
        await self._check_binding(session, touch=touch)
        options = {"session": session} if session is not None else {}
        query = {"_id": session_id, "binding_id": self.binding_id, "expires_at": {"$gt": self.now()}}
        if touch:
            doc = await self._collection("guardian_auth_sessions").find_one_and_update(query, {"$inc": {"fence": 1}},
                return_document=ReturnDocument.AFTER, maxTimeMS=2000, **options)
        else:
            doc = await self._collection("guardian_auth_sessions").find_one(query, max_time_ms=2000, **options)
        if not doc:
            raise IdentityError(401, "invalid_session")
        member = self._member(doc.get("issuer"), doc.get("subject"))
        csrf = doc.get("csrf_token")
        if not _key(csrf):
            raise IdentityError(401, "invalid_session")
        actor_id = digest(json.dumps([self.settings.issuer, member.subject], separators=(",", ":")))
        return Principal(session_id, {"id": actor_id, "name": member.name, "role": member.role},
            {"organization_id": self.settings.organization_id, "project_id": self.settings.project_id,
             "environment": self.settings.environment, "name": self.settings.project_name}, csrf,
            ["read", "resolve_incidents"] if member.role in ("owner", "operator") else ["read"])

    @bounded()
    async def authenticate(self, token):
        key = _key(token)
        if not key:
            raise IdentityError(401, "invalid_session")
        return await self._authenticate_id(key)

    @bounded()
    async def logout(self, principal):
        await self._check_binding()
        # A repeated deletion is successful revocation; the API first authenticates.
        await self._collection("guardian_auth_sessions").delete_one({"_id": principal.session_id, "binding_id": self.binding_id})

    @bounded(TRANSACTION_SECONDS)
    async def resolve(self, principal, incident_id):
        async def write(session):
            options = {"session": session} if session is not None else {}
            current = await self._authenticate_id(principal.session_id, session, touch=True)
            if "resolve_incidents" not in current.permissions or not hmac.compare_digest(current.csrf_token, principal.csrf_token):
                raise IdentityError(403, "mutation_denied")
            if not isinstance(incident_id, str) or not 1 <= len(incident_id) <= 256:
                raise IdentityError(404, "incident_not_found")
            collection = self._collection("guardian_incidents")
            incident = await collection.find_one({"id": incident_id}, max_time_ms=2000, **options)
            if not incident:
                raise IdentityError(404, "incident_not_found")
            if incident.get("status") == "resolved":
                return Incident(**incident)
            if incident.get("status") != "open":
                raise IdentityError(503, "invalid_incident_state")
            resolved_at = self.now().isoformat()
            updated = await collection.find_one_and_update({"_id": incident["_id"], "status": "open"},
                {"$set": {"status": "resolved", "resolved_at": resolved_at}},
                return_document=ReturnDocument.AFTER, maxTimeMS=2000, **options)
            if not updated:
                raise IdentityError(503, "incident_changed")
            await self._collection("guardian_identity_audit").insert_one({
                "_id": digest(json.dumps([self.binding_id, "resolve_incident", incident_id], separators=(",", ":"))),
                "action": "resolve_incident", "incident_id": incident_id, "binding_id": self.binding_id,
                "actor": current.actor, "project": current.project, "occurred_at": resolved_at,
                "before": "open", "after": "resolved"}, **options)
            return Incident(**updated)
        return await ObservationLedger(self.db).transaction(write)
