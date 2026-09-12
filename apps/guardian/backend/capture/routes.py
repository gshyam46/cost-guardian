"""Named credential management and isolated machine-only event admission."""
import asyncio

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from auth import require_access
from db import db
from identity.routes import require_csrf
from identity.settings import load_settings
from .credentials import IngestionCredentialStore
from .errors import CaptureError, bounded
from .schema import decode_batch, read_json
from .service import CaptureService
from .settings import ensure_direct_binding, load_capture_mode

router = APIRouter(prefix="/guardian", tags=["capture"])
_intake_slots = asyncio.Semaphore(4)
LIMITS = {"max_batch_events": 100, "max_body_bytes": 262144, "max_active_keys": 10, "max_keys": 100}


async def _named(request, owner=False):
    principal = await require_access(request, db)
    if principal is None:
        raise CaptureError(403, "named_access_required")
    settings = load_settings()
    if owner:
        if principal.actor["role"] != "owner":
            raise CaptureError(403, "owner_required")
        require_csrf(request, settings, principal)
    await ensure_direct_binding(db, settings)
    return principal, settings


@router.get("/capture")
@bounded()
async def get_capture(request: Request):
    principal = await require_access(request, db)
    mode = load_capture_mode()
    direct = mode == "direct"
    if direct and principal is None:
        raise CaptureError(503, "direct_capture_not_configured")
    status = await CaptureService(db, load_settings()).status() if direct else None
    return {"mode": mode, "enabled": direct, "schema_version": 1,
        "collector_path": "/api/guardian/ingest/events", "can_manage_keys": direct and principal.actor["role"] == "owner",
        "project": principal.project if principal else None, "limits": LIMITS, "status": status}


@router.get("/ingestion-keys")
@bounded()
async def list_keys(request: Request):
    principal, settings = await _named(request)
    return {"credentials": await IngestionCredentialStore(db, settings).list(principal)}


@router.post("/ingestion-keys", status_code=201)
@bounded(40)
async def create_key(request: Request):
    principal, settings = await _named(request, owner=True)
    body = await read_json(request)
    if not isinstance(body, dict) or set(body) != {"request_id", "label", "expires_in_days"}:
        raise CaptureError(400, "invalid_credential_request")
    return await IngestionCredentialStore(db, settings).create(principal, body["label"], body["expires_in_days"], body["request_id"])


@router.post("/ingestion-keys/{credential_id}/revoke")
@bounded(40)
async def revoke_key(credential_id: str, request: Request):
    principal, settings = await _named(request, owner=True)
    return await IngestionCredentialStore(db, settings).revoke(principal, credential_id)


@router.post("/ingest/events", status_code=202)
@bounded(45)
async def ingest_events(request: Request):
    settings = load_settings()
    if load_capture_mode() != "direct" or settings.mode != "oidc":
        raise CaptureError(503, "direct_capture_not_configured")
    headers = request.headers.getlist("x-guardian-ingest-key")
    if len(headers) != 1:
        raise CaptureError(401, "invalid_ingestion_credential")
    token = headers[0]
    await IngestionCredentialStore(db, settings).authenticate_ingestion(token)
    try:
        await asyncio.wait_for(_intake_slots.acquire(), timeout=0.25)
    except TimeoutError:
        raise CaptureError(503, "capture_busy") from None
    try:
        batch = decode_batch(await read_json(request), settings)
        service = CaptureService(db, settings)
        await service.ensure_indexes()
        result = await service.ingest(token, batch)
        return JSONResponse(result, status_code=202)
    finally:
        _intake_slots.release()
