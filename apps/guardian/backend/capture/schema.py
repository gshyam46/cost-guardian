"""Strict numeric terminal events. Never return raw validation input in errors."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re
from uuid import UUID

from guardian.models import TraceMetric
from .errors import CaptureError

MAX_BODY_BYTES = 262144
MAX_BATCH_EVENTS = 100
MAX_TOKENS = 2**53 - 1
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
COST = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?\Z")


@dataclass(frozen=True)
class Batch:
    batch_id: str
    test_mode: bool
    metrics: list


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _constant(_value):
    raise ValueError()


def parse_json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise CaptureError(400, "invalid_json") from None


async def read_json(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise CaptureError(415, "json_required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise CaptureError(413, "unsupported_encoding")
    lengths = request.headers.getlist("content-length")
    if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]) or int(lengths[0]) > MAX_BODY_BYTES):
        raise CaptureError(413, "body_too_large")
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_BODY_BYTES:
                    raise CaptureError(413, "body_too_large")
                raw.extend(chunk)
    except TimeoutError:
        raise CaptureError(400, "body_timeout") from None
    return parse_json(bytes(raw))


def _stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError()
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError()
    return stamp.astimezone(timezone.utc)


def _tokens(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_TOKENS):
        raise ValueError()
    return value


def decode_batch(body, settings, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        if not isinstance(body, dict) or set(body) != {"schema_version", "batch_id", "test_mode", "events"}:
            raise ValueError()
        if type(body["schema_version"]) is not int or body["schema_version"] != 1 or type(body["test_mode"]) is not bool:
            raise ValueError()
        if not isinstance(body["batch_id"], str) or len(body["batch_id"]) != 36:
            raise ValueError()
        batch_id = str(UUID(body["batch_id"]))
        if batch_id != body["batch_id"].lower():
            raise ValueError()
        events = body["events"]
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_BATCH_EVENTS:
            raise ValueError()
        required = {"observation_id", "trace_id", "agent_name", "model", "started_at", "ended_at", "status"}
        optional = {"parent_observation_id", "cost_usd", "input_tokens", "output_tokens", "total_tokens"}
        metrics = []
        for row in events:
            if not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional:
                raise ValueError()
            for field in ("observation_id", "trace_id", "parent_observation_id"):
                value = row.get(field)
                if field == "parent_observation_id" and value is None:
                    continue
                if not isinstance(value, str) or not ID.fullmatch(value):
                    raise ValueError()
            for field in ("agent_name", "model"):
                if not isinstance(row[field], str) or not LABEL.fullmatch(row[field]):
                    raise ValueError()
            if row["status"] not in ("success", "error", "unknown"):
                raise ValueError()
            start, end = _stamp(row["started_at"]), _stamp(row["ended_at"])
            if start < now - timedelta(hours=24) or end < start or max(start, end) > now + timedelta(minutes=5):
                raise ValueError()
            # Compare original instants before normalizing storage precision.
            start = start.replace(microsecond=(start.microsecond // 1000) * 1000)
            end = end.replace(microsecond=(end.microsecond // 1000) * 1000)
            cost = row.get("cost_usd")
            if cost is not None:
                if not isinstance(cost, str) or not COST.fullmatch(cost):
                    raise ValueError()
                cost = format(Decimal(cost).normalize(), "f")
            input_tokens, output_tokens, total = (_tokens(row.get(field)) for field in ("input_tokens", "output_tokens", "total_tokens"))
            if input_tokens is not None and output_tokens is not None:
                derived = _tokens(input_tokens + output_tokens)
                if total is not None and total != derived:
                    raise ValueError()
                total = derived
            metrics.append(TraceMetric(trace_id=row["trace_id"], observation_id=row["observation_id"],
                agent_name=row["agent_name"], model=row["model"], cost_usd=float(cost) if cost is not None else None,
                cost_usd_decimal=cost, total_tokens=total, input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=(end - start).total_seconds() * 1000, status=row["status"], timestamp=start, ended_at=end,
                completion_state="complete", source="guardian_direct", project_id=settings.project_id,
                environment=settings.environment, parent_observation_id=row.get("parent_observation_id")))
        return Batch(batch_id, body["test_mode"], metrics)
    except (TypeError, ValueError, KeyError, OverflowError):
        raise CaptureError(400, "invalid_event_batch") from None
