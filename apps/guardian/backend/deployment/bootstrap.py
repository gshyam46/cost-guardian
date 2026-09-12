"""Explicit bounded schema initialization; never migrate or reset existing data."""
import asyncio
from datetime import datetime, timezone

from pymongo.errors import CollectionInvalid, DuplicateKeyError, OperationFailure

from capture.settings import NORMALIZATION_VERSION, SOURCE_API_VERSION, ensure_direct_binding
from guardian.ledger import LEDGER_VERSION, ObservationLedger
from identity.store import IdentityStore
from .errors import DeploymentError

MARKER_ID = "deployment_initialization"
SCHEMA_VERSION = 1


async def capability(db):
    result = await db.command("hello", maxTimeMS=2000)
    if (not result.get("setName") or result.get("isWritablePrimary") is not True
            or result.get("logicalSessionTimeoutMinutes") is None or result.get("maxWireVersion", 0) < 7):
        raise DeploymentError("transaction_database_required")


async def matching_state(db, configuration, *, initialized=False, session=None):
    """Read-only validation also used before any bootstrap index/state writes."""
    identity = IdentityStore(db, configuration.identity)
    options = {"session": session} if session is not None else {}
    states = {}
    for name in ("identity_binding", "capture_binding", "ledger_configuration", MARKER_ID):
        states[name] = await db.guardian_state.find_one({"_id": name}, max_time_ms=2000, **options)
    expected = {
        "identity_binding": configuration.identity.binding,
        "capture_binding": {"mode": "direct", "binding_id": identity.binding_id,
            "connection_id": configuration.identity.connection_id, "normalization_version": NORMALIZATION_VERSION},
        "ledger_configuration": {"connection_id": configuration.identity.connection_id,
            "version": LEDGER_VERSION, "source_api_version": SOURCE_API_VERSION,
            "normalization_version": NORMALIZATION_VERSION},
        MARKER_ID: {"schema_version": SCHEMA_VERSION, "binding_id": identity.binding_id},
    }
    for name, fields in expected.items():
        current = states[name]
        if current and any(current.get(key) != value for key, value in fields.items()):
            raise DeploymentError("deployment_binding_mismatch")
        if initialized and not current:
            raise DeploymentError("deployment_not_initialized")
    if (states["capture_binding"] and not states["identity_binding"]
            or states[MARKER_ID] and any(not states[name] for name in expected if name != MARKER_ID)):
        raise DeploymentError("deployment_binding_mismatch")
    if await db.guardian_metrics.find_one({"accounting_status": {"$ne": LEDGER_VERSION}}, {"_id": 1}, max_time_ms=2000, **options):
        raise DeploymentError("legacy_migration_required")
    if not states["capture_binding"]:
        worker = await db.guardian_state.find_one({"_id": "guardian_worker_cursor"}, max_time_ms=2000, **options) or {}
        if states["ledger_configuration"] or worker.get("active_window") or worker.get("last_polled_at"):
            raise DeploymentError("legacy_migration_required")
        for name in ("guardian_observations", "guardian_metrics", "guardian_incidents", "guardian_quarantine", "guardian_capture_inbox"):
            if await db[name].find_one({}, {"_id": 1}, max_time_ms=2000, **options):
                raise DeploymentError("legacy_migration_required")
    return identity


async def ensure_indexes(db, configuration):
    from capture.service import CaptureService
    from guardian.summaries import ensure_summary_indexes
    from notifications.outbox import ensure_indexes as ensure_notification_indexes

    # Avoid first-use collection creation inside concurrent initialization TXs.
    for name in ("guardian_state", "guardian_monitoring_policies", "guardian_notification_settings"):
        try:
            await db.create_collection(name)
        except CollectionInvalid:
            pass
        except OperationFailure as error:
            if error.code != 48:
                raise
    await IdentityStore(db, configuration.identity)._indexes()
    await CaptureService(db, configuration.identity).ensure_indexes()
    await ObservationLedger(db, configuration.identity.connection_id).ensure_indexes()
    await ensure_summary_indexes(db)
    await ensure_notification_indexes(db)
    await db.guardian_capture_inbox.create_index([("connection_id", 1), ("processed", 1), ("sequence", 1)], maxTimeMS=2000)
    # Policy/head and credential/receipt identities already use Mongo's unique _id.


async def bootstrap(db, configuration):
    from policies.store import _head as policy_head
    from notifications.control import read_head as notification_head
    try:
        async with asyncio.timeout(45):
            await capability(db)
            await matching_state(db, configuration)
            await ensure_indexes(db, configuration)
            ledger = ObservationLedger(db, configuration.identity.connection_id)

            async def initialize(session):
                options = {"session": session} if session is not None else {}
                identity = await matching_state(db, configuration, session=session)
                await db.guardian_state.update_one({"_id": "identity_binding"},
                    {"$setOnInsert": {**configuration.identity.binding, "fence": 0}}, upsert=True, **options)
                await identity._check_binding(session, touch=True)
                await ensure_direct_binding(db, configuration.identity, session=session, touch=True)
                await ledger._migration_guard(session)
                await db.guardian_state.update_one({"_id": "ledger_configuration"},
                    {"$set": {"source_api_version": SOURCE_API_VERSION, "normalization_version": NORMALIZATION_VERSION}}, **options)
                await policy_head(db, configuration.identity.connection_id, session, create=True)
                await notification_head(db, configuration.identity.connection_id, session, create=True)
                await db.guardian_state.update_one({"_id": MARKER_ID}, {"$setOnInsert": {
                    "schema_version": SCHEMA_VERSION, "binding_id": identity.binding_id,
                    "created_at": datetime.now(timezone.utc)}}, upsert=True, **options)

            for attempt in range(3):
                try:
                    await ledger.transaction(initialize)
                    break
                except DuplicateKeyError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.02)
            await matching_state(db, configuration, initialized=True)
    except DeploymentError:
        raise
    except Exception:
        raise DeploymentError("bootstrap_unavailable") from None
