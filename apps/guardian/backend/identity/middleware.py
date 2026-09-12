"""Do not cache protected Guardian responses across browser identities."""
from starlette.datastructures import MutableHeaders


class PrivateGuardianResponses:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/guardian/"):
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                vary = {value.strip().lower() for value in headers.get("Vary", "").split(",") if value.strip()}
                vary.update({"authorization", "x-guardian-key", "cookie", "origin"})
                headers["Vary"] = ", ".join(sorted(vary))
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.app(scope, receive, private_send)
