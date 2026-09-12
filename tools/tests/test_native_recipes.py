"""Real localhost transport tests for the dependency-free terminal-event examples."""
from contextlib import contextmanager
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "examples/native-capture/guardian_capture.py"
NODE = ROOT / "examples/native-capture/guardian_capture.mjs"
spec = importlib.util.spec_from_file_location("capture_recipe", PYTHON)
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)
TOKEN = "cg_ingest_" + "a" * 32 + "_" + "b" * 43
# Keep the same operating-system allowlist as tools/harness.py. Windows needs
# SYSTEMDRIVE/COMSPEC and profile paths even for dependency-free subprocesses.
SYSTEM_KEYS = {
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "LANG", "LC_ALL", "LC_CTYPE",
}


def receipt(batch, **changes):
    return {"batch_id": batch["batch_id"], "test_mode": batch["test_mode"],
            "processing": "test_only" if batch["test_mode"] else "queued",
            "received": len(batch["events"]), "duplicate": 0, "conflict_candidates": 0,
            "replayed": False, **changes}


@contextmanager
def receiver(replies):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append({"headers": dict(self.headers), "body": raw, "path": self.path})
            code, headers, value = replies[min(len(calls) - 1, len(replies) - 1)]
            if value is None:
                batch = json.loads(raw)
                value = receipt(batch)
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, val in headers.items():
                self.send_header(key, val)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class NativeRecipes(unittest.TestCase):
    def invoke(self, language, origin, *, batch=None, arguments=True):
        if language == "python" and arguments:
            return recipe.send_batch(batch or recipe.test_batch(), origin=origin, token=TOKEN, allow_local=True)
        if language == "node" and not shutil.which("node"):
            self.skipTest("Node is not installed; Python transport tests still run")
        env = {key: value for key, value in os.environ.items()
               if key.upper() in SYSTEM_KEYS}
        env.update(GUARDIAN_URL=origin, GUARDIAN_INGEST_KEY=TOKEN)
        if language == "node" and batch is not None:
            program = (f"import {{sendBatch}} from {json.dumps(NODE.as_uri())};"
                       "let raw='';for await(const c of process.stdin)raw+=c;"
                       "console.log(JSON.stringify(await sendBatch(JSON.parse(raw),{allowLocal:true}))); ")
            command = ["node", "--input-type=module", "-e", program]
            payload = json.dumps(batch)
        else:
            command = [sys.executable, "-I", "-S", str(PYTHON)] if language == "python" else ["node", str(NODE)]
            if arguments:
                command += ["--send-test", "--allow-local-http"]
            payload = None
        result = subprocess.run(command, input=payload, text=True, capture_output=True, env=env, timeout=20)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertNotIn("server-content-canary", result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout) if arguments else result.stdout

    def test_python_success_uses_only_machine_authority(self):
        self._success("python")

    def test_node_success_uses_only_machine_authority(self):
        self._success("node")

    def _success(self, language):
        with receiver([(202, {}, None)]) as (origin, calls):
            self.assertEqual(self.invoke(language, origin), {"ok": True, "code": "test_received"})
            self.assertEqual(len(calls), 1)
            headers = {key.lower(): value for key, value in calls[0]["headers"].items()}
            self.assertEqual(headers["x-guardian-ingest-key"], TOKEN)
            self.assertTrue({"cookie", "authorization", "x-guardian-key", "x-guardian-csrf"}.isdisjoint(headers))
            self.assertEqual(calls[0]["path"], "/api/guardian/ingest/events")
            self.assertIs(json.loads(calls[0]["body"])["test_mode"], True)

    def test_python_retries_identical_body(self):
        self._retry("python")

    def test_node_retries_identical_body(self):
        self._retry("node")

    def _retry(self, language):
        with receiver([(500, {}, b"server-content-canary"), (202, {}, None)]) as (origin, calls):
            batch = recipe.test_batch()
            batch["test_mode"] = False
            self.assertEqual(self.invoke(language, origin, batch=batch), {"ok": True, "code": "received"})
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["body"], calls[1]["body"])

    def test_python_returns_throttle_delay_without_retry_storm(self):
        self._throttle("python")

    def test_node_returns_throttle_delay_without_retry_storm(self):
        self._throttle("node")

    def _throttle(self, language):
        for status, delay, expected in [(429, "60", 60), (429, "bad", 60), (503, "50000", 3600)]:
            with self.subTest(status=status, delay=delay), receiver([(status, {"Retry-After": delay}, b"server-content-canary")]) as (origin, calls):
                result = self.invoke(language, origin)
                self.assertFalse(result["ok"])
                self.assertEqual(result["retry_after_seconds"], expected)
                self.assertEqual(len(calls), 1)

    def test_python_never_follows_redirects(self):
        self._redirect("python")

    def test_node_never_follows_redirects(self):
        self._redirect("node")

    def _redirect(self, language):
        with receiver([(202, {}, None)]) as (destination, leaked):
            with receiver([(307, {"Location": destination}, b"server-content-canary")]) as (origin, calls):
                self.assertFalse(self.invoke(language, origin)["ok"])
                self.assertEqual(leaked, [])
                self.assertLessEqual(len(calls), 3)

    def test_python_does_not_trust_receipts(self):
        self._receipt("python")

    def test_node_does_not_trust_receipts(self):
        self._receipt("node")

    def _receipt(self, language):
        for body in [b"server-content-canary", b"x" * 16385, {"batch_id": "wrong", "test_mode": True, "processing": "test_only"}]:
            with self.subTest(body_type=type(body).__name__), receiver([(202, {}, body)]) as (origin, _):
                self.assertEqual(self.invoke(language, origin), {"ok": False, "code": "receipt_unconfirmed"})

    def test_python_no_arguments_is_offline(self):
        self._offline("python")

    def test_node_no_arguments_is_offline(self):
        self._offline("node")

    def _offline(self, language):
        with receiver([(202, {}, None)]) as (origin, calls):
            self.assertIn("--send-test", self.invoke(language, origin, arguments=False))
            self.assertEqual(calls, [])

    def test_python_invalid_configuration_does_not_raise(self):
        self.assertEqual(recipe.send_batch({}, origin="http://example.com", token=TOKEN),
                         {"ok": False, "code": "invalid_configuration_or_batch"})

    def test_python_validates_complete_receipt_counts(self):
        self._strict_receipts("python")

    def test_node_validates_complete_receipt_counts(self):
        self._strict_receipts("node")

    def _strict_receipts(self, language):
        batch = recipe.test_batch()
        malformed = [receipt(batch, received=0), receipt(batch, received=2),
            receipt(batch, received=True), receipt(batch, received="1"), receipt(batch, received=1.5),
            receipt(batch, duplicate=-1), receipt(batch, duplicate=True), receipt(batch, conflict_candidates=2),
            receipt(batch, received=0, duplicate=1), receipt(batch, conflict_candidates=1),
            receipt(batch, replayed="false"), receipt(batch, unexpected="server-content-canary"),
            [], b"null"]
        for field in receipt(batch):
            value = receipt(batch)
            del value[field]
            malformed.append(value)
        for index, value in enumerate(malformed):
            with self.subTest(case=index), receiver([(202, {}, value)]) as (origin, calls):
                self.assertEqual(self.invoke(language, origin, batch=batch), {"ok": False, "code": "receipt_unconfirmed"})
                self.assertEqual(len(calls), 1)

    def test_python_accepts_production_duplicates_and_conflict_candidates(self):
        self._production_receipts("python")

    def test_node_accepts_production_duplicates_and_conflict_candidates(self):
        self._production_receipts("node")

    def _production_receipts(self, language):
        batch = recipe.test_batch()
        batch["test_mode"] = False
        for changes in ({"received": 0, "duplicate": 1, "replayed": True}, {"conflict_candidates": 1}):
            with self.subTest(changes=changes), receiver([(202, {}, receipt(batch, **changes))]) as (origin, calls):
                self.assertEqual(self.invoke(language, origin, batch=batch), {"ok": True, "code": "received"})
                self.assertEqual(len(calls), 1)
        for changes in ({"received": 0, "duplicate": 1, "conflict_candidates": 1},
                        {"received": 1, "duplicate": 1}, {"received": -1, "duplicate": 2}):
            with self.subTest(changes=changes), receiver([(202, {}, receipt(batch, **changes))]) as (origin, calls):
                self.assertEqual(self.invoke(language, origin, batch=batch), {"ok": False, "code": "receipt_unconfirmed"})
                self.assertEqual(len(calls), 1)

    def test_python_receipt_uses_exact_batch_event_count(self):
        self._multiple_events("python")

    def test_node_receipt_uses_exact_batch_event_count(self):
        self._multiple_events("node")

    def _multiple_events(self, language):
        batch = recipe.test_batch()
        batch["events"] *= 2
        for test_mode in (False, True):
            batch["test_mode"] = test_mode
            with self.subTest(test_mode=test_mode), receiver([(202, {}, receipt(batch))]) as (origin, _):
                self.assertEqual(self.invoke(language, origin, batch=batch),
                                 {"ok": True, "code": "test_received" if test_mode else "received"})
            with self.subTest(test_mode=test_mode), receiver([(202, {}, receipt(batch, received=1))]) as (origin, _):
                self.assertEqual(self.invoke(language, origin, batch=batch), {"ok": False, "code": "receipt_unconfirmed"})


if __name__ == "__main__":
    unittest.main()
