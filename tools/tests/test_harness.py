"""Harness contracts using stdlib only. No paid calls or external services."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import harness
import _harness_child as child_module


class CliTests(unittest.TestCase):
    def test_entrypoints_are_safe_without_packages_or_arguments(self):
        # -S prevents site packages, so accidental dotenv/FastAPI/etc imports fail.
        for script in ("verify_mvp.py", "build_baseline.py", "test_mongo_capture.py", "test_mongo_exporters.py", "test_mongo_policies.py", "test_mongo_notifications.py"):
            for args in ([], ["--help"]):
                result = subprocess.run(
                    [sys.executable, "-S", str(TOOLS / script), *args],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
                self.assertNotIn("[OK]", result.stdout)

    def test_no_args_never_spawns_child_or_writes_report(self):
        with patch.object(harness, "ChildProcess") as child, patch.object(harness, "write_report") as write, redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main([]), 0)
        child.assert_not_called()
        write.assert_not_called()

    def test_live_requires_explicit_opt_in_and_all_app_inputs(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            harness.parser().parse_args(["live"])
        self.assertEqual(error.exception.code, 2)
        args = ["live", "--founder-python", "f", "--guardian-python", "g", "--founder-env", "f.env", "--guardian-env", "g.env"]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            harness.parser().parse_args(args)

    def test_baseline_failure_propagates_to_process_exit_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report_path = Path(folder) / "report.json"
            result = subprocess.run([
                sys.executable, "-S", str(TOOLS / "build_baseline.py"), "live", "--allow-live",
                "--founder-python", sys.executable, "--guardian-python", sys.executable,
                "--founder-env", str(Path(folder) / "missing-founder.env"),
                "--guardian-env", str(Path(folder) / "missing-guardian.env"),
                "--report", str(report_path),
            ], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text())
        self.assertFalse(report["ok"])
        self.assertEqual(report["failure_code"], "configuration_invalid")
        self.assertNotIn(folder, result.stdout + result.stderr)

    def test_invalid_timeouts_and_baseline_counts_are_rejected(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.assertRaises(Exception):
                harness.positive_float(value)
        for value in ("0", "21", "two"):
            with self.assertRaises(Exception):
                harness.bounded_runs(value)


class EnvironmentTests(unittest.TestCase):
    def test_inherited_credentials_python_paths_and_proxies_do_not_survive(self):
        inherited = {
            "SystemRoot": "C:/Windows", "PATH": "system-path", "TEMP": "temp-path",
            "MONGO_URL": "mongodb://wrong-db", "DB_NAME": "wrong-app",
            "GUARDIAN_API_KEY": "wrong-key", "GROQ_API_KEY": "wrong-provider",
            "LANGFUSE_SECRET_KEY": "wrong-project", "PYTHONPATH": "wrong-imports",
            "PYTHONHOME": "wrong-interpreter", "HTTP_PROXY": "http://wrong-proxy",
            "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_OIDC_CLIENT_SECRET": "wrong-identity-secret",
            "GUARDIAN_CAPTURE_MODE": "direct",
        }
        env = harness.isolated_env("guardian", {"MONGO_URL": "mongodb://selected-db"}, inherited)
        self.assertEqual(env, {
            "SystemRoot": "C:/Windows", "PATH": "system-path", "TEMP": "temp-path",
            "MONGO_URL": "mongodb://selected-db", "PYTHON_DOTENV_DISABLED": "1",
            "GUARDIAN_AUTH_MODE": "api_key",
            "GUARDIAN_CAPTURE_MODE": "langfuse",
        })
        self.assertEqual(inherited["MONGO_URL"], "mongodb://wrong-db")

    def test_selected_files_are_separate_and_never_interpolated(self):
        with tempfile.TemporaryDirectory() as folder:
            founder = Path(folder) / "founder.env"
            guardian = Path(folder) / "guardian.env"
            founder.write_text("# separate app\nDB_NAME='guardian_verify_founder'\nMONGO_URL=mongodb://founder\n", encoding="utf-8")
            guardian.write_text('GUARDIAN_DB_NAME="guardian_verify_guardian"\nMONGO_URL=mongodb://guardian\n', encoding="utf-8")
            first = harness.parse_env_file(founder, "founder")
            second = harness.parse_env_file(guardian, "guardian")
            self.assertEqual(first["MONGO_URL"], "mongodb://founder")
            self.assertEqual(second["MONGO_URL"], "mongodb://guardian")
            self.assertNotIn("DB_NAME", second)
            for invalid in ("MONGO_URL=${MONGO_URL}", "DB_NAME=x", "PYTHONPATH=elsewhere", "MONGO_URL=x\nMONGO_URL=y"):
                guardian.write_text(invalid, encoding="utf-8")
                with self.assertRaises(harness.HarnessError):
                    harness.parse_env_file(guardian, "guardian")

    def test_normal_app_env_is_refused_even_if_readable(self):
        for backend in harness.BACKENDS.values():
            with self.assertRaises(harness.HarnessError):
                harness.parse_env_file(backend / ".env", "guardian")

    def test_live_boundaries_require_test_marker_separate_databases_and_same_source(self):
        common = {
            "GUARDIAN_HARNESS_TEST_ONLY": "1", "MONGO_URL": "mongodb://localhost:27017",
            "LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test", "LANGFUSE_HOST": "http://localhost:3000",
        }
        founder = common | {"DB_NAME": "guardian_verify_founder", "GROQ_API_KEY": "test-provider-key"}
        guardian = common | {"GUARDIAN_DB_NAME": "guardian_verify_guardian", "GUARDIAN_API_KEY": "test-guardian-key-long-enough"}
        harness.validate_live_env(founder, guardian)
        for changes in (
            {"GUARDIAN_HARNESS_TEST_ONLY": "0"}, {"GUARDIAN_DB_NAME": "production"},
            {"GUARDIAN_DB_NAME": founder["DB_NAME"]}, {"LANGFUSE_SECRET_KEY": "different-project"},
            {"GUARDIAN_API_KEY": ""},
            {"LANGFUSE_READ_API": "auto"},
        ):
            with self.assertRaises(harness.HarnessError):
                harness.validate_live_env(founder, guardian | changes)


class TransactionPreflightTests(unittest.IsolatedAsyncioTestCase):
    PRIVATE_ERROR = "mongodb://private-user:private-secret@private-host/provider-response"

    def database(self, *, start_error=None, insert_error=None, abort_error=None):
        events = []

        class Session:
            async def __aenter__(self):
                events.append("enter_session")
                return self

            async def __aexit__(self, exc_type, _exc, _traceback):
                events.append("exit_session")
                return False

            def start_transaction(self):
                events.append("start_transaction")

            async def abort_transaction(self):
                events.append("abort_transaction")
                if abort_error:
                    raise abort_error

            commit_transaction = AsyncMock()

        session = Session()

        async def start_session():
            events.append("start_session")
            if start_error:
                raise start_error
            return session

        async def insert_one(document, **kwargs):
            events.append("insert_one")
            self.assertEqual(document, {"_id": "transaction-capability"})
            self.assertIs(kwargs.get("session"), session)
            if insert_error:
                raise insert_error

        database = SimpleNamespace(
            client=SimpleNamespace(start_session=AsyncMock(side_effect=start_session)),
            guardian_preflight=SimpleNamespace(insert_one=AsyncMock(side_effect=insert_one)),
            command=AsyncMock(return_value={"ok": 1}),
            list_collection_names=AsyncMock(return_value=[]),
        )
        return database, session, events

    def assert_safe_failure(self, error):
        self.assertEqual(str(error), "mongo_transactions_required")
        self.assertTrue(error.__suppress_context__)
        self.assertNotIn(self.PRIVATE_ERROR, "".join(traceback.format_exception(error)))

    async def test_supported_transaction_is_aborted_after_real_write_attempt(self):
        database, session, events = self.database()
        await child_module.verify_mongo_transactions(database)
        self.assertEqual(events, [
            "start_session", "enter_session", "start_transaction", "insert_one",
            "abort_transaction", "exit_session",
        ])
        database.guardian_preflight.insert_one.assert_awaited_once()
        session.commit_transaction.assert_not_called()

    async def test_unsupported_session_fails_without_attempting_a_write(self):
        database, _session, events = self.database(start_error=NotImplementedError(self.PRIVATE_ERROR))
        with self.assertRaises(child_module.StepError) as failure:
            await child_module.verify_mongo_transactions(database)
        self.assert_safe_failure(failure.exception)
        self.assertEqual(events, ["start_session"])
        database.guardian_preflight.insert_one.assert_not_called()

    async def test_insert_failure_aborts_and_closes_session_without_leaking_driver_detail(self):
        database, session, events = self.database(insert_error=RuntimeError(self.PRIVATE_ERROR))
        with self.assertRaises(child_module.StepError) as failure:
            await child_module.verify_mongo_transactions(database)
        self.assert_safe_failure(failure.exception)
        self.assertEqual(events, [
            "start_session", "enter_session", "start_transaction", "insert_one",
            "abort_transaction", "exit_session",
        ])
        session.commit_transaction.assert_not_called()

    async def test_abort_failure_is_not_reported_as_success_and_closes_session(self):
        database, session, events = self.database(abort_error=RuntimeError(self.PRIVATE_ERROR))
        with self.assertRaises(child_module.StepError) as failure:
            await child_module.verify_mongo_transactions(database)
        self.assert_safe_failure(failure.exception)
        self.assertEqual(events[-2:], ["abort_transaction", "exit_session"])
        session.commit_transaction.assert_not_called()

    async def test_actual_preflight_requires_transaction_before_constructing_source(self):
        # Fake only imported app boundaries; run the real preflight orchestration
        # and transaction probe without loading app configuration or networking.
        for failure_stage in ("session", "insert"):
            with self.subTest(failure_stage=failure_stage):
                database, _session, events = self.database(
                    start_error=NotImplementedError(self.PRIVATE_ERROR) if failure_stage == "session" else None,
                    insert_error=RuntimeError(self.PRIVATE_ERROR) if failure_stage == "insert" else None,
                )
                source = MagicMock()
                imports = {
                    "uvicorn": SimpleNamespace(), "server": SimpleNamespace(app=object()),
                    "config": SimpleNamespace(DB_NAME="guardian_verify_transaction_probe"),
                    "db": SimpleNamespace(db=database),
                    "guardian.langfuse_client": SimpleNamespace(LangfuseTraceSource=source),
                }
                with patch.dict(sys.modules, imports), patch.dict(os.environ, {"GUARDIAN_HARNESS_TEST_ONLY": "1"}):
                    with self.assertRaises(child_module.StepError) as failure:
                        await child_module.preflight()
                self.assert_safe_failure(failure.exception)
                database.command.assert_awaited_once_with("ping")
                database.list_collection_names.assert_awaited_once()
                source.assert_not_called()
                if failure_stage == "insert":
                    self.assertEqual(events[-2:], ["abort_transaction", "exit_session"])


class ProcessTests(unittest.TestCase):
    def test_live_source_client_closes_on_success_and_failure(self):
        for fail in (False, True):
            source = SimpleNamespace(close=MagicMock())

            async def preflight():
                return source

            async def ingest(_request, actual_source):
                self.assertIs(actual_source, source)
                if fail:
                    raise child_module.StepError("live_source_failed")
                return {"source_api_version": "v2"}

            with patch.object(child_module, "preflight", preflight), \
                    patch.object(child_module, "_ingest_live_from_source", ingest):
                if fail:
                    with self.assertRaises(child_module.StepError):
                        asyncio.run(child_module.ingest_live({}))
                else:
                    self.assertEqual(asyncio.run(child_module.ingest_live({})), {"source_api_version": "v2"})
            source.close.assert_called_once()

    def test_source_mode_mismatch_stops_before_paid_workload(self):
        common = {
            "GUARDIAN_HARNESS_TEST_ONLY": "1", "MONGO_URL": "mongodb://localhost:27017",
            "LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_HOST": "https://example.invalid",
        }
        founder = common | {"DB_NAME": "guardian_verify_founder", "GROQ_API_KEY": "test-provider"}
        guardian = common | {"GUARDIAN_DB_NAME": "guardian_verify_guardian",
                             "GUARDIAN_API_KEY": "test-guardian-key-long-enough", "LANGFUSE_READ_API": "v2"}
        args = SimpleNamespace(allow_live=True, founder_env="founder.env", guardian_env="guardian.env",
                               founder_python=sys.executable, guardian_python=sys.executable, timeout=45)
        with patch.object(harness, "parse_env_file", side_effect=[founder, guardian]), \
                patch.object(harness, "ChildProcess") as process:
            process.return_value.__enter__.return_value.receive.return_value = {
                "event": "completed", "source_api_version": "v1",
            }
            with self.assertRaises(harness.HarnessError) as failure:
                harness.run_live(args, {}, 1)
            self.assertEqual(failure.exception.code, "child_protocol_invalid")
            self.assertEqual(process.call_count, 1)
            self.assertEqual(process.call_args.args[2], "guardian-preflight")

    def test_transaction_preflight_failure_never_starts_paid_workload(self):
        common = {
            "GUARDIAN_HARNESS_TEST_ONLY": "1", "MONGO_URL": "mongodb://localhost:27017",
            "LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_HOST": "https://example.invalid",
        }
        founder = common | {"DB_NAME": "guardian_verify_founder", "GROQ_API_KEY": "test-provider"}
        guardian = common | {"GUARDIAN_DB_NAME": "guardian_verify_guardian",
                             "GUARDIAN_API_KEY": "test-guardian-key-long-enough"}
        args = SimpleNamespace(allow_live=True, founder_env="founder.env", guardian_env="guardian.env",
                               founder_python=sys.executable, guardian_python=sys.executable, timeout=45)
        with patch.object(harness, "parse_env_file", side_effect=[founder, guardian]), \
                patch.object(harness, "ChildProcess") as process:
            process.return_value.__enter__.return_value.receive.side_effect = harness.HarnessError("mongo_transactions_required")
            with self.assertRaises(harness.HarnessError) as failure:
                harness.run_live(args, {}, 1)
            self.assertEqual(failure.exception.code, "mongo_transactions_required")
            self.assertEqual(process.call_count, 1)
            self.assertEqual(process.call_args.args[2], "guardian-preflight")

    def fake_child(self, folder, script, env=None):
        fixture = Path(folder) / "fixture.py"
        fixture.write_text(script, encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(harness, "CHILD", fixture).start()
        patch.object(harness, "BACKENDS", {"guardian": Path(folder)}).start()
        return harness.ChildProcess(sys.executable, "guardian", "fixture", env or harness.isolated_env("guardian", {}), {})

    def test_real_subprocess_sees_selected_environment_and_isolated_python(self):
        with tempfile.TemporaryDirectory() as folder:
            env = harness.isolated_env("guardian", {"GUARDIAN_API_KEY": "selected-value"}, os.environ | {"MONGO_URL": "wrong-value", "PYTHONPATH": folder})
            script = "import os,json,sys\nprint(json.dumps({'event':'completed','selected':os.getenv('GUARDIAN_API_KEY'),'mongo':os.getenv('MONGO_URL'),'isolated':sys.flags.isolated}))\n"
            with self.fake_child(folder, script, env) as child:
                result = child.receive(10)
                child.finish(10)
            self.assertEqual(result["selected"], "selected-value")
            self.assertIsNone(result["mongo"])
            self.assertEqual(result["isolated"], 1)

    def test_timeout_reaps_the_process(self):
        with tempfile.TemporaryDirectory() as folder:
            script = "import time,json\nprint(json.dumps({'event':'ready'}),flush=True)\ntime.sleep(60)\n"
            with self.assertRaises(harness.HarnessError) as error:
                with self.fake_child(folder, script) as child:
                    child.receive(10)
                    child.finish(0.05)
            self.assertEqual(error.exception.code, "child_timeout")
            self.assertIsNotNone(child.process.poll())

    def test_nonzero_exit_is_failure_even_after_completed_message(self):
        with tempfile.TemporaryDirectory() as folder:
            script = "import json\nprint(json.dumps({'event':'completed'}),flush=True)\nraise SystemExit(7)\n"
            with self.fake_child(folder, script) as child:
                child.receive(10)
                with self.assertRaises(harness.HarnessError) as error:
                    child.finish(10)
            self.assertEqual(error.exception.code, "child_failed")

    def test_untrusted_child_message_never_becomes_an_error_detail(self):
        with tempfile.TemporaryDirectory() as folder:
            script = "import json\nprint(json.dumps({'event':'error','code':'provider-secret-must-not-escape'}))\n"
            with self.fake_child(folder, script) as child:
                with self.assertRaises(harness.HarnessError) as error:
                    child.receive(10)
            self.assertEqual(str(error.exception), "child_failed")

    def test_interrupt_during_constructor_stops_and_reaps_the_owned_process(self):
        process = MagicMock()
        process.pid = 123456789
        process.poll.return_value = None
        process.stdin.write.side_effect = KeyboardInterrupt
        with patch.object(harness.subprocess, "Popen", return_value=process), patch.object(harness.subprocess, "run") as tree_stop, patch.object(harness.os, "killpg", create=True) as group_stop:
            with self.assertRaises(KeyboardInterrupt):
                harness.ChildProcess(sys.executable, "guardian", "fixture", {}, {})
        process.wait.assert_called()
        if os.name == "nt":
            self.assertIn(str(process.pid), tree_stop.call_args.args[0])
            self.assertIn("/T", tree_stop.call_args.args[0])
        else:
            group_stop.assert_called_once()


class HttpAndReportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests
        test = self
        cutoff = datetime.now(timezone.utc)
        cutoff = cutoff.replace(microsecond=(cutoff.microsecond // 1000) * 1000)
        self.created = cutoff - timedelta(seconds=2)
        self.summary = self.valid_summary(cutoff, self.created)
        self.summary_status = 200
        self.summary_auth_denied = True
        self.access = {"authenticated": True, "auth_mode": "api_key", "deployment_mode": "single_project",
                       "permissions": ["read", "resolve_incidents"]}
        self.access_status = 200
        self.access_auth_denied = True

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://must-never-be-contacted.invalid/")
                    self.end_headers()
                    return
                if self.path == "/api/health":
                    status, result = 200, {"service": "cost-guardian"}
                elif (self.headers.get("X-Guardian-Key") != "selected-test-key"
                      and (self.path != "/api/guardian/summary?days=14" or test.summary_auth_denied)
                      and (self.path != "/api/guardian/access" or test.access_auth_denied)):
                    status, result = 401, {}
                elif self.path == "/api/guardian/access":
                    status, result = test.access_status, test.access
                elif self.path == "/api/guardian/metrics":
                    status, result = 200, [{"call_count": 7}]
                elif self.path == "/api/guardian/summary?days=14":
                    status, result = test.summary_status, test.summary
                elif self.path.startswith("/api/guardian/incidents/"):
                    status, result = 200, {"id": "synthetic-incident", "detector": "cost_anomaly",
                                           "created_at": test.created.isoformat()}
                else:
                    status, result = 200, [{"id": "synthetic-incident"}]
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def valid_summary(cutoff, created):
        start = cutoff.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=13)
        return {
            "overview": {"open_incidents": 1, "incidents_last_7_days": 1,
                         "open_by_severity": {"high": 1}, "open_by_detector": {"cost_anomaly": 1}},
            "trends": [{"date": (start + timedelta(days=index)).date().isoformat(),
                        "count": int((start + timedelta(days=index)).date() == created.date())}
                       for index in range(14)],
            "coverage": {"status": "complete", "invalid_timestamp_count": 0}, "timezone": "UTC",
            "as_of": cutoff.isoformat(), "window_start": start.isoformat(), "window_end": cutoff.isoformat(),
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_http_contract_uses_header_and_rejects_legacy_cookie(self):
        result = harness.verify_http({"port": self.server.server_port, "incident_id": "synthetic-incident"}, "selected-test-key", time.monotonic() + 5, offline=True)
        self.assertEqual(result["auth_denials_checked"], 9)
        self.assertTrue(result["access_verified"])
        self.assertEqual(result["access_mode"], "api_key")
        self.assertEqual(result["deployment_mode"], "single_project")
        self.assertEqual(result["metric_call_count"], 7)
        self.assertEqual(result["summary_open_incidents"], 1)
        self.assertEqual(result["summary_recent_incidents"], 1)
        self.assertEqual(result["summary_trend_days"], 14)
        self.assertEqual(result["summary_coverage"], "complete")
        self.assertEqual(result["summary_timezone"], "UTC")
        self.assertTrue(any(headers.get("X-Guardian-Key") == "selected-test-key" for _, headers in self.requests))
        self.assertTrue(any("Cookie" in headers and "X-Guardian-Key" not in headers for _, headers in self.requests))
        summary_headers = [headers for path, headers in self.requests if path == "/api/guardian/summary?days=14"]
        self.assertEqual([headers.get("X-Guardian-Key") for headers in summary_headers],
                         [None, "incorrect-key", None, "selected-test-key"])
        self.assertIn("Cookie", summary_headers[2])

    def test_access_failure_stops_before_protected_data_and_keeps_error_private(self):
        self.access_status = 503
        self.access = {"detail": "private-server-config-must-not-escape"}
        with self.assertRaises(harness.HarnessError) as failure:
            harness.verify_http({"port": self.server.server_port}, "selected-test-key", time.monotonic() + 5, offline=True)
        self.assertEqual(str(failure.exception), "api_verification_failed")
        self.assertFalse(any(headers.get("X-Guardian-Key") == "selected-test-key"
                             and path != "/api/guardian/access" for path, headers in self.requests))

    def test_access_without_authentication_cannot_pass_the_smoke(self):
        self.access_auth_denied = False
        with self.assertRaises(harness.HarnessError) as failure:
            harness.verify_http({"port": self.server.server_port, "incident_id": "synthetic-incident"},
                                "selected-test-key", time.monotonic() + 5, offline=True)
        self.assertEqual(str(failure.exception), "api_verification_failed")

    def test_access_contract_requires_explicit_shared_key_permissions(self):
        cases = [None, [], {}, {**self.access, "authenticated": 1}, {**self.access, "authenticated": False},
                 {**self.access, "auth_mode": "session"}, {**self.access, "deployment_mode": "multi_project"},
                 {**self.access, "permissions": ["read"]}, {**self.access, "secret": "must-not-escape"}]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(harness.HarnessError) as failure:
                harness.verify_access(body)
            self.assertEqual(str(failure.exception), "api_verification_failed")

    def test_summary_http_failure_cannot_be_reported_as_verified_or_leak_body(self):
        self.summary_status = 503
        self.summary = {"detail": "private-database-error-must-not-escape"}
        with self.assertRaises(harness.HarnessError) as failure:
            harness.verify_http({"port": self.server.server_port, "incident_id": "synthetic-incident"},
                                "selected-test-key", time.monotonic() + 5, offline=True)
        self.assertEqual(str(failure.exception), "api_verification_failed")

    def test_summary_without_authentication_is_rejected_by_smoke(self):
        self.summary_auth_denied = False
        with self.assertRaises(harness.HarnessError) as failure:
            harness.verify_http({"port": self.server.server_port, "incident_id": "synthetic-incident"},
                                "selected-test-key", time.monotonic() + 5, offline=True)
        self.assertEqual(str(failure.exception), "api_verification_failed")

    def test_summary_contract_rejects_partial_wrong_counts_and_misleading_windows(self):
        cases = [
            (("coverage", "status"), "partial"), (("coverage", "invalid_timestamp_count"), 1),
            (("coverage", "invalid_timestamp_count"), False), (("timezone",), "local"),
            (("window_start",), self.summary["as_of"]), (("window_end",), self.summary["window_start"]),
            (("as_of",), "2026-01-01T12:00:00"),
            (("trends",), self.summary["trends"][:-1]),
            (("trends",), list(reversed(self.summary["trends"]))),
            (("overview", "open_incidents"), 0), (("overview", "incidents_last_7_days"), 0),
            (("overview", "open_by_severity"), {"medium": 1}),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                summary = deepcopy(self.summary)
                target = summary
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(harness.HarnessError) as failure:
                    harness.verify_summary(summary, {"created_at": self.created.isoformat()})
                self.assertEqual(str(failure.exception), "api_verification_failed")

    def test_summary_places_seeded_incident_before_midnight_in_its_actual_utc_day(self):
        cutoff = datetime(2026, 1, 1, 0, 0, 1, 234000, tzinfo=timezone.utc)
        created = datetime(2025, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
        summary = self.valid_summary(cutoff, created)
        result = harness.verify_summary(summary, {"created_at": created.isoformat()})
        self.assertEqual(result["summary_window_start"], "2025-12-19T00:00:00+00:00")
        self.assertEqual(summary["trends"][-2], {"date": "2025-12-31", "count": 1})
        self.assertEqual(summary["trends"][-1], {"date": "2026-01-01", "count": 0})

    def test_summary_cutoff_uses_millisecond_precision_and_excludes_future_fixture(self):
        summary = deepcopy(self.summary)
        summary["as_of"] = summary["window_end"] = (datetime.fromisoformat(summary["as_of"]) + timedelta(microseconds=1)).isoformat()
        with self.assertRaises(harness.HarnessError):
            harness.verify_summary(summary)
        with self.assertRaises(harness.HarnessError):
            harness.verify_summary(self.summary, {"created_at": self.summary["as_of"]})

    def test_key_cannot_follow_redirects(self):
        status, _ = harness.http_json(self.server.server_port, "/redirect", "selected-test-key")
        self.assertEqual(status, 302)
        self.assertEqual(len(self.requests), 1)

    def test_http_checks_stop_when_total_deadline_expires(self):
        elapsed = [0.0]

        def response(_port, path, *_args, **kwargs):
            self.assertLessEqual(kwargs["timeout"], 2.0)
            elapsed[0] += 1.0
            return (200, {"service": "cost-guardian"}) if path == "/api/health" else (401, None)

        with patch.object(harness.time, "monotonic", side_effect=lambda: elapsed[0]), patch.object(harness, "http_json", side_effect=response) as request:
            with self.assertRaises(harness.HarnessError) as error:
                harness.verify_http({"port": self.server.server_port}, "selected-test-key", 2.0, offline=False)
        self.assertEqual(error.exception.code, "child_timeout")
        self.assertEqual(request.call_count, 2)

    def test_failure_report_excludes_exception_secrets_and_preserves_truthful_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            report_path = Path(folder) / "report.json"
            output = io.StringIO()
            with patch.object(harness, "run_offline", side_effect=RuntimeError("do-not-leak-this-provider-secret")), redirect_stdout(output):
                code = harness.main(["offline", "--guardian-python", sys.executable, "--report", str(report_path)])
            report_text = report_path.read_text()
        report = json.loads(report_text)
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failure_code"], "child_failed")
        self.assertEqual(report["source"], "synthetic")
        self.assertEqual(report["persistence"], "mongomock")
        self.assertEqual(report["http_transport"], "localhost_tcp")
        self.assertNotIn("do-not-leak", output.getvalue() + report_text)

    def test_report_creates_its_parent_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reports" / "nested" / "verification.json"
            harness.write_report(path, {"ok": True})
            self.assertEqual(json.loads(path.read_text()), {"ok": True})


class LiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 9, 11, 12, 15, tzinfo=timezone.utc)
        self.metrics = [SimpleNamespace(
            trace_id="intended-run", agent_name=agent, model="priced-model", total_tokens=100,
            cost_usd=0.01, latency_ms=500.0, timestamp=self.when, status="success",
        ) for agent in child_module.EXPECTED_AGENTS]
        self.rollups = [{
            "hour": "2026-09-11T12:00:00+00:00", "agent_name": metric.agent_name,
            "call_count": 1, "error_count": 0, "total_cost_usd": 0.01,
            "total_tokens": 100, "sum_latency_ms": 500.0,
        } for metric in self.metrics]

    def test_exact_actual_worker_candidates_reconcile(self):
        child_module.validate_live_rollups([{"run_id": "intended-run"}], self.metrics, self.rollups)

    def test_unrelated_traffic_cannot_substitute_for_intended_worker_input(self):
        for metric in self.metrics:
            metric.trace_id = "unrelated-run"
        with self.assertRaises(child_module.StepError) as error:
            child_module.validate_live_rollups([{"run_id": "intended-run"}], self.metrics, self.rollups)
        self.assertEqual(str(error.exception), "live_worker_failed")

    def test_correct_total_count_cannot_mask_wrong_persisted_cost(self):
        self.rollups[0]["total_cost_usd"] = 5.0
        with self.assertRaises(child_module.StepError) as error:
            child_module.validate_live_rollups([{"run_id": "intended-run"}], self.metrics, self.rollups)
        self.assertEqual(str(error.exception), "live_worker_failed")


if __name__ == "__main__":
    unittest.main()
