"""Guardian's own authentication.

Previously Guardian reused the monitored app's session cookies -- which only worked
because the two shared a process. As a standalone service it authenticates callers
itself, via a static API key sent as `X-Guardian-Key` (or `Authorization: Bearer ...`).

Deliberately minimal: Guardian is single-tenant right now ("watch my own stack"), so
one key is the honest amount of auth. Multi-tenant Guardian needs per-project keys
scoped to a Langfuse project -- see docs/PHASES.md Phase 7. Shipping a fake
multi-tenant auth layer now would be pretending to a capability that doesn't exist.
"""
import hmac

from fastapi import HTTPException, Request

from config import GUARDIAN_API_KEY


def require_api_key(request: Request) -> None:
    """Raise 401 unless the caller presented the configured API key."""
    if not GUARDIAN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "GUARDIAN_API_KEY is not configured. Set it in apps/guardian/backend/.env "
                "-- Guardian refuses to serve data rather than run unauthenticated."
            ),
        )

    presented = request.headers.get("X-Guardian-Key", "")
    if not presented:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            presented = auth_header[7:]

    # compare_digest keeps the check constant-time so the key can't be recovered by
    # timing repeated requests.
    if not presented or not hmac.compare_digest(presented, GUARDIAN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing Guardian API key")
