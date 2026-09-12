"""Small synchronous sender for an application's background telemetry job.

No imports of Guardian/server/provider packages. No network or environment reads
at import time. Network/configuration failures return a fixed diagnostic.
"""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import math
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def target(origin, allow_local=False):
    parsed = urlsplit(origin)
    if parsed.port == 0:
        raise ValueError()
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or any(c in origin for c in "\\?#") or any(c.isspace() for c in origin)):
        raise ValueError()
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (allow_local and local and parsed.scheme == "http"):
        raise ValueError()
    return origin.rstrip("/") + "/api/guardian/ingest/events"


def _valid_receipt(receipt, batch_id, test_mode, event_count):
    fields = {"batch_id", "test_mode", "processing", "received", "duplicate", "conflict_candidates", "replayed"}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or receipt["batch_id"] != batch_id or receipt["test_mode"] is not test_mode
            or receipt["processing"] != ("test_only" if test_mode else "queued")
            or type(receipt["replayed"]) is not bool):
        return False
    if any(type(receipt[name]) is not int or receipt[name] < 0
           for name in ("received", "duplicate", "conflict_candidates")):
        return False
    if receipt["received"] + receipt["duplicate"] != event_count or receipt["conflict_candidates"] > receipt["received"]:
        return False
    return not test_mode or (receipt["received"] == event_count and receipt["duplicate"] == receipt["conflict_candidates"] == 0)


def _retry_after(hint):
    if type(hint) is not str or not hint or len(hint) > 128:
        return None
    if hint.isascii() and hint.isdecimal() and len(hint) <= 6:
        return min(3600, max(1, int(hint)))
    try:
        stamp = parsedate_to_datetime(hint)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return min(3600, max(1, math.ceil((stamp.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())))
    except (ValueError, TypeError, OverflowError):
        return None


def send_batch(batch, *, origin=None, token=None, allow_local=False, max_attempts=3,
               should_stop=None, include_http_status=False):
    """Retry transport/transient failures using the same batch ID and bytes.

    Call from a background job, not the synchronous model request. A 202 means
    durable receipt; inspect Guardian separately for processing/incident results.
    """
    try:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3 or type(include_http_status) is not bool:
            raise ValueError()
        if should_stop is not None and not callable(should_stop):
            raise ValueError()

        def result(code, *, ok=False, status=None, retry_after=None):
            value = {"ok": ok, "code": code}
            if retry_after is not None:
                value["retry_after_seconds"] = retry_after
            if include_http_status and status is not None:
                value["http_status"] = status
            return value

        url = target(origin or os.getenv("GUARDIAN_URL", ""), allow_local)
        secret = token or os.getenv("GUARDIAN_INGEST_KEY", "")
        if not secret.startswith("cg_ingest_") or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise ValueError()
        if (not isinstance(batch, dict) or not isinstance(batch.get("batch_id"), str)
                or type(batch.get("test_mode")) is not bool or not isinstance(batch.get("events"), list)
                or not 1 <= len(batch["events"]) <= 100):
            raise ValueError()
        batch_id, test_mode, event_count = batch["batch_id"], batch["test_mode"], len(batch["events"])
        raw = json.dumps(batch, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > 262144:
            raise ValueError()
        opener = build_opener(ProxyHandler({}), NoRedirect())
        last_status = None
        for attempt in range(max_attempts):
            if should_stop is not None and should_stop():
                return result("cancelled")
            retry = False
            try:
                request = Request(url, data=raw, method="POST", headers={
                    "Content-Type": "application/json", "X-Guardian-Ingest-Key": secret})
                with opener.open(request, timeout=5) as response:
                    deadline = time.monotonic() + 5
                    chunks, length = [], 0
                    while length <= 16384:
                        if should_stop is not None and should_stop():
                            return result("cancelled")
                        if time.monotonic() >= deadline:
                            raise OSError()
                        chunk = response.read1(min(4096, 16385 - length))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        length += len(chunk)
                    body = b"".join(chunks)
                    if response.status != 202 or len(body) > 16384:
                        return result("receipt_unconfirmed", status=response.status)
                    receipt = json.loads(body)
                    if not _valid_receipt(receipt, batch_id, test_mode, event_count):
                        return result("receipt_unconfirmed", status=response.status)
                    return result("test_received" if test_mode else "received", ok=True, status=202)
            except HTTPError as error:
                last_status = error.code
                hint = error.headers.get("Retry-After", "")
                delay = _retry_after(hint)
                if error.code == 429 or (error.code in {500, 502, 503, 504} and delay is not None):
                    code = "rate_limited" if error.code == 429 else "temporarily_unavailable"
                    error.close()
                    return result(code, status=last_status, retry_after=delay or 60)
                retry = error.code in {429, 500, 502, 503, 504}
                error.close()
                if not retry:
                    return result("rejected", status=last_status)
            except (OSError, ValueError):
                retry = True
            if retry and attempt < max_attempts - 1:
                if should_stop is not None and should_stop():
                    return result("cancelled")
                time.sleep(0.1 * (attempt + 1))
        return result("receipt_unconfirmed", status=last_status)
    except Exception:
        return {"ok": False, "code": "invalid_configuration_or_batch"}


def test_batch():
    now = datetime.now(timezone.utc).isoformat()
    return {"schema_version": 1, "batch_id": str(uuid4()), "test_mode": True, "events": [{
        "observation_id": uuid4().hex, "trace_id": uuid4().hex, "agent_name": "capture-test", "model": "test-model",
        "started_at": now, "ended_at": now, "status": "unknown", "cost_usd": None}]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send a labelled capture handshake, never production sample traffic.")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--allow-local-http", action="store_true")
    args = parser.parse_args()
    if not args.send_test:
        parser.print_help()
    else:
        result = send_batch(test_batch(), allow_local=args.allow_local_http)
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
