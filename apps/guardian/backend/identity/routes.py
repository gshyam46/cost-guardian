"""Browser OIDC endpoints. Provider tokens never leave the server callback."""
import asyncio
import hmac
import logging

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from db import db
from .errors import HEADERS, IdentityError
from .settings import load_settings
from .store import FLOW_SECONDS, SESSION_SECONDS, IdentityStore

router = APIRouter(prefix="/guardian/auth", tags=["identity"])
logger = logging.getLogger(__name__)
_provider_slots = asyncio.Semaphore(4)


def provider_factory(settings):
    from .oidc_provider import OIDCProvider
    return OIDCProvider(settings.issuer, settings.client_id, settings.client_secret, settings.redirect_uri,
                        allow_loopback_http=settings.allow_loopback_http)


def require_csrf(request, settings, principal):
    origins = request.headers.getlist("origin")
    csrf_values = request.headers.getlist("x-guardian-csrf")
    if (origins != [settings.ui_origin] or len(csrf_values) != 1 or len(csrf_values[0]) > 256
            or not hmac.compare_digest(csrf_values[0].encode("utf-8"), principal.csrf_token.encode("utf-8"))):
        raise IdentityError(403, "invalid_csrf")


def _oidc_settings():
    settings = load_settings()
    if settings.mode != "oidc":
        raise IdentityError(404, "oidc_disabled")
    return settings


def _set_cookie(response, settings, name, value, seconds):
    response.set_cookie(name, value, max_age=seconds, secure=settings.secure_cookies,
                        httponly=True, samesite="lax", path="/")


def _clear_cookie(response, settings, name):
    response.delete_cookie(name, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")


async def _provider_operation(operation):
    try:
        await asyncio.wait_for(_provider_slots.acquire(), timeout=0.25)
    except TimeoutError:
        raise IdentityError(503, "provider_busy") from None
    try:
        async with asyncio.timeout(16):
            return await operation()
    finally:
        _provider_slots.release()


@router.get("/config")
async def get_config():
    settings = load_settings()
    return JSONResponse({"auth_mode": settings.mode,
                         "login_path": "/api/guardian/auth/login" if settings.mode == "oidc" else None}, headers=HEADERS)


@router.get("/login")
async def login(request: Request):
    settings = _oidc_settings()
    store = IdentityStore(db, settings)
    flow = await store.create_flow(request.client.host if request.client else "unknown")
    try:
        provider = provider_factory(settings)
        url = await _provider_operation(lambda: provider.start(flow["state"], flow["nonce"], flow["code_verifier"]))
    except Exception:
        raise IdentityError(503, "provider_unavailable") from None
    response = RedirectResponse(url, status_code=302, headers={**HEADERS, "Referrer-Policy": "no-referrer"})
    _set_cookie(response, settings, settings.login_cookie, flow["browser_token"], FLOW_SECONDS)
    return response


@router.get("/callback")
async def callback(request: Request):
    settings = _oidc_settings()
    store = IdentityStore(db, settings)
    try:
        query = request.query_params
        if len(query.getlist("state")) != 1:
            raise IdentityError(401, "invalid_state")
        flow = await store.consume_flow(query.get("state"), request.cookies.get(settings.login_cookie))
        codes = query.getlist("code")
        if query.getlist("error") or len(codes) != 1 or not 1 <= len(codes[0]) <= 4096 or any(ord(c) < 32 for c in codes[0]):
            raise IdentityError(401, "invalid_callback")
        provider = provider_factory(settings)
        claims = await _provider_operation(lambda: provider.finish(codes[0], flow))
        token = await store.create_session(claims, request.cookies.get(settings.session_cookie))
    except Exception:
        logger.info("Guardian sign-in did not complete")
        response = RedirectResponse(settings.ui_origin + "/?guardian_login=failed", status_code=303,
                                    headers={**HEADERS, "Referrer-Policy": "no-referrer"})
    else:
        response = RedirectResponse(settings.ui_origin + "/?guardian_login=complete", status_code=303,
                                    headers={**HEADERS, "Referrer-Policy": "no-referrer"})
        _set_cookie(response, settings, settings.session_cookie, token, SESSION_SECONDS)
    _clear_cookie(response, settings, settings.login_cookie)
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request):
    settings = _oidc_settings()
    store = IdentityStore(db, settings)
    principal = await store.authenticate(request.cookies.get(settings.session_cookie))
    require_csrf(request, settings, principal)
    await store.logout(principal)
    response = Response(status_code=204, headers=HEADERS)
    _clear_cookie(response, settings, settings.session_cookie)
    _clear_cookie(response, settings, settings.login_cookie)
    return response
