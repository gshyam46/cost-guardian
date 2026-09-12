"""Strict native event validation and bounded request-body handling."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from capture import schema
from capture.errors import CaptureError

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(project_id="configured-project", environment="configured-environment")
PRIVATE = "private-prompt-and-secret-canary"


def event(**changes):
    value = {"observation_id": "call-one", "trace_id": "trace-one", "agent_name": "answer-agent",
        "model": "provider/model", "started_at": (NOW - timedelta(seconds=1)).isoformat(),
        "ended_at": NOW.isoformat(), "status": "success", "cost_usd": "0.001200",
        "input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    return {**value, **changes}


def body(**changes):
    return {"schema_version": 1, "batch_id": "38aca0cb-e357-4e16-a314-ef031ae4c33d",
            "test_mode": False, "events": [event()], **changes}


def decode(value):
    return schema.decode_batch(value, SETTINGS, now=NOW)


def test_scope_is_server_owned_and_cost_preserves_decimal_meaning():
    metric = decode(body()).metrics[0]
    assert metric.project_id == SETTINGS.project_id
    assert metric.environment == SETTINGS.environment
    assert metric.source == "guardian_direct"
    assert metric.cost_usd_decimal == "0.0012"
    assert metric.cost_usd == .0012
    assert metric.latency_ms == 1000
    assert metric.output_text is None


def test_null_measurements_remain_unknown_and_explicit_zero_known():
    unknown = event(cost_usd=None, input_tokens=None, output_tokens=None, total_tokens=None)
    zero = event(cost_usd="0", input_tokens=0, output_tokens=0, total_tokens=0)
    missing = event()
    for field in ("cost_usd", "input_tokens", "output_tokens", "total_tokens"):
        del missing[field]
    values = decode(body(events=[unknown, zero, missing])).metrics
    assert values[0].cost_usd is None and values[0].total_tokens is None
    assert values[1].cost_usd == 0 and values[1].total_tokens == 0
    assert values[2].cost_usd is None and values[2].total_tokens is None


def test_total_is_derived_only_from_two_known_components():
    partial = event(input_tokens=10, output_tokens=None, total_tokens=None)
    split = event(input_tokens=10, output_tokens=2, total_tokens=None)
    assert decode(body(events=[partial])).metrics[0].total_tokens is None
    assert decode(body(events=[split])).metrics[0].total_tokens == 12


def test_aware_offsets_and_submillisecond_values_are_canonical_before_replay_fingerprint():
    one = event(started_at="2026-09-12T12:00:00.000900+00:00", ended_at="2026-09-12T12:00:01.123900Z")
    two = event(started_at="2026-09-12T17:30:00.000100+05:30", ended_at="2026-09-12T17:30:01.123100+05:30")
    first, second = decode(body(events=[one, two])).metrics
    assert first.timestamp == second.timestamp
    assert first.ended_at == second.ended_at
    assert first.latency_ms == second.latency_ms == 1123
    assert first.timestamp.microsecond == 0
    assert first.ended_at.microsecond == 123000


def test_submillisecond_reversed_terminal_order_is_rejected_before_flooring():
    with pytest.raises(CaptureError):
        decode(body(events=[event(started_at="2026-09-12T12:00:00.000900Z", ended_at="2026-09-12T12:00:00.000100Z")]))


@pytest.mark.parametrize("field,value", [
    ("cost_usd", "-1"), ("cost_usd", "1e-3"), ("cost_usd", "NaN"), ("cost_usd", "Infinity"),
    ("cost_usd", "1000000000"), ("cost_usd", "0.1234567890123"), ("cost_usd", 1), ("cost_usd", True),
    ("input_tokens", -1), ("input_tokens", 1.5), ("input_tokens", True), ("input_tokens", "1"),
    ("total_tokens", 2**53), ("total_tokens", 11), ("output_tokens", 2**53-1),
    ("observation_id", ""), ("trace_id", "contains space"), ("parent_observation_id", "../path"),
    ("agent_name", "unicode-\u00e9"), ("model", PRIVATE + "\n"), ("status", "running"),
    ("status", True), ("started_at", "2026-09-12T11:59:59"), ("started_at", "2026-02-30T00:00:00Z"),
    ("started_at", (NOW - timedelta(hours=24, seconds=1)).isoformat()),
    ("ended_at", (NOW - timedelta(seconds=2)).isoformat()),
    ("ended_at", (NOW + timedelta(minutes=5, seconds=1)).isoformat()),
])
def test_invalid_scalars_are_rejected_without_echo(field, value):
    with pytest.raises(CaptureError) as error:
        decode(body(events=[event(**{field: value})]))
    assert error.value.status_code == 400
    assert PRIVATE not in json.dumps(error.value.detail)


@pytest.mark.parametrize("field", ["output", "input", "prompt", "documents", "metadata", "status_message",
    "user_id", "session_id", "tags", "project_id", "source", "environment"])
def test_unknown_content_and_scope_fields_are_forbidden(field):
    with pytest.raises(CaptureError) as error:
        decode(body(events=[event(**{field: PRIVATE})]))
    assert PRIVATE not in str(error.value.detail)


@pytest.mark.parametrize("value", [None, [], {}, body(schema_version=True), body(schema_version=2),
    body(test_mode="false"), body(events=[]), body(events=[event()] * 101), body(batch_id="not-a-uuid"),
    body(extra=PRIVATE)])
def test_envelope_limits_are_strict(value):
    with pytest.raises(CaptureError):
        decode(value)


@pytest.mark.parametrize("raw", [b'{"field":1,"field":2}', b'{"parent":{"field":1,"field":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}', b'\xff', b'{', b'[' * 1100])
def test_json_duplicate_keys_nonfinite_utf8_and_depth_are_rejected(raw):
    with pytest.raises(CaptureError) as error:
        schema.parse_json(raw)
    assert error.value.code == "invalid_json"


def request(chunks, headers=None):
    items = iter(chunks)
    async def receive():
        return {"type": "http.request", "body": next(items), "more_body": True}
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers or [(b"content-type", b"application/json")]}, receive)


@pytest.mark.anyio
async def test_stream_body_size_limit_is_enforced_without_content_length():
    req = request([b"x" * 131072, b"x" * 131073])
    with pytest.raises(CaptureError) as error:
        await schema.read_json(req)
    assert (error.value.status_code, error.value.code) == (413, "body_too_large")


@pytest.mark.anyio
@pytest.mark.parametrize("headers,status", [
    ([(b"content-type", b"text/plain")], 415),
    ([(b"content-type", b"application/json"), (b"content-encoding", b"gzip")], 413),
    ([(b"content-type", b"application/json"), (b"content-length", b"262145")], 413),
    ([(b"content-type", b"application/json"), (b"content-length", b"2"), (b"content-length", b"2")], 413),
])
async def test_rejected_headers_do_not_consume_body(headers, status):
    async def receive():
        pytest.fail("A rejected request must not consume body bytes")
    req = Request({"type": "http", "method": "POST", "path": "/", "headers": headers}, receive)
    with pytest.raises(CaptureError) as error:
        await schema.read_json(req)
    assert error.value.status_code == status


@pytest.mark.anyio
async def test_body_deadline_produces_safe_timeout(monkeypatch):
    @asynccontextmanager
    async def expired(seconds):
        assert seconds == 5
        raise TimeoutError("private-network-message")
        yield
    monkeypatch.setattr(schema.asyncio, "timeout", expired)
    with pytest.raises(CaptureError) as error:
        await schema.read_json(request([]))
    assert error.value.code == "body_timeout"
    assert "private-network-message" not in str(error.value.detail)
