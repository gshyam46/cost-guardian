import asyncio
from functools import wraps

from fastapi import HTTPException


class NotificationError(HTTPException):
    def __init__(self, status, code):
        self.code = code
        messages = {
            400: "The notification request is invalid.",
            401: "Sign in again before accessing notifications.",
            403: "Only a named project owner may change notifications.",
            404: "The incident or delivery is unavailable.",
            409: "Notification state changed or this action is unavailable. Refresh before trying again.",
            413: "The notification request exceeds the supported size or encoding.",
            415: "Use an application/json body.",
            503: "Notifications are unavailable. Retry shortly.",
        }
        headers = {"Cache-Control": "no-store", "Vary": "Cookie, Origin, Authorization, X-Guardian-Key"}
        if status == 503:
            headers["Retry-After"] = "5"
        super().__init__(status, {"code": code, "message": messages.get(status, "Notification request failed.")}, headers=headers)


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
                raise NotificationError(503, "notifications_unavailable") from None
        return wrapped
    return decorate
