"""Explicit source selection and database binding; no automatic cutover."""
import os

from identity.store import IdentityStore
from .errors import CaptureError

NORMALIZATION_VERSION = "guardian-json-1"
SOURCE_API_VERSION = "direct-v1"


def load_capture_mode():
    mode = os.getenv("GUARDIAN_CAPTURE_MODE", "langfuse")
    if mode not in ("langfuse", "direct"):
        raise CaptureError(503, "invalid_capture_mode")
    return mode


async def guard_source_mode(db, mode, session=None):
    options = {"session": session} if session is not None else {}
    binding = await db.guardian_state.find_one({"_id": "capture_binding"}, max_time_ms=2000, **options)
    if mode not in ("langfuse", "direct") or binding and binding.get("mode") != mode:
        raise CaptureError(503, "capture_mode_mismatch")
    return binding


async def claim_langfuse_binding(db, session=None):
    """Fence a Langfuse writer against initial direct capture on the same _id.

    Writers call this inside their ledger transaction. A concurrently committed
    direct binding either wins the initial upsert or conflicts with this write;
    neither path can overwrite the winning mode. Existing unbound Langfuse data
    needs no migration merely to record its already configured source mode.
    """
    await guard_source_mode(db, "langfuse", session=session)
    options = {"session": session} if session is not None else {}
    await db.guardian_state.update_one({"_id": "capture_binding"},
        {"$setOnInsert": {"mode": "langfuse", "fence": 0}}, upsert=True, **options)
    result = await db.guardian_state.update_one({"_id": "capture_binding", "mode": "langfuse"},
        {"$inc": {"fence": 1}}, **options)
    if result.matched_count != 1:
        raise CaptureError(503, "capture_mode_mismatch")


async def ensure_direct_binding(db, settings, session=None, touch=False):
    if load_capture_mode() != "direct" or settings.mode != "oidc":
        raise CaptureError(503, "direct_capture_not_configured")
    identity = IdentityStore(db, settings)
    await identity._check_binding(session, touch=touch)
    options = {"session": session} if session is not None else {}
    expected = {"_id": "capture_binding", "mode": "direct", "binding_id": identity.binding_id,
                "connection_id": settings.connection_id, "normalization_version": NORMALIZATION_VERSION}
    collection = identity._collection("guardian_state")
    binding = await collection.find_one({"_id": "capture_binding"}, max_time_ms=2000, **options)
    if not binding:
        ledger = await collection.find_one({"_id": "ledger_configuration"}, max_time_ms=2000, **options)
        worker = await collection.find_one({"_id": "guardian_worker_cursor"}, max_time_ms=2000, **options) or {}
        if (ledger or worker.get("active_window") or worker.get("last_polled_at")
                or worker.get("source_api_version") not in (None, SOURCE_API_VERSION)):
            raise CaptureError(503, "capture_migration_required")
        for name in ("guardian_observations", "guardian_metrics", "guardian_incidents", "guardian_quarantine"):
            if await db[name].find_one({}, {"_id": 1}, max_time_ms=2000, **options):
                raise CaptureError(503, "capture_migration_required")
        await collection.update_one({"_id": "capture_binding"},
            {"$setOnInsert": {**expected, "fence": 0}}, upsert=True, **options)
    if touch:
        result = await collection.update_one(expected, {"$inc": {"fence": 1}}, **options)
        valid = result.matched_count
    else:
        valid = await collection.find_one(expected, max_time_ms=2000, **options)
    if not valid:
        raise CaptureError(503, "capture_binding_mismatch")
    ledger = await collection.find_one({"_id": "ledger_configuration"}, max_time_ms=2000, **options)
    if ledger and (ledger.get("connection_id") != settings.connection_id
                   or ledger.get("source_api_version") not in (None, SOURCE_API_VERSION)):
        raise CaptureError(503, "capture_migration_required")
    return expected
