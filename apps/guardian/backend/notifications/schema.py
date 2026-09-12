"""Bounded strict owner commands; URL and payload fields are never accepted."""
import asyncio
import re
import uuid

from capture.errors import CaptureError
from capture.schema import parse_json
from .errors import NotificationError

MAX_REVISION = 2**31 - 1
MAX_BODY_BYTES = 4096


def validate_command(value):
    if type(value) is not dict:
        raise ValueError()
    action = value.get("action")
    fields = {"expected_revision", "request_id", "action"}
    if action == "retry":
        fields.add("delivery_id")
    if set(value) != fields or action not in {"test", "enable", "disable", "retry"}:
        raise ValueError()
    revision, request_id = value["expected_revision"], value["request_id"]
    if type(revision) is not int or not 0 <= revision < MAX_REVISION:
        raise ValueError()
    if type(request_id) is not str or len(request_id) != 36 or str(uuid.UUID(request_id)) != request_id:
        raise ValueError()
    if action == "retry" and (type(value["delivery_id"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value["delivery_id"])):
        raise ValueError()
    return dict(value)


async def read_request(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise NotificationError(415, "json_required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise NotificationError(413, "unsupported_encoding")
    lengths = request.headers.getlist("content-length")
    if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]) or int(lengths[0]) > MAX_BODY_BYTES):
        raise NotificationError(413, "body_too_large")
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_BODY_BYTES:
                    raise NotificationError(413, "body_too_large")
                raw.extend(chunk)
    except TimeoutError:
        raise NotificationError(400, "body_timeout") from None
    try:
        return validate_command(parse_json(bytes(raw)))
    except (ValueError, TypeError, AttributeError, CaptureError):
        raise NotificationError(400, "invalid_notification_request") from None
