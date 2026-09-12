"""Read monitoring rules and save one owner-authorized revision."""
from dataclasses import replace

from fastapi import APIRouter, Request

from auth import require_access
from config import GUARDIAN_CONNECTION_ID
from db import db
from identity.routes import require_csrf
from identity.settings import load_settings
from .errors import PolicyError, bounded
from .schema import read_request
from .store import PolicyStore

router = APIRouter(prefix="/guardian", tags=["monitoring rules"])


@router.get("/monitoring-policy")
@bounded()
async def get_policy(request: Request):
    principal = await require_access(request, db)
    settings = load_settings()
    if settings.mode == "api_key":
        settings = replace(settings, connection_id=GUARDIAN_CONNECTION_ID)
    return await PolicyStore(db, settings).get(principal)


@router.put("/monitoring-policy")
@bounded(40)
async def save_policy(request: Request):
    principal = await require_access(request, db)
    if principal is None or principal.actor["role"] != "owner":
        raise PolicyError(403, "owner_required")
    settings = load_settings()
    require_csrf(request, settings, principal)
    body = await read_request(request)
    return await PolicyStore(db, settings).save(principal, **body)
