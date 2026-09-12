"""Authenticated notification status and explicit owner delivery actions."""
from dataclasses import replace

from fastapi import APIRouter, Request

from auth import require_access
from config import GUARDIAN_CONNECTION_ID
from db import db
from identity.routes import require_csrf
from identity.settings import load_settings
from .control import NotificationStore
from .errors import NotificationError, bounded
from .schema import read_request

router = APIRouter(prefix="/guardian", tags=["notifications"])


@router.get("/notifications")
@bounded()
async def get_notifications(request: Request):
    principal = await require_access(request, db)
    settings = load_settings()
    if settings.mode == "api_key":
        settings = replace(settings, connection_id=GUARDIAN_CONNECTION_ID)
    values = request.query_params.getlist("incident_id")
    if len(values) > 1 or set(request.query_params) - {"incident_id"}:
        raise NotificationError(400, "invalid_notification_query")
    return await NotificationStore(db, settings).get(principal, values[0] if values else None)


@router.post("/notifications/actions")
@bounded(45)
async def notification_action(request: Request):
    principal = await require_access(request, db)
    if principal is None or principal.actor["role"] != "owner":
        raise NotificationError(403, "owner_required")
    settings = load_settings()
    require_csrf(request, settings, principal)
    body = await read_request(request)
    return await NotificationStore(db, settings).command(principal, **body)
