"""Mode-specific Guardian access. Verified access does not imply telemetry health."""
import hmac

from fastapi import HTTPException, Request

from config import GUARDIAN_API_KEY
from identity.errors import IdentityError
from identity.settings import load_settings
from identity.store import IdentityStore
from capture.settings import ensure_direct_binding, guard_source_mode, load_capture_mode
from capture.errors import bounded as capture_bounded

AUTH_CACHE_HEADERS = {"Cache-Control": "no-store", "Vary": "Authorization, X-Guardian-Key"}


def require_api_key(request: Request) -> None:
    """Raise 401 unless the caller presented the configured API key."""
    if not GUARDIAN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Guardian access is not configured. Contact your Guardian operator.",
            headers=AUTH_CACHE_HEADERS,
        )

    presented = request.headers.get("X-Guardian-Key", "")
    if not presented:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            presented = auth_header[7:]

    # compare_digest keeps the check constant-time so the key can't be recovered by
    # timing repeated requests.
    if not presented or not hmac.compare_digest(presented.encode("utf-8"), GUARDIAN_API_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing Guardian API key", headers=AUTH_CACHE_HEADERS)


async def require_access(request: Request, db, *, mutation=False):
    settings = load_settings()
    if settings.mode == "api_key":
        require_api_key(request)
        await _source_boundary(request, db, settings)
        return None
    try:
        principal = await IdentityStore(db, settings).authenticate(request.cookies.get(settings.session_cookie))
    except IdentityError:
        raise
    except Exception:
        raise IdentityError(503, "identity_store_unavailable") from None
    await _source_boundary(request, db, settings)
    if mutation:
        if "resolve_incidents" not in principal.permissions:
            raise IdentityError(403, "mutation_denied")
        from identity.routes import require_csrf
        require_csrf(request, settings, principal)
    return principal


@capture_bounded()
async def _source_boundary(request, db, settings):
    # Access verification is independent of source readiness. Data paths check
    # the persisted boundary before touching any source/cache/store.
    if request.url.path == "/api/guardian/access":
        return
    mode = load_capture_mode()
    if mode == "direct":
        await ensure_direct_binding(db, settings)
    else:
        await guard_source_mode(db, mode)
