"""Strict content-free policy values, shared by API persistence and evaluation."""
import asyncio
import re

from capture.errors import CaptureError
from capture.schema import parse_json
from .errors import PolicyError

DEFAULT_RULES = {"max_call_cost_usd": None, "max_call_latency_ms": None, "alert_on_errors": True}
MAX_REVISION = 2**31 - 1
MAX_BODY_BYTES = 8192
COST = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?\Z")


def valid_revision(value):
    return type(value) is int and 0 <= value <= MAX_REVISION


def validate_rules(value):
    if type(value) is not dict or set(value) != set(DEFAULT_RULES):
        raise ValueError("invalid_policy_rules")
    cost, latency, errors = value["max_call_cost_usd"], value["max_call_latency_ms"], value["alert_on_errors"]
    if cost is not None and (type(cost) is not str or not COST.fullmatch(cost)):
        raise ValueError("invalid_policy_rules")
    if latency is not None and (type(latency) is not int or not 0 <= latency <= 86400000):
        raise ValueError("invalid_policy_rules")
    if type(errors) is not bool:
        raise ValueError("invalid_policy_rules")
    return {"max_call_cost_usd": cost, "max_call_latency_ms": latency, "alert_on_errors": errors}


def validate_snapshot(value):
    if type(value) is not dict or set(value) != {"revision", "rules"} or not valid_revision(value["revision"]):
        raise ValueError("invalid_policy_snapshot")
    rules = validate_rules(value["rules"])
    if value["revision"] == 0 and rules != DEFAULT_RULES:
        raise ValueError("invalid_policy_snapshot")
    return {"revision": value["revision"], "rules": rules}


async def read_request(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise PolicyError(415, "json_required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise PolicyError(413, "unsupported_encoding")
    lengths = request.headers.getlist("content-length")
    if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]) or int(lengths[0]) > MAX_BODY_BYTES):
        raise PolicyError(413, "body_too_large")
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_BODY_BYTES:
                    raise PolicyError(413, "body_too_large")
                raw.extend(chunk)
    except TimeoutError:
        raise PolicyError(400, "body_timeout") from None
    try:
        value = parse_json(bytes(raw))
        if type(value) is not dict or set(value) != {"expected_revision", "rules"} or not valid_revision(value["expected_revision"]):
            raise ValueError()
        return {"expected_revision": value["expected_revision"], "rules": validate_rules(value["rules"])}
    except (ValueError, CaptureError):
        raise PolicyError(400, "invalid_policy_request") from None
