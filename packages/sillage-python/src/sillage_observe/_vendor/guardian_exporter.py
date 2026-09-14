"""Bounded, process-local export of numeric terminal-call events.

Import is inert. One explicit instance owns one daemon sender. Delivery is not
durable across process exit, and a timed-out close cannot interrupt urllib/DNS.
"""
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
import threading
import time
from uuid import uuid4

from .guardian_capture import send_batch, target


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
_COST = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?\Z")
_TOKEN = re.compile(r"cg_ingest_[0-9a-f]{32}_[A-Za-z0-9_-]{43}\Z")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")
_REQUIRED = frozenset({"observation_id", "trace_id", "agent_name", "model", "started_at", "ended_at", "status"})
_MEASUREMENTS = frozenset({"cost_usd", "input_tokens", "output_tokens", "total_tokens"})
_OPTIONAL = _MEASUREMENTS | {"parent_observation_id"}
_MAX_TOKENS = 2**53 - 1
_RETRY_CODES = frozenset({"receipt_unconfirmed", "rate_limited", "temporarily_unavailable"})


class ExporterConfigurationError(ValueError):
    def __init__(self):
        super().__init__("invalid_configuration")


def _utcnow():
    return datetime.now(timezone.utc)


def _number(value, maximum, *, integer=False, zero=False):
    if type(value) not in ((int,) if integer else (int, float)):
        raise ValueError()
    if not math.isfinite(value) or not (0 <= value <= maximum if zero else 0 < value <= maximum):
        raise ValueError()
    return value


def _technical(value, pattern):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError()
    return value


def _stamp(value):
    if type(value) is not str or len(value) > 40 or not _TIME.fullmatch(value):
        raise ValueError()
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError()
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError()
    return stamp.astimezone(timezone.utc)


