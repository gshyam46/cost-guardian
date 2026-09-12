"""Wire outcome classification and safe raw-byte limits; no Slack traffic."""
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import logging

import httpx
import pytest

from notifications.settings import NotificationSettings
from notifications.transport import SlackTransport, retry_after

pytestmark = pytest.mark.anyio
SECRET = "private-webhook-secret-canary"
URL = "https://hooks.slack.com/services/TEAM/CHANNEL/" + SECRET
CONFIG = NotificationSettings(URL, "a" * 64, "https://guardian.example.invalid", "configured")
PAYLOAD = {"text": "Cost Guardian notification test", "mrkdwn": False, "unfurl_links": False, "unfurl_media": False}


@pytest.mark.parametrize("status,body,outcome,accepted,retryable,uncertain", [
    (200, b"ok", "accepted", True, False, False),
    (200, b"unexpected private response", "invalid_response", False, True, True),
    (201, b"ok", "invalid_response", False, True, True),
    (429, b"private rate limit", "rate_limited", False, True, False),
    (500, b"private failure", "receiver_unavailable", False, True, False),
    (503, b"private failure", "receiver_unavailable", False, True, False),
    (400, b"private failure", "receiver_rejected", False, False, False),
    (401, b"private failure", "receiver_rejected", False, False, False),
    (403, b"private failure", "receiver_rejected", False, False, False),
    (404, b"private failure", "receiver_rejected", False, False, False),
    (302, b"", "receiver_rejected", False, False, False),
])
async def test_exact_receiver_outcomes_never_include_response_body(status, body, outcome, accepted, retryable, uncertain):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=body, headers={"Location": "https://untrusted.invalid/secret"})

    result = await SlackTransport(http_transport=httpx.MockTransport(handler)).send(CONFIG, PAYLOAD)
    assert (result.outcome, result.accepted, result.retryable, result.unconfirmed) == (outcome, accepted, retryable, uncertain)
    assert len(calls) == 1
    assert json.loads(calls[0].content) == PAYLOAD
    assert "private" not in repr(result)


async def test_response_body_bound_and_compression_rejection():
    for headers, content, outcome in [({}, b"x" * 8193, "response_too_large"),
        ({"Content-Encoding": "gzip"}, b"unparsed compressed bytes", "invalid_response")]:
        response = httpx.Response(200, headers=headers, stream=httpx.ByteStream(content))
        result = await SlackTransport(http_transport=httpx.MockTransport(lambda request: response)).send(CONFIG, PAYLOAD)
        assert result.outcome == outcome and result.unconfirmed and result.retryable


async def test_retry_after_survives_rejection_of_oversized_or_encoded_body():
    for headers, content in [({}, b"x" * 8193), ({"Content-Encoding": "gzip"}, b"unparsed bytes")]:
        response = httpx.Response(429, headers={**headers, "Retry-After": "90"}, stream=httpx.ByteStream(content))
        result = await SlackTransport(http_transport=httpx.MockTransport(lambda request: response)).send(CONFIG, PAYLOAD)
        assert result.retry_after == 90 and result.unconfirmed


@pytest.mark.parametrize("error,outcome", [(httpx.ReadTimeout("private timeout"), "timeout_unconfirmed"),
    (httpx.RemoteProtocolError("private connection"), "network_unconfirmed")])
async def test_network_failures_are_redacted_and_unconfirmed(error, outcome):
    def handler(request):
        raise error
    result = await SlackTransport(http_transport=httpx.MockTransport(handler)).send(CONFIG, PAYLOAD)
    assert result.outcome == outcome and result.unconfirmed
    assert "private" not in repr(result)


async def test_total_deadline_cancels_stalled_transport(monkeypatch):
    import notifications.transport as module
    stopped = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(module, "TOTAL_SECONDS", .02)
    result = await SlackTransport(http_transport=httpx.MockTransport(handler)).send(CONFIG, PAYLOAD)
    assert result.outcome == "timeout_unconfirmed"
    assert stopped.is_set()


async def test_retry_after_delta_date_and_large_hints_respect_cycle_bound():
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    assert retry_after("60", now) == 60
    assert retry_after("999999999999", now) == 86401
    assert retry_after(format_datetime(now + timedelta(seconds=72), usegmt=True), now) == 72
    assert retry_after("0", now) == 1
    assert retry_after("-7", now) is None
    assert retry_after("private response", now) is None
    assert retry_after("Mon, 01 Jan 2024 01:00:00", now) is None
    response = httpx.Response(429, content=b"private", headers={"Retry-After": "72"})
    result = await SlackTransport(http_transport=httpx.MockTransport(lambda request: response)).send(CONFIG, PAYLOAD)
    assert result.retry_after == 72


async def test_http_client_debug_records_do_not_expose_webhook_or_headers(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request):
        logging.getLogger("httpcore.http11").debug("receiver headers %s", SECRET)
        return httpx.Response(200, content=b"ok", headers={"X-Private": SECRET})

    assert (await SlackTransport(http_transport=httpx.MockTransport(handler)).send(CONFIG, PAYLOAD)).accepted
    assert SECRET not in caplog.text and URL not in caplog.text


class Loopback(httpx.AsyncBaseTransport):
    """Only this test transport rewrites the exact synthetic Slack URL."""
    def __init__(self, port):
        self.port = port
        self.inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        assert str(request.url) == URL
        mapped = httpx.Request(request.method, f"http://127.0.0.1:{self.port}/receiver",
                               headers={"Content-Type": "application/json"}, content=await request.aread())
        return await self.inner.handle_async_request(mapped)

    async def aclose(self):
        await self.inner.aclose()


@pytest.mark.parametrize("acknowledge", [True, False])
async def test_actual_local_http_acceptance_and_lost_acknowledgement(acknowledge):
    received = []
    done = asyncio.Event()

    async def receiver(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            received.append(json.loads(await reader.readexactly(length)))
            if acknowledge:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(receiver, "127.0.0.1", 0)
    try:
        transport = SlackTransport(http_transport=Loopback(server.sockets[0].getsockname()[1]))
        result = await transport.send(CONFIG, PAYLOAD)
        await asyncio.wait_for(done.wait(), 2)
    finally:
        server.close()
        await server.wait_closed()
    assert received == [PAYLOAD]
    assert result.accepted is acknowledge
    assert result.unconfirmed is not acknowledge
    assert SECRET not in repr(result)
