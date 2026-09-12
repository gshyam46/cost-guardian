"""Independent lifecycle/concurrency and localhost wire checks; no services needed."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import gc
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import weakref

from test_native_recipes import receiver, receipt, TOKEN, SYSTEM_KEYS


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "native-capture"
sys.path.insert(0, str(EXAMPLES))
export = importlib.import_module("guardian_exporter")
app = importlib.import_module("python_app")
manual = importlib.import_module("guardian_capture")


def event(index=0, **changes):
    now = datetime.now(timezone.utc)
    return {"observation_id": f"call-{index}", "trace_id": "synthetic-run", "agent_name": "synthetic-agent",
            "model": "synthetic/model", "started_at": (now - timedelta(seconds=1)).isoformat(),
            "ended_at": now.isoformat(), "status": "success", "cost_usd": "0.0100",
            "input_tokens": 2, "output_tokens": 3, "total_tokens": 5, **changes}


class BlockedSender:
    def __init__(self, outcome=None):
        self.entered, self.release, self.returned = threading.Event(), threading.Event(), threading.Event()
        self.calls = []
        self.outcome = outcome or {"ok": True, "code": "received"}

    def __call__(self, body, **options):
        self.calls.append((json.dumps(body, separators=(",", ":")), options, threading.get_ident()))
        self.entered.set()
        if not self.release.wait(5):
            raise AssertionError("test did not release sender")
        self.returned.set()
        return self.outcome


class PythonExporter(unittest.TestCase):
    def make(self, **options):
        test_retry_base = options.pop("retry_base", 1)
        value = export.BackgroundExporter(origin="https://guardian.invalid", token=TOKEN, **options)
        value._retry_base = test_retry_base
        self.addCleanup(value.close, 0)
        return value

    def assert_counts(self, value):
        counts = value.snapshot()
        self.assertEqual(counts["enqueued_events"], counts["confirmed_events"] + counts["unconfirmed_events"] + counts["pending_events"])
        self.assertEqual(counts["pending_events"], counts["queued_events"] + counts["in_flight_events"])
        for name, number in counts.items():
            if name.endswith("_events") or name in ("pending_bytes", "export_attempts"):
                self.assertGreaterEqual(number, 0)
        self.assertNotIn(TOKEN, json.dumps(counts))
        return counts

    def wait_idle_transport(self, value):
        with value._condition:
            self.assertTrue(value._condition.wait_for(lambda: not value._transport_active, 2))

    def test_import_and_no_arguments_are_offline(self):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        interpreter = getattr(sys, "_base_executable", sys.executable)
        program = (
            "import sys,socket,threading,os; from unittest.mock import patch; "
            f"sys.path.insert(0,{str(EXAMPLES)!r}); "
            "fail=lambda *a,**k: (_ for _ in ()).throw(AssertionError('unexpected setup')); "
            "exec('with patch.object(threading.Thread,\"start\",fail), patch.object(socket.socket,\"connect\",fail), patch.object(os,\"getenv\",fail):\\n import guardian_exporter,python_app')"
        )
        result = subprocess.run([interpreter, "-I", "-S", "-c", program], capture_output=True, text=True, timeout=20, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        help_result = subprocess.run([interpreter, "-S", str(EXAMPLES / "python_app.py")],
                                     capture_output=True, text=True, timeout=20, env=environment)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--send-test", help_result.stdout)
        self.assertNotIn(TOKEN, help_result.stdout + help_result.stderr)

    def test_constructor_is_local_and_limits_cannot_increase(self):
        invalid = [dict(max_events=1001), dict(max_events=True), dict(max_bytes=4194305), dict(batch_size=101),
                   dict(batch_bytes=262145), dict(batch_bytes=1), dict(flush_interval=1.01), dict(max_attempts=6),
                   dict(max_age=301), dict(retry_base=1.01), dict(retry_base=0), dict(retry_base=0.5), dict(max_age=float("nan")), dict(test_mode=1),
                   dict(token="canary-invalid-key"), dict(origin="https://guardian.invalid:bad")]
        with patch.object(export, "send_batch", side_effect=AssertionError("constructor network")):
            for values in invalid:
                with self.subTest(values=values), self.assertRaises(export.ExporterConfigurationError) as caught:
                    export.BackgroundExporter(**{"origin": "https://guardian.invalid", "token": TOKEN, **values})
                self.assertEqual(str(caught.exception), "invalid_configuration")
            value = self.make()
            self.assertTrue(value.close()["confirmed"])

    def test_unknown_content_is_rejected_before_hooks_or_retention(self):
        class Canary:
            def __str__(self):
                raise AssertionError("inspected content")

            def __deepcopy__(self, memo):
                raise AssertionError("copied content")

        value = self.make()
        content = Canary()
        reference = weakref.ref(content)
        row = event(prompt=content)
        self.assertEqual(value.emit(row), {"accepted": False, "code": "invalid_event"})
        del row, content
        gc.collect()
        self.assertIsNone(reference())
        counts = self.assert_counts(value)
        self.assertEqual((counts["rejected_events"], counts["pending_events"], counts["pending_bytes"]), (1, 0, 0))

    def test_strict_numeric_identity_and_original_timestamp_validation(self):
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
        invalid = [dict(observation_id="private value"), dict(model={"content": "canary"}), dict(status=True),
                   dict(cost_usd=0.01), dict(cost_usd="NaN"), dict(cost_usd="1000000000"), dict(cost_usd="0.0000000000001"),
                   dict(input_tokens=True), dict(total_tokens=6), dict(output_tokens=2**53),
                   dict(started_at=stamp + ".123900Z", ended_at=stamp + ".123100Z"),
                   dict(started_at=stamp + ".1234567Z"), dict(started_at=stamp + "+00:99"),
                   dict(started_at="2026-02-30T00:00:00Z"), dict(started_at=stamp.replace("T", " ") + "Z"),
                   dict(started_at=(now - timedelta(days=1, seconds=1)).isoformat()),
                   dict(ended_at=(now + timedelta(minutes=6)).isoformat()), dict(started_at=stamp)]
        value = self.make()
        for changes in invalid:
            with self.subTest(fields=list(changes)):
                self.assertEqual(value.emit(event(**changes))["code"], "invalid_event")
        self.assertEqual(self.assert_counts(value)["rejected_events"], len(invalid))

    def test_emit_never_waits_for_transport_and_counts_inflight_capacity(self):
        sender = BlockedSender()
        self.addCleanup(sender.release.set)
        with patch.object(export, "send_batch", sender):
            value = self.make(max_events=2, batch_size=1)
            self.assertTrue(value.emit(event(1))["accepted"])
            self.assertTrue(sender.entered.wait(2))
            self.assertTrue(value.emit(event(2))["accepted"])
            self.assertEqual(value.emit(event(3))["code"], "queue_full")
            counts = self.assert_counts(value)
            self.assertEqual((counts["pending_events"], counts["queued_events"], counts["in_flight_events"]), (2, 1, 1))
            self.assertTrue(counts["transport_active"])
            self.assertNotEqual(sender.calls[0][2], threading.get_ident())
            self.assertEqual(sender.calls[0][1]["max_attempts"], 1)
            sender.release.set()
            self.assertTrue(value.flush()["confirmed"])
            self.assertEqual(self.assert_counts(value)["confirmed_events"], 2)

    def test_pending_byte_limit_includes_attempted_work(self):
        sender = BlockedSender()
        self.addCleanup(sender.release.set)
        row = event()
        size = len(json.dumps(row, separators=(",", ":")).encode())
        with patch.object(export, "send_batch", sender):
            value = self.make(max_bytes=size, batch_size=1)
            self.assertTrue(value.emit(row)["accepted"])
            self.assertTrue(sender.entered.wait(2))
            self.assertEqual(value.snapshot()["pending_bytes"], size)
            self.assertEqual(value.emit(row)["code"], "queue_full")
            sender.release.set()
            self.assertTrue(value.flush()["confirmed"])
            self.assertEqual(value.snapshot()["pending_bytes"], 0)

    def test_wire_retries_retain_exact_body_after_caller_mutation(self):
        first = threading.Event()
        raw_bodies = []
        actual = export.send_batch

        def observed(body, **options):
            raw_bodies.append(json.dumps(body, separators=(",", ":")))
            first.set()
            return actual(body, **options)

        with receiver([(500, {}, b"private-server-error"), (202, {}, None)]) as (origin, calls):
            with patch.object(export, "send_batch", observed):
                value = export.BackgroundExporter(origin=origin, token=TOKEN, allow_local=True, batch_size=1)
                value._retry_base = 0.05
                self.addCleanup(value.close, 0)
                row = event()
                self.assertTrue(value.emit(row)["accepted"])
                self.assertTrue(first.wait(2))
                row["cost_usd"], row["observation_id"] = "99", "changed-after-admission"
                row["prompt"] = object()
                self.assertTrue(value.flush()["confirmed"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["body"], calls[1]["body"])
                self.assertEqual(raw_bodies[0], raw_bodies[1])
                body = json.loads(calls[0]["body"])
                self.assertEqual(body["events"][0]["cost_usd"], "0.0100")
                self.assertNotIn("prompt", body["events"][0])
                self.assertEqual(self.assert_counts(value)["export_attempts"], 2)

    def test_fifo_batch_count_and_envelope_byte_bounds(self):
        bodies = []

        def received(body, **options):
            bodies.append(json.loads(json.dumps(body)))
            return {"ok": True, "code": "received"}

        with patch.object(export, "send_batch", received):
            value = self.make(batch_size=2, batch_bytes=1000)
            for index in range(7):
                self.assertTrue(value.emit(event(index))["accepted"])
            self.assertTrue(value.flush()["confirmed"])
        self.assertEqual([row["observation_id"] for body in bodies for row in body["events"]], [f"call-{index}" for index in range(7)])
        self.assertTrue(all(len(body["events"]) <= 2 and len(json.dumps(body, separators=(",", ":")).encode()) <= 1000 for body in bodies))
        self.assertEqual(len({body["batch_id"] for body in bodies}), len(bodies))
        self.assert_counts(value)

    def test_test_mode_is_instance_fixed_and_unknown_metrics_stay_unknown(self):
        with receiver([(202, {}, None)]) as (origin, calls):
            value = export.BackgroundExporter(origin=origin, token=TOKEN, allow_local=True, test_mode=True)
            self.addCleanup(value.close, 0)
            handle = value.start_call(agent_name="synthetic", model="synthetic/model")
            self.assertTrue(handle.finish("unknown")["accepted"])
            self.assertTrue(value.close()["confirmed"])
            body = json.loads(calls[0]["body"])
            self.assertIs(body["test_mode"], True)
            self.assertTrue({"cost_usd", "input_tokens", "output_tokens", "total_tokens"}.isdisjoint(body["events"][0]))

    def test_retry_after_floor_survives_flush_and_close_wakes(self):
        attempts = []
        first = threading.Event()

        def received(body, **options):
            attempts.append(time.monotonic())
            first.set()
            return {"ok": True, "code": "received"} if len(attempts) > 1 else {"ok": False, "code": "rate_limited", "retry_after_seconds": 0.15}

        with patch.object(export, "send_batch", received):
            value = self.make(batch_size=1, retry_base=0.01)
            value.emit(event())
            self.assertTrue(first.wait(2))
            self.assertFalse(value.flush(0.02)["drained"])
            self.assertTrue(value.close(1)["confirmed"])
            self.assertGreaterEqual(attempts[1] - attempts[0], 0.14)
            self.assertEqual(len(attempts), 2)

    def test_retry_cap_has_no_nested_transport_attempts(self):
        calls = []

        def unavailable(body, **options):
            calls.append(options["max_attempts"])
            return {"ok": False, "code": "receipt_unconfirmed"}

        with patch.object(export, "send_batch", unavailable):
            value = self.make(batch_size=1, retry_base=0)
            value.emit(event())
            result = value.flush()
            self.assertTrue(result["drained"])
            self.assertFalse(result["confirmed"])
            self.assertEqual(calls, [1] * 5)
            self.assertEqual(self.assert_counts(value)["last_error_code"], "retry_exhausted")

    def test_retry_beyond_age_budget_is_unconfirmed_without_waiting(self):
        with patch.object(export, "send_batch", return_value={"ok": False, "code": "temporarily_unavailable", "retry_after_seconds": 60}) as sender:
            value = self.make(batch_size=1, max_age=0.1)
            value.emit(event())
            self.assertFalse(value.flush(1)["confirmed"])
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(self.assert_counts(value)["last_error_code"], "batch_expired")

    def test_original_event_age_is_rechecked_before_retry(self):
        now = datetime.now(timezone.utc)
        current = [now]

        def unavailable(body, **options):
            current[0] = now + timedelta(days=1, seconds=2)
            return {"ok": False, "code": "receipt_unconfirmed"}

        with patch.object(export, "_utcnow", side_effect=lambda: current[0]), patch.object(export, "send_batch", side_effect=unavailable) as sender:
            value = self.make(batch_size=1, retry_base=0)
            value.emit(event())
            self.assertTrue(value.flush()["drained"])
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(self.assert_counts(value)["last_error_code"], "event_expired")

    def test_unattempted_expired_neighbors_do_not_discard_fresh_fifo_events(self):
        now = datetime.now(timezone.utc)
        current = [now]
        entered, release = threading.Event(), threading.Event()
        sent = []

        def received(body, **options):
            sent.extend(row["observation_id"] for row in body["events"])
            if not entered.is_set():
                entered.set()
                release.wait(3)
            return {"ok": True, "code": "received"}

        with patch.object(export, "_utcnow", side_effect=lambda: current[0]), patch.object(export, "send_batch", received):
            value = self.make(flush_interval=0)
            try:
                value.emit(event(1))
                self.assertTrue(entered.wait(2))
                old_start = (now - timedelta(days=1) + timedelta(milliseconds=100)).isoformat()
                self.assertTrue(value.emit(event(2, started_at=old_start))["accepted"])
                self.assertTrue(value.emit(event(3))["accepted"])
                self.assertTrue(value.emit(event(4, started_at=old_start))["accepted"])
                self.assertTrue(value.emit(event(5))["accepted"])
                current[0] = now + timedelta(milliseconds=200)
                release.set()
                result = value.flush()
                self.assertTrue(result["drained"])
                self.assertFalse(result["confirmed"])
                self.assertEqual(sent, ["call-1", "call-3", "call-5"])
                counts = self.assert_counts(value)
                self.assertEqual((counts["confirmed_events"], counts["unconfirmed_events"]), (3, 2))
            finally:
                release.set()

    def test_permanent_rejection_only_terminates_that_batch(self):
        with receiver([(400, {}, b"private-response"), (202, {}, None)]) as (origin, calls):
            value = export.BackgroundExporter(origin=origin, token=TOKEN, allow_local=True, batch_size=1)
            self.addCleanup(value.close, 0)
            value.emit(event(1))
            self.assertFalse(value.flush()["confirmed"])
            self.assertTrue(value.emit(event(2))["accepted"])
            result = value.flush()
            self.assertTrue(result["drained"])
            self.assertFalse(result["confirmed"])
            self.assertEqual(len(calls), 2)
            counts = self.assert_counts(value)
            self.assertEqual((counts["confirmed_events"], counts["unconfirmed_events"]), (1, 1))

    def test_expiry_during_unattempted_batch_construction_preserves_fresh_neighbor(self):
        now = datetime.now(timezone.utc)
        current, sent = [now], []

        def received(body, **options):
            sent.extend(row["observation_id"] for row in body["events"])
            return {"ok": True, "code": "received"}

        with patch.object(export, "_utcnow", side_effect=lambda: current[0]), patch.object(export, "send_batch", received):
            value = self.make()
            original = value._envelope

            def elapsed_during_construction(events, batch_id):
                current[0] = now + timedelta(milliseconds=200)
                return original(events, batch_id)

            value._envelope = elapsed_during_construction
            value.emit(event(1, started_at=(now - timedelta(days=1) + timedelta(milliseconds=100)).isoformat()))
            value.emit(event(2))
            result = value.flush()
            self.assertTrue(result["drained"])
            self.assertFalse(result["confirmed"])
            self.assertEqual(sent, ["call-2"])
            self.assertEqual(result["stats"]["export_attempts"], 1)
            self.assert_counts(value)

    def test_auth_rejection_stops_instance_and_remaining_queue(self):
        for status in (401, 403):
            sender = BlockedSender({"ok": False, "code": "rejected", "http_status": status})
            with self.subTest(status=status), patch.object(export, "send_batch", sender):
                value = self.make(batch_size=1)
                try:
                    value.emit(event(1))
                    self.assertTrue(sender.entered.wait(2))
                    value.emit(event(2))
                    sender.release.set()
                    self.assertFalse(value.flush()["confirmed"])
                    self.assertEqual(value.emit(event(3))["code"], "exporter_unavailable")
                    self.assertEqual(len(sender.calls), 1)
                    counts = self.assert_counts(value)
                    self.assertEqual((counts["pending_events"], counts["unconfirmed_events"]), (0, 2))
                    self.assertEqual(counts["last_error_code"], "credential_rejected")
                finally:
                    sender.release.set()

    def test_prefix_flush_ignores_later_blocked_producer(self):
        entered = [threading.Event(), threading.Event()]
        releases = [threading.Event(), threading.Event()]
        calls = []

        def controlled(body, **options):
            index = len(calls)
            calls.append(body)
            entered[index].set()
            releases[index].wait(5)
            return {"ok": True, "code": "received"}

        with patch.object(export, "send_batch", controlled):
            value = self.make(batch_size=1)
            flushed, done = [], threading.Event()
            value.emit(event(1))
            self.assertTrue(entered[0].wait(2))
            waiter = threading.Thread(target=lambda: (flushed.append(value.flush(2)), done.set()), daemon=True)
            waiter.start()
            try:
                with value._condition:
                    self.assertTrue(value._condition.wait_for(lambda: value._flush_through == 1, 1))
                value.emit(event(2))
                releases[0].set()
                self.assertTrue(entered[1].wait(2))
                self.assertTrue(done.wait(1))
                self.assertTrue(flushed[0]["confirmed"])
                self.assertEqual(value.snapshot()["pending_events"], 1)
            finally:
                for release in releases:
                    release.set()
                waiter.join(2)
                value.close(2)

    def test_timed_out_flush_keeps_work_but_close_fences_late_ack(self):
        sender = BlockedSender()
        self.addCleanup(sender.release.set)
        with patch.object(export, "send_batch", sender):
            value = self.make(batch_size=1)
            value.emit(event(1))
            self.assertTrue(sender.entered.wait(2))
            self.assertFalse(value.flush(0)["drained"])
            self.assertEqual(value.snapshot()["pending_events"], 1)
            result = value.close(0)
            self.assertTrue(result["drained"])
            self.assertFalse(result["confirmed"])
            self.assertTrue(result["stats"]["transport_active"])
            self.assertEqual(value.emit(event(2))["code"], "closed")
            sender.release.set()
            self.wait_idle_transport(value)
            counts = self.assert_counts(value)
            self.assertEqual((counts["confirmed_events"], counts["unconfirmed_events"], counts["export_attempts"]), (0, 1, 1))
            self.assertFalse(value.close()["confirmed"])
            self.assertTrue(sender.calls[0][1]["should_stop"]())

    def test_call_handle_is_once_even_if_queue_rejects_it(self):
        with patch.object(export, "send_batch", return_value={"ok": True, "code": "received"}):
            value = self.make(max_events=1)
            first = value.start_call(agent_name="synthetic", model="synthetic/model", trace_id="shared-run")
            second = value.start_call(agent_name="synthetic", model="synthetic/model", trace_id=first.trace_id,
                                      parent_observation_id=first.observation_id)
            self.assertNotEqual(first.observation_id, second.observation_id)
            self.assertTrue(first.finish("success")["accepted"])
            self.assertEqual(first.finish("error")["code"], "already_finished")
            self.assertEqual(second.finish("success")["code"], "queue_full")
            self.assertEqual(second.finish("success")["code"], "already_finished")
            self.assertTrue(value.flush()["confirmed"])
            self.assertEqual(value.snapshot()["enqueued_events"], 1)

    def test_invalid_handle_metadata_and_measurements_are_inert(self):
        value = self.make()
        handle = value.start_call(agent_name="contains private spaces", model="synthetic/model")
        self.assertIsNone(handle.observation_id)
        handle.finish("success", input_tokens=2)
        self.assertEqual(value.snapshot()["rejected_events"], 1)
        valid = value.start_call(agent_name="synthetic", model="synthetic/model")
        self.assertEqual(valid.finish("success", raw_response=object())["code"], "invalid_event")
        self.assertEqual(valid.finish("success")["code"], "already_finished")
        self.assertEqual(value.snapshot()["enqueued_events"], 0)

    def test_lifecycle_helpers_preserve_results_errors_and_early_stream_status(self):
        bodies = []

        def received(body, **options):
            bodies.extend(body["events"])
            return {"ok": True, "code": "received"}

        with patch.object(export, "send_batch", received):
            value = self.make()
            result = object()
            self.assertIs(app.run_call(value, lambda: result, agent_name="normal", model="synthetic/model"), result)
            items = [object(), object()]
            self.assertEqual(list(app.stream_call(value, lambda: iter(items), agent_name="stream", model="synthetic/model")), items)
            early = app.stream_call(value, lambda: iter(items), agent_name="early", model="synthetic/model")
            self.assertIs(next(early), items[0])
            early.close()
            failure = RuntimeError("private-provider-error")

            def bad():
                raise failure

            with self.assertRaises(RuntimeError) as caught:
                app.run_call(value, bad, agent_name="failure", model="synthetic/model")
            self.assertIs(caught.exception, failure)

            def bad_stream():
                yield items[0]
                raise failure

            with self.assertRaises(RuntimeError) as caught:
                list(app.stream_call(value, bad_stream, agent_name="stream-failure", model="synthetic/model"))
            self.assertIs(caught.exception, failure)
            self.assertTrue(value.close()["confirmed"])
        self.assertEqual([row["status"] for row in bodies], ["success", "success", "unknown", "error", "error"])
        self.assertNotIn("private-provider-error", json.dumps(bodies))
        self.assertEqual(len({row["observation_id"] for row in bodies}), 5)

    def test_cancellation_preserves_base_exception_and_marks_unknown(self):
        class Cancelled(BaseException):
            pass

        cancellation = Cancelled()
        bodies = []

        def stopped():
            raise cancellation

        with patch.object(export, "send_batch", side_effect=lambda body, **kwargs: (bodies.extend(body["events"]), {"ok": True})[1]):
            value = self.make()
            with self.assertRaises(Cancelled) as caught:
                app.run_call(value, stopped, agent_name="cancelled", model="synthetic/model")
            self.assertIs(caught.exception, cancellation)
            self.assertTrue(value.close()["confirmed"])
        self.assertEqual(bodies[0]["status"], "unknown")

    def test_sync_stream_preserves_generator_return_value(self):
        value = self.make()
        chunk, returned = object(), object()

        def provider():
            yield chunk
            return returned

        with patch.object(export, "send_batch", return_value={"ok": True, "code": "received"}):
            wrapped = app.stream_call(value, provider, agent_name="stream", model="synthetic/model")
            self.assertIs(next(wrapped), chunk)
            with self.assertRaises(StopIteration) as stopped:
                next(wrapped)
            self.assertIs(stopped.exception.value, returned)
            self.assertTrue(value.close()["confirmed"])

    def test_async_helpers_preserve_results_exception_identity_and_exhaustion(self):
        captured = []

        async def exercise():
            value = self.make()
            result, first, last = object(), object(), object()

            async def normal():
                return result

            self.assertIs(await app.async_run_call(value, normal, agent_name="async-normal", model="synthetic/model"), result)
            reads = []

            async def stream():
                reads.append(1)
                yield first
                reads.append(2)
                yield last

            wrapped = app.async_stream_call(value, stream, agent_name="async-stream", model="synthetic/model")
            self.assertEqual(reads, [])
            self.assertIs(await anext(wrapped), first)
            self.assertEqual(reads, [1])
            self.assertIs(await anext(wrapped), last)
            with self.assertRaises(StopAsyncIteration):
                await anext(wrapped)
            failure = RuntimeError("private-async-error")

            async def fails():
                raise failure

            with self.assertRaises(RuntimeError) as caught:
                await app.async_run_call(value, fails, agent_name="async-error", model="synthetic/model")
            self.assertIs(caught.exception, failure)

            async def bad_stream():
                yield first
                raise failure

            with self.assertRaises(RuntimeError) as caught:
                async for _ in app.async_stream_call(value, bad_stream, agent_name="async-stream-error", model="synthetic/model"):
                    pass
            self.assertIs(caught.exception, failure)
            self.assertTrue(value.close()["confirmed"])

        with patch.object(export, "send_batch", side_effect=lambda body, **kwargs: (captured.extend(body["events"]), {"ok": True})[1]):
            asyncio.run(exercise())
        self.assertEqual([row["status"] for row in captured], ["success", "success", "error", "error"])
        self.assertNotIn("private-async-error", json.dumps(captured))

    def test_async_early_close_and_cancellation_are_unknown_with_provider_cleanup(self):
        captured = []

        async def exercise():
            value = self.make()
            closed = []

            async def stream():
                try:
                    yield object()
                    yield object()
                finally:
                    closed.append(True)

            wrapped = app.async_stream_call(value, stream, agent_name="async-early", model="synthetic/model")
            await anext(wrapped)
            await wrapped.aclose()
            self.assertEqual(closed, [True])
            cancelled = asyncio.CancelledError("private-cancellation")

            async def cancellation():
                raise cancelled

            with self.assertRaises(asyncio.CancelledError) as caught:
                await app.async_run_call(value, cancellation, agent_name="async-cancelled", model="synthetic/model")
            self.assertIs(caught.exception, cancelled)
            started, cleaned = asyncio.Event(), asyncio.Event()

            async def waiting_stream():
                try:
                    started.set()
                    await asyncio.Event().wait()
                    yield object()
                finally:
                    cleaned.set()

            wrapped = app.async_stream_call(value, waiting_stream, agent_name="async-stream-cancelled", model="synthetic/model")
            pending = asyncio.create_task(anext(wrapped))
            await asyncio.wait_for(started.wait(), 1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(cleaned.is_set())
            self.assertTrue(value.close()["confirmed"])

        with patch.object(export, "send_batch", side_effect=lambda body, **kwargs: (captured.extend(body["events"]), {"ok": True})[1]):
            asyncio.run(exercise())
        self.assertEqual([row["status"] for row in captured], ["unknown", "unknown", "unknown"])
        self.assertNotIn("private-cancellation", json.dumps(captured))

    def test_fork_pid_change_does_not_restart_worker_or_reuse_parent_lock(self):
        value = self.make()
        original_condition = value._condition
        acquired, release, done = threading.Event(), threading.Event(), threading.Event()

        def hold():
            with original_condition:
                acquired.set()
                release.wait(3)
                original_condition.notify_all()

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        self.assertTrue(acquired.wait(1))
        result = []
        try:
            with patch.object(export.os, "getpid", return_value=value._pid + 1), patch.object(export.threading.Thread, "start", side_effect=AssertionError("restarted inherited worker")):
                result.append(value.emit(event()))
                done.set()
            self.assertTrue(done.is_set())
            self.assertEqual(result[0]["code"], "exporter_unavailable")
            self.assertFalse(value.snapshot()["transport_active"])
        finally:
            release.set()
            holder.join(2)

    def test_manual_single_attempt_status_and_cancellation_are_opt_in(self):
        batch = manual.test_batch()
        with receiver([(401, {}, b"private-error")]) as (origin, calls):
            result = manual.send_batch(batch, origin=origin, token=TOKEN, allow_local=True,
                                       max_attempts=1, include_http_status=True)
            self.assertEqual(result, {"ok": False, "code": "rejected", "http_status": 401})
            self.assertEqual(len(calls), 1)
            self.assertEqual(manual.send_batch(batch, origin=origin, token=TOKEN, allow_local=True,
                                              should_stop=lambda: True), {"ok": False, "code": "cancelled"})
            self.assertEqual(len(calls), 1)

    def test_http_date_retry_after_is_honored_and_does_not_leak_content(self):
        for status in (429, 500, 502, 503, 504):
            hint = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=10), usegmt=True)
            with self.subTest(status=status), receiver([(status, {"Retry-After": hint}, b"private-upstream-text")]) as (origin, calls):
                result = manual.send_batch(manual.test_batch(), origin=origin, token=TOKEN, allow_local=True,
                                           max_attempts=1, include_http_status=True)
                self.assertFalse(result["ok"])
                self.assertGreaterEqual(result["retry_after_seconds"], 590)
                self.assertLessEqual(result["retry_after_seconds"], 600)
                self.assertEqual(len(calls), 1)
                self.assertNotIn("private-upstream-text", json.dumps(result))
        for hint in ("private-not-a-date", "Sat, 12 Sep 2026 00:00:00", "x" * 129):
            with self.subTest(hint=hint), receiver([(429, {"Retry-After": hint}, b"private-upstream-text")]) as (origin, calls):
                result = manual.send_batch(manual.test_batch(), origin=origin, token=TOKEN, allow_local=True)
                self.assertEqual(result, {"ok": False, "code": "rate_limited", "retry_after_seconds": 60})
                self.assertEqual(len(calls), 1)

    def test_far_future_retry_after_expires_background_batch_without_retry(self):
        hint = format_datetime(datetime.now(timezone.utc) + timedelta(hours=2), usegmt=True)
        with receiver([(503, {"Retry-After": hint}, b"private-upstream-text")]) as (origin, calls):
            value = export.BackgroundExporter(origin=origin, token=TOKEN, allow_local=True, batch_size=1)
            self.addCleanup(value.close, 0)
            value.emit(event())
            result = value.flush(2)
            self.assertTrue(result["drained"])
            self.assertFalse(result["confirmed"])
            self.assertEqual(result["stats"]["last_error_code"], "batch_expired")
            self.assertEqual(len(calls), 1)

    def test_real_blocked_receipt_close_is_bounded_and_fences_late_transport(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                calls.append(raw)
                raw_receipt = json.dumps(receipt(json.loads(raw))).encode()
                self.send_response(202)
                self.send_header("Content-Length", str(len(raw_receipt)))
                self.end_headers()
                self.wfile.write(raw_receipt[:1])
                self.wfile.flush()
                entered.set()
                release.wait(3)
                try:
                    self.wfile.write(raw_receipt[1:])
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        value = export.BackgroundExporter(origin=f"http://127.0.0.1:{server.server_port}", token=TOKEN,
                                          allow_local=True, batch_size=1)
        try:
            self.assertTrue(value.emit(event())["accepted"])
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            result = value.close(0.02)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(result["stats"]["transport_active"])
            self.assertFalse(result["confirmed"])
            release.set()
            self.wait_idle_transport(value)
            counts = self.assert_counts(value)
            self.assertEqual((counts["confirmed_events"], counts["unconfirmed_events"]), (0, 1))
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            value.close(0)
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
