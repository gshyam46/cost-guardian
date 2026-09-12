import asyncio
from functools import wraps

from fastapi import HTTPException


class PolicyError(HTTPException):
    def __init__(self, status, code):
        self.code = code
        messages = {
            400: "The monitoring rules are invalid. Check the field values.",
            401: "Sign in again before accessing monitoring rules.",
            403: "Only a named project owner may change monitoring rules.",
            409: "Monitoring rules changed. Reload the saved rules before trying again.",
            413: "The monitoring request exceeds the supported size or encoding.",
            415: "Use an application/json body.",
            503: "Monitoring rules are unavailable. Retry shortly.",
        }
        headers = {"Cache-Control": "no-store", "Vary": "Cookie, Origin, Authorization, X-Guardian-Key"}
        if status == 503:
            headers["Retry-After"] = "5"
        super().__init__(status, {"code": code, "message": messages.get(status, "Monitoring request failed.")}, headers=headers)


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
                raise PolicyError(503, "policy_unavailable") from None
        return wrapped
    return decorate