def _event(event, now):
    # Inspect only flat field names before inspecting or copying their values.
    # Exact builtin types exclude arbitrary mapping/string/JSON hooks.
    if type(event) is not dict or len(event) > len(_REQUIRED) + len(_OPTIONAL) or any(type(key) is not str for key in event):
        raise ValueError()
    fields = set(event)
    if not _REQUIRED <= fields or fields - _REQUIRED - _OPTIONAL:
        raise ValueError()
    copied = {}
    for name in ("observation_id", "trace_id"):
        copied[name] = _technical(event[name], _ID)
    for name in ("agent_name", "model"):
        copied[name] = _technical(event[name], _LABEL)
    if "parent_observation_id" in event:
        value = event["parent_observation_id"]
        copied["parent_observation_id"] = None if value is None else _technical(value, _ID)
    if type(event["status"]) is not str or event["status"] not in ("success", "error", "unknown"):
        raise ValueError()
    start, end = _stamp(event["started_at"]), _stamp(event["ended_at"])
    if start < now - timedelta(hours=24) or end < start or max(start, end) > now + timedelta(minutes=5):
        raise ValueError()
    copied.update(started_at=event["started_at"], ended_at=event["ended_at"], status=event["status"])
    if "cost_usd" in event:
        cost = event["cost_usd"]
        copied["cost_usd"] = None if cost is None else _technical(cost, _COST)
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        if name in event:
            value = event[name]
            if value is not None and (type(value) is not int or not 0 <= value <= _MAX_TOKENS):
                raise ValueError()
            copied[name] = value
    inputs, outputs, total = (copied.get(name) for name in ("input_tokens", "output_tokens", "total_tokens"))
    if inputs is not None and outputs is not None:
        derived = inputs + outputs
        if derived > _MAX_TOKENS or total is not None and total != derived:
            raise ValueError()
        copied["total_tokens"] = derived
    raw = json.dumps(copied, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return copied, len(raw), start


class BackgroundExporter:
    def __init__(self, *, origin=None, token=None, allow_local=False, test_mode=False,
                 max_events=1000, max_bytes=4194304, batch_size=100, batch_bytes=262144,
                 flush_interval=1.0, max_attempts=5, max_age=300.0, retry_base=1.0):
        try:
            origin = os.getenv("GUARDIAN_URL", "") if origin is None else origin
            token = os.getenv("GUARDIAN_INGEST_KEY", "") if token is None else token
            if type(origin) is not str or type(allow_local) is not bool or type(test_mode) is not bool:
                raise ValueError()
            target(origin, allow_local)
            _technical(token, _TOKEN)
            self._max_events = _number(max_events, 1000, integer=True)
            self._max_bytes = _number(max_bytes, 4194304, integer=True)
            self._batch_size = _number(batch_size, 100, integer=True)
            self._batch_bytes = _number(batch_bytes, 262144, integer=True)
            self._interval = _number(flush_interval, 1, zero=True)
            self._max_attempts = _number(max_attempts, 5, integer=True)
            self._max_age = _number(max_age, 300)
            self._retry_base = _number(retry_base, 1)
            if self._retry_base != 1:
                raise ValueError()
            self._origin, self._token = origin, token
            self._allow_local, self._test_mode = allow_local, test_mode
            self._envelope_bytes = len(json.dumps(self._envelope([], "0" * 36), separators=(",", ":")).encode())
            if self._batch_bytes <= self._envelope_bytes:
                raise ValueError()
        except Exception:
            raise ExporterConfigurationError() from None
        self._pid = os.getpid()
        self._condition = threading.Condition()
        self._queue = deque()
        self._active = None
        self._enqueued = self._confirmed = self._unconfirmed = self._rejected = 0
        self._pending_bytes = self._attempts = self._completed = 0
        self._first_unconfirmed = None
        self._flush_through = 0
        self._closed = self._stopped = self._unavailable = self._transport_active = False
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name="guardian-export", daemon=True)
        try:
            self._thread.start()
        except Exception:
            raise ExporterConfigurationError() from None

    def _envelope(self, events, batch_id):
        return {"schema_version": 1, "batch_id": batch_id, "test_mode": self._test_mode, "events": events}

    def _process(self):
        if os.getpid() != self._pid:
            # Never acquire a possibly locked mutex inherited from the parent.
            self._pid = os.getpid()
            self._condition = threading.Condition()
            self._transport_active = False
            self._unavailable = True
            self._fail_all("exporter_unavailable")

    def _snapshot(self):
        return {"enqueued_events": self._enqueued, "confirmed_events": self._confirmed,
                "unconfirmed_events": self._unconfirmed, "rejected_events": self._rejected,
                "pending_events": self._enqueued - self._completed, "queued_events": len(self._queue),
                "in_flight_events": len(self._active["entries"]) if self._active else 0,
                "pending_bytes": self._pending_bytes, "export_attempts": self._attempts,
                "closed": self._closed, "transport_active": self._transport_active,
                "last_error_code": self._last_error}

    def snapshot(self):
        self._process()
        with self._condition:
            return self._snapshot()

    def _reject(self, code):
        self._rejected += 1
        if self._last_error != "credential_rejected":
            self._last_error = code
        return {"accepted": False, "code": code}

    def _invalid(self):
        self._process()
        with self._condition:
            return self._reject("invalid_event")

    def emit(self, event):
        self._process()
        try:
            copied, size, start = _event(event, _utcnow())
        except Exception:
            return self._invalid()
        with self._condition:
            if self._closed:
                return self._reject("closed")
            if self._unavailable or self._stopped:
                return self._reject("exporter_unavailable")
            if size + self._envelope_bytes > self._batch_bytes:
                return self._reject("invalid_event")
            if self._enqueued - self._completed >= self._max_events or self._pending_bytes + size > self._max_bytes:
                return self._reject("queue_full")
            self._enqueued += 1
            self._pending_bytes += size
            self._queue.append((self._enqueued, copied, size, start, time.monotonic()))
            self._condition.notify_all()
            return {"accepted": True, "code": "queued"}

    def start_call(self, *, agent_name, model, trace_id=None, parent_observation_id=None):
        try:
            _technical(agent_name, _LABEL)
            _technical(model, _LABEL)
            trace_id = uuid4().hex if trace_id is None else _technical(trace_id, _ID)
            if parent_observation_id is not None:
                _technical(parent_observation_id, _ID)
            metadata = {"observation_id": uuid4().hex, "trace_id": trace_id, "agent_name": agent_name,
                        "model": model, "started_at": _utcnow().isoformat()}
            if parent_observation_id is not None:
                metadata["parent_observation_id"] = parent_observation_id
            return CallHandle(self, metadata)
        except Exception:
            self._invalid()
            return CallHandle(self, None)

    def _result(self, prefix, *, forced=False):
        drained = self._completed >= prefix
        confirmed = drained and not forced and (self._first_unconfirmed is None or self._first_unconfirmed > prefix)
        return {"drained": drained, "confirmed": confirmed, "stats": self._snapshot()}

    def _wait(self, prefix, deadline):
        self._flush_through = max(self._flush_through, prefix)
        self._condition.notify_all()
        while self._completed < prefix:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._condition.wait(remaining)

    def flush(self, timeout=5):
        self._process()
        try:
            _number(timeout, 300, zero=True)
        except Exception:
            timeout = 0
        with self._condition:
            prefix = self._enqueued
            self._wait(prefix, time.monotonic() + timeout)
            return self._result(prefix)

    def close(self, timeout=5):
        self._process()
        try:
            _number(timeout, 300, zero=True)
        except Exception:
            timeout = 0
        with self._condition:
            self._closed = True
            prefix = self._enqueued
            self._wait(prefix, time.monotonic() + timeout)
            forced = self._completed < prefix
            if forced:
                self._fail_all("close_timeout")
            self._condition.notify_all()
            return self._result(prefix, forced=forced)

    def _finish_batch(self, confirmed, code=None):
        entries = self._active["entries"]
        count = len(entries)
        if confirmed:
            self._confirmed += count
        else:
            self._unconfirmed += count
            if self._first_unconfirmed is None:
                self._first_unconfirmed = entries[0][0]
        self._completed = entries[-1][0]
        self._pending_bytes -= sum(entry[2] for entry in entries)
        self._active = None
        self._last_error = code
        self._condition.notify_all()

    def _fail_all(self, code):
        if self._completed < self._enqueued and self._first_unconfirmed is None:
            self._first_unconfirmed = self._completed + 1
        self._unconfirmed += self._enqueued - self._completed
        self._completed = self._enqueued
        self._pending_bytes = 0
        self._active = None
        self._queue.clear()
        self._stopped = True
        self._last_error = code

    def _cancelled(self):
        with self._condition:
            return self._stopped

    def _run(self):
        try:
            self._send_loop()
        except Exception:
            with self._condition:
                self._transport_active = False
                self._unavailable = True
                self._fail_all("exporter_unavailable")
                self._condition.notify_all()

    def _send_loop(self):
        while True:
            with self._condition:
                if self._stopped:
                    return
                if self._active is None:
                    while self._queue and self._queue[0][3] < _utcnow() - timedelta(hours=24):
                        expired = self._queue.popleft()
                        if self._first_unconfirmed is None:
                            self._first_unconfirmed = expired[0]
                        self._unconfirmed += 1
                        self._completed = expired[0]
                        self._pending_bytes -= expired[2]
                        self._last_error = "event_expired"
                        self._condition.notify_all()
                    if not self._queue:
                        if self._closed:
                            return
                        self._condition.wait()
                        continue
                    deadline = self._queue[0][4] + self._interval
                    if not self._closed and self._queue[0][0] > self._flush_through and len(self._queue) < self._batch_size:
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            self._condition.wait(remaining)
                            continue
                    entries, size = [], self._envelope_bytes
                    while self._queue and len(entries) < self._batch_size:
                        if self._queue[0][3] < _utcnow() - timedelta(hours=24):
                            break
                        next_size = self._queue[0][2] + (1 if entries else 0)
                        if size + next_size > self._batch_bytes:
                            break
                        entries.append(self._queue.popleft())
                        size += next_size
                    if not entries:
                        continue
                    self._active = {"entries": entries, "body": self._envelope([entry[1] for entry in entries], str(uuid4())),
                                    "created": time.monotonic(), "retry_at": 0, "attempts": 0}
                batch = self._active
                now = time.monotonic()
                if now - batch["created"] >= self._max_age:
                    self._finish_batch(False, "batch_expired")
                    continue
                if any(entry[3] < _utcnow() - timedelta(hours=24) for entry in batch["entries"]):
                    if batch["attempts"] == 0:
                        # No request has observed this UUID/body. Reclassify at
                        # the FIFO head if an event expired while forming it.
                        self._queue.extendleft(reversed(batch["entries"]))
                        self._active = None
                        continue
                    self._finish_batch(False, "event_expired")
                    continue
                remaining = batch["retry_at"] - now
                if remaining > 0:
                    self._condition.wait(min(remaining, batch["created"] + self._max_age - now))
                    continue
                batch["attempts"] += 1
                self._attempts += 1
                self._transport_active = True
            try:
                result = send_batch(batch["body"], origin=self._origin, token=self._token,
                                    allow_local=self._allow_local, max_attempts=1,
                                    should_stop=self._cancelled, include_http_status=True)
            except Exception:
                result = {"ok": False, "code": "receipt_unconfirmed"}
            with self._condition:
                self._transport_active = False
                self._condition.notify_all()
                if self._stopped or self._active is not batch:
                    continue
                if type(result) is not dict:
                    result = {"ok": False, "code": "receipt_unconfirmed"}
                if result.get("http_status") in (401, 403):
                    self._unavailable = True
                    self._fail_all("credential_rejected")
                    self._condition.notify_all()
                    continue
                if result.get("ok") is True:
                    self._finish_batch(True)
                    continue
                code = result.get("code")
                if code in ("rejected", "invalid_configuration_or_batch"):
                    self._finish_batch(False, code)
                    continue
                if batch["attempts"] >= self._max_attempts:
                    self._finish_batch(False, "retry_exhausted")
                    continue
                delay = self._retry_base * (2 ** (batch["attempts"] - 1))
                retry_after = result.get("retry_after_seconds")
                if type(retry_after) in (int, float) and math.isfinite(retry_after) and retry_after > 0:
                    delay = max(delay, retry_after)
                batch["retry_at"] = time.monotonic() + delay
                self._last_error = code if type(code) is str and code in _RETRY_CODES else "receipt_unconfirmed"
                if batch["retry_at"] >= batch["created"] + self._max_age:
                    self._finish_batch(False, "batch_expired")


class CallHandle:
    def __init__(self, exporter, metadata):
        self._exporter, self._metadata = exporter, metadata
        self._lock = threading.Lock()
        self._finished = metadata is None
        self._pid = os.getpid()
        self.observation_id = metadata["observation_id"] if metadata else None
        self.trace_id = metadata["trace_id"] if metadata else None

    def finish(self, status="unknown", **measurements):
        if os.getpid() != self._pid:
            self._pid = os.getpid()
            self._lock = threading.Lock()
        with self._lock:
            if self._finished:
                return {"accepted": False, "code": "already_finished"}
            self._finished = True
            try:
                if set(measurements) - _MEASUREMENTS:
                    return self._exporter._invalid()
                event = {**self._metadata, "ended_at": _utcnow().isoformat(), "status": status, **measurements}
                self._metadata = None
                return self._exporter.emit(event)
            except Exception:
                return self._exporter._invalid()
