"""One bounded Slack POST; no retries, redirects, proxies or receiver text logs."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import math
import re

import httpx

TOTAL_SECONDS = 10
MAX_RESPONSE_BYTES = 8192
ACTIVE = ContextVar("notification_transport_active", default=False)


class _PrivateRequest(logging.Filter):
    def filter(self, record):
        return not ACTIVE.get()


for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateRequest())


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    accepted: bool = False
    retryable: bool = False
    unconfirmed: bool = False
    retry_after: int | None = None


def retry_after(value, now=None):
    if type(value) is not str or len(value) > 100:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,12}", value):
        # Larger hints expire the 24-hour cycle instead of scheduling an early send.
        return min(86401, max(1, int(value)))
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.utcoffset() is None:
            return None
        seconds = (stamp.astimezone(timezone.utc) - (now or datetime.now(timezone.utc))).total_seconds()
        return min(86401, max(1, math.ceil(seconds)))
    except (ValueError, TypeError, OverflowError):
        return None


class SlackTransport:
    def __init__(self, *, http_transport=None):
        # Injection replaces the HTTP boundary in tests; production destination
        # validation always remains owned by NotificationSettings.
        self.http_transport = http_transport

    async def send(self, settings, payload):
        if settings.state != "configured":
            return DeliveryResult("invalid_delivery")
        token = ACTIVE.set(True)
        try:
            async with asyncio.timeout(TOTAL_SECONDS):
                async with httpx.AsyncClient(transport=self.http_transport, timeout=5,
                        follow_redirects=False, trust_env=False) as client:
                    async with client.stream("POST", settings.webhook_url, json=payload,
                            headers={"Content-Type": "application/json", "Accept-Encoding": "identity"}) as response:
                        hint = retry_after(response.headers.get("retry-after"))
                        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                            return DeliveryResult("invalid_response", retryable=True, unconfirmed=True, retry_after=hint)
                        content = bytearray()
                        async def raw_chunks():
                            if response.is_stream_consumed:  # Preloaded injected test responses only.
                                yield response.content
                            else:
                                async for chunk in response.aiter_raw():
                                    yield chunk
                        async for chunk in raw_chunks():
                            if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                                return DeliveryResult("response_too_large", retryable=True, unconfirmed=True, retry_after=hint)
                            content.extend(chunk)
                        if response.status_code == 200 and bytes(content) == b"ok":
                            return DeliveryResult("accepted", accepted=True)
                        if response.status_code == 429:
                            return DeliveryResult("rate_limited", retryable=True, retry_after=hint)
                        if 500 <= response.status_code < 600:
                            return DeliveryResult("receiver_unavailable", retryable=True, retry_after=hint)
                        if 200 <= response.status_code < 300:
                            return DeliveryResult("invalid_response", retryable=True, unconfirmed=True, retry_after=hint)
                        return DeliveryResult("receiver_rejected")
        except (TimeoutError, httpx.TimeoutException):
            return DeliveryResult("timeout_unconfirmed", retryable=True, unconfirmed=True)
        except Exception:
            return DeliveryResult("network_unconfirmed", retryable=True, unconfirmed=True)
        finally:
            ACTIVE.reset(token)
