import asyncio
from functools import wraps

from fastapi import HTTPException


class CaptureError(HTTPException):
    def __init__(self, status, code):
        self.code = code
        messages = {400: "The capture request is invalid. Check the documented format.",
            401: "The ingestion credential is invalid, expired or revoked.",
            403: "Only a project owner may manage ingestion credentials.",
            404: "The ingestion credential was not found.",
            409: "This request conflicts with an earlier request. Refresh state before retrying.",
            413: "The capture body or encoding exceeds the supported limit.",
            415: "Use an application/json body.",
            429: "Capture capacity is temporarily unavailable. Retry after the indicated delay.",
            503: "Capture is unavailable. Retry shortly or contact your Guardian operator."}
        headers = {"Cache-Control": "no-store", "Vary": "Cookie, Origin, X-Guardian-Ingest-Key"}
        if status in (429, 503):
            headers["Retry-After"] = "60" if status == 429 else "5"
        super().__init__(status, {"code": code, "message": messages.get(status, "Capture request failed.")}, headers=headers)


def bounded(seconds=5):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            try:
                async with asyncio.timeout(seconds):
                    return await function(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                raise CaptureError(503, "capture_unavailable") from None
        return wrapped
    return decorate
