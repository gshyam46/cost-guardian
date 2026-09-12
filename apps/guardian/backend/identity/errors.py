"""Only fixed, public diagnostics cross the identity boundary."""
from fastapi import HTTPException

HEADERS = {"Cache-Control": "no-store", "Vary": "Cookie, Origin"}


class IdentityError(HTTPException):
    def __init__(self, status, code):
        self.code = code
        messages = {
            401: "Your Guardian session has expired or is unavailable. Sign in again.",
            403: "You do not have permission for this action.",
            404: "Incident not found.",
            429: "Too many sign-in attempts. Retry in five minutes.",
            503: "Guardian access is unavailable. Contact your Guardian operator or retry shortly.",
        }
        headers = dict(HEADERS)
        if status in (429, 503):
            headers["Retry-After"] = "300" if status == 429 else "5"
        super().__init__(status_code=status, detail=messages.get(status, "Sign-in failed. Try again."), headers=headers)
