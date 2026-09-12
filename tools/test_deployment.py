#!/usr/bin/env python
"""Actual native deployment -> local signed OIDC -> browser -> Mongo/worker.

No arguments print stdlib-only help. Requires explicit isolated dependencies and
local test Mongo. Never loads application .env, account or provider credentials.
This is native-process evidence, not a Docker, public TLS or customer IdP test.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "deployment-fixtures"
BACKEND = ROOT / "apps" / "guardian" / "backend"
sys.path.insert(0, str(ROOT / "tools"))
from harness import SYSTEM_KEYS
from test_mongo_ledger import validate_url


class CheckFailed(Exception): pass


class ChildStartupFailure(CheckFailed):
    def __init__(self, child):
        self.child = child
        super().__init__("owned_child_cleanup_uncertain")


def check(condition, code):
    if not condition: raise CheckFailed(code)


def system_environment():
    # Playwright locates installed Windows Edge using the OS program directories.
    allowed = SYSTEM_KEYS | {"PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


class Child:
    """Bounded logs stay private; owned descendants are reaped before DB cleanup."""
    def __init__(self, command, config, *, cwd=BACKEND):
        self.buffers = [bytearray(), bytearray()]
        self.overflow = False
        self.closed = False
        self.readers = []
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.process = subprocess.Popen(command, cwd=cwd, env=system_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        try:
            for stream, buffer in zip((self.process.stdout, self.process.stderr), self.buffers):
                def drain(source=stream, target=buffer):
                    while data := source.read(4096):
                        if len(target) + len(data) <= 65536: target.extend(data)
                        else: self.overflow = True
                thread = threading.Thread(target=drain, daemon=True)
                thread.start()
                self.readers.append(thread)
            self.process.stdin.write(json.dumps(config).encode())
            self.process.stdin.close()
        except BaseException:
            try: self.close()
            except BaseException: raise ChildStartupFailure(self) from None
            raise

    def wait(self, seconds=30):
        try: self.process.wait(timeout=seconds)
        except subprocess.TimeoutExpired: raise CheckFailed("owned_child_timeout") from None
        for thread in self.readers: thread.join(3)
        check(not self.overflow and not any(thread.is_alive() for thread in self.readers), "owned_child_output_limit")
        return self.process.returncode

    def result(self, seconds=30):
        self.wait(seconds)
        try: result = json.loads(bytes(self.buffers[0]))
        except (ValueError, UnicodeError): raise CheckFailed("owned_child_protocol_invalid") from None
        check(isinstance(result, dict), "owned_child_protocol_invalid")
        return result

    def close(self):
        if self.closed: return
        if self.process.poll() is None:
            if os.name == "nt":
                taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
                subprocess.run([str(taskkill), "/PID", str(self.process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try: os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: self.process.wait(10)
                except subprocess.TimeoutExpired:
                    try: os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            self.process.wait(10)
        for thread in self.readers: thread.join(3)
        check(not any(thread.is_alive() for thread in self.readers), "owned_child_cleanup_uncertain")
        for stream in (self.process.stdout, self.process.stderr): stream.close()
        self.closed = True


def request(origin, path, *, timeout=4):
    opener = build_opener(ProxyHandler({}))
    try: response = opener.open(Request(origin + path), timeout=timeout)
    except HTTPError as error: response = error
    with response:
        data = response.read(1048577)
        check(len(data) <= 1048576, "http_response_unbounded")
        return response.status, {key.lower(): value for key, value in response.headers.items()}, data


def await_ready(origin, child, *, expected=200, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        check(child.process.poll() is None, "api_exited_before_readiness")
        try:
            # The endpoint itself permits five seconds for a failing DB check.
            status, headers, body = request(origin, "/api/ready", timeout=min(7, max(.1, deadline - time.monotonic())))
            if status == expected:
                check(json.loads(body) == {"status": "ready" if expected == 200 else "not_ready", "service": "cost-guardian"}, "readiness_response_invalid")
                check("no-store" in headers.get("cache-control", ""), "readiness_cacheable")
                return
        except (URLError, OSError, ValueError): pass
        time.sleep(.1)
    raise CheckFailed("readiness_deadline")


def free_port():
    with socket.socket() as owned:
        owned.bind(("127.0.0.1", 0))
        return owned.getsockname()[1]


def launch(python, environment, arguments):
    return Child([python, "-I", str(FIXTURES / "launch.py"), "--run"], {"environment": environment, "arguments": arguments})


def remove_owned_database(admin, db, database, owner, *, children_clean):
    check(children_clean, "owned_child_cleanup_uncertain")
    check(database == "guardian_deployment_test_" + owner and re.fullmatch(r"[a-f0-9]{32}", owner), "cleanup_scope_invalid")
    check(db["_deployment_owner"].find_one({"_id": owner, "purpose": "guardian-native-deployment-smoke"}), "cleanup_marker_missing")
    admin.drop_database(database)
    check(database not in admin.list_database_names(), "cleanup_database_remains")


def deployment_environment(uri, database, origin, issuer, static_dir):
    return {**system_environment(), "PYTHON_DOTENV_DISABLED": "1", "GUARDIAN_CAPTURE_MODE": "direct",
        "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH": "true", "MONGO_URL": uri,
        "GUARDIAN_DB_NAME": database, "GUARDIAN_PUBLIC_URL": origin, "GUARDIAN_UI_ORIGIN": origin,
        "GUARDIAN_BIND_HOST": "127.0.0.1", "GUARDIAN_PORT": str(urlsplit(origin).port),
        "GUARDIAN_STATIC_DIR": str(static_dir), "GUARDIAN_POLL_INTERVAL_SECONDS": "1",
        "GUARDIAN_OIDC_ISSUER": issuer.origin, "GUARDIAN_OIDC_CLIENT_ID": issuer.client_id,
        "GUARDIAN_OIDC_CLIENT_SECRET": issuer.client_secret, "GUARDIAN_ORGANIZATION_ID": "deployment-fixture-org",
        "GUARDIAN_PROJECT_ID": "deployment-fixture-project", "GUARDIAN_PROJECT_NAME": "Deployment Fixture",
        "GUARDIAN_ENVIRONMENT": "test", "GUARDIAN_CONNECTION_ID": "deployment-fixture",
        "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([{"subject": "deployment-owner", "role": "owner", "name": "Synthetic Owner"}])}


def run_suite(args, report_dir):
    # Dependency imports happen only after explicit arguments pass validation.
    from pymongo import MongoClient
    sys.path.insert(0, str(FIXTURES))
    from oidc import OIDCFixture
    from mongo_proxy import MongoProxy
    started = time.monotonic()
    owner = uuid4().hex
    database = "guardian_deployment_test_" + owner
    admin = MongoClient(args.mongo_url, serverSelectionTimeoutMS=3000, connectTimeoutMS=2000, socketTimeoutMS=5000)
    db = admin[database]
    children, steps = [], []
    created = False
    result = {"status": "failed", "evidence_type": "native_entrypoints_actual_oidc_browser_and_mongo", "steps": steps}
    def step(name):
        steps.append(name)
        print(json.dumps({"progress": name}), file=sys.stderr, flush=True)
    def register(child): children.append(child); return child
    try:
        hello = admin.admin.command("hello")
        check(hello.get("setName") == "guardian-r102" and hello.get("isWritablePrimary") and len(hello.get("hosts", [])) == 1, "owned_replica_required")
        check(database not in admin.list_database_names(), "database_not_fresh")
        db["_deployment_owner"].insert_one({"_id": owner, "purpose": "guardian-native-deployment-smoke"})
        created = True
        result["mongo_version"] = admin.server_info()["version"]
        mongo_address = urlsplit(args.mongo_url)
        origin = "http://127.0.0.1:" + str(free_port())
        with ExitStack() as stack:
            proxy = stack.enter_context(MongoProxy(mongo_address.hostname, mongo_address.port or 27017))
            issuer = stack.enter_context(OIDCFixture(origin + "/api/guardian/auth/callback"))
            proxied_uri = "mongodb://127.0.0.1:" + str(proxy.port) + "/?replicaSet=guardian-r102&directConnection=true"
            environment = deployment_environment(proxied_uri, database, origin, issuer, args.static_dir)
            child = register(launch(args.guardian_python, environment, ["check"]))
            configured = child.result()
            result["configuration_check"] = {key: configured[key] for key in ("status", "command", "code") if key in configured}
            check(child.process.returncode == 0, "deployment_offline_check_failed")
            invalid = {key: value for key, value in environment.items() if key != "GUARDIAN_OIDC_CLIENT_SECRET"}
            check(register(launch(args.guardian_python, invalid, ["check"])).wait() != 0, "missing_configuration_accepted")
            check(not issuer.counts, "offline_check_contacted_identity")
            step("offline_configuration_and_missing_secret")
            standalone = MongoClient(args.standalone_url, directConnection=True, serverSelectionTimeoutMS=3000,
                connectTimeoutMS=2000, socketTimeoutMS=5000)
            refused = None
            try:
                check(not standalone.admin.command("hello").get("setName"), "explicit_standalone_required")
                check(database not in standalone.list_database_names(), "standalone_database_not_fresh")
                standalone[database]["_deployment_owner"].insert_one({"_id": owner, "purpose": "guardian-native-deployment-smoke"})
                refused = register(launch(args.guardian_python, {**environment, "MONGO_URL": args.standalone_url}, ["bootstrap"]))
                check(refused.result(60) == {"status": "failed", "code": "transaction_database_required"}
                    and refused.process.returncode != 0, "standalone_bootstrap_not_refused")
                check(standalone[database].list_collection_names() == ["_deployment_owner"], "standalone_refusal_wrote_state")
            finally:
                try:
                    if refused: refused.close()
                    if standalone[database]["_deployment_owner"].find_one({"_id": owner, "purpose": "guardian-native-deployment-smoke"}):
                        remove_owned_database(standalone, standalone[database], database, owner, children_clean=not refused or refused.closed)
                finally: standalone.close()
            step("actual_standalone_refused_without_state_writes")
            # Reject a late initialization write using actual Mongo validation.
            # This preserves ordinary driver abort semantics; synthetic commit
            # rejection can leave a server TX open after driver marks COMMITTED.
            db.create_collection("guardian_notification_settings", validator={"$expr": {"$eq": [1, 0]}}, validationAction="error")
            db.command({"profile": 2, "filter": {"errCode": 121}})
            try:
                aborted = register(launch(args.guardian_python, environment, ["bootstrap"]))
                check(aborted.result(60) == {"status": "failed", "code": "bootstrap_unavailable"}
                    and aborted.process.returncode != 0, "validator_bootstrap_did_not_fail")
                check(db["system.profile"].find_one({"errCode": 121,
                    "ns": database + ".guardian_notification_settings"}), "late_write_validation_error_not_observed")
                check(all(db[name].count_documents({}) == 0 for name in
                    ("guardian_state", "guardian_monitoring_policies", "guardian_notification_settings")),
                    "aborted_bootstrap_left_partial_binding")
                result["bootstrap_rollback"] = {"injection": "late_notification_head_validator", "mongo_error_code": 121,
                    "identity_source_ledger_heads_and_marker_absent": True}
            finally:
                db.command({"profile": 0})
                db.command({"collMod": "guardian_notification_settings", "validator": {}, "validationLevel": "off"})
            step("real_bootstrap_late_write_failure_rolls_back_bindings_and_marker")
            bootstrap = register(launch(args.guardian_python, environment, ["bootstrap"]))
            initialized = bootstrap.result(60)
            result["bootstrap"] = {key: initialized[key] for key in ("status", "command", "code") if key in initialized}
            check(initialized == {"status": "ready", "command": "bootstrap"} and bootstrap.process.returncode == 0, "bootstrap_failed")
            left = register(launch(args.guardian_python, environment, ["bootstrap"]))
            right = register(launch(args.guardian_python, environment, ["bootstrap"]))
            check(left.wait() == right.wait() == 0, "concurrent_bootstrap_replay_failed")
            before = list(db.guardian_state.find({}))
            mismatch = register(launch(args.guardian_python, {**environment, "GUARDIAN_PROJECT_ID": "different-project"}, ["bootstrap"]))
            check(mismatch.wait() != 0 and list(db.guardian_state.find({})) == before, "bootstrap_mismatch_mutated_state")
            check(not issuer.counts, "bootstrap_contacted_identity")
            step("bootstrap_idempotence_concurrency_and_mismatch")
            api = register(launch(args.guardian_python, environment, ["run", "api"]))
            await_ready(origin, api)
            check(request(origin, "/api/health")[0] == 200, "liveness_failed")
            check(request(origin, "/api/guardian/access")[0] == 401, "anonymous_data_read_accepted")
            for path in ("/api/nonexistent", "/.env", "/server.py", "/static/missing.js", "/unknown-route"):
                status, headers, body = request(origin, path)
                check(status == 404 and b'<div id="root">' not in body, "static_or_api_boundary_failed")
            status, headers, body = request(origin, "/setup")
            check(status == 200 and b'<div id="root">' in body and "no-store" in headers.get("cache-control", ""), "setup_shell_unavailable")
            step("actual_lifespan_readiness_static_and_authority")
            worker = register(launch(args.guardian_python, environment, ["run", "worker"]))
            browser_config = {"origin": origin, "issuer": issuer.origin, "playwright": str(args.playwright),
                "module_dir": str(ROOT / "examples" / "native-capture"), "report_dir": str(report_dir), "phase": "first"}
            browser = register(Child([args.node, str(FIXTURES / "browser.cjs"), "--run"], browser_config, cwd=ROOT))
            first = browser.result(120)
            if first.get("status") != "passed": result["browser_failure"] = first
            check(first.get("status") == "passed" and browser.process.returncode == 0, "browser_first_" + str(first.get("phase", "failed")))
            result["first_journey"] = first
            step("browser_oidc_key_test_worker_incident_run_resolve_replay_logout")
            worker.close()
            api.close()
            api = register(launch(args.guardian_python, environment, ["run", "api"]))
            await_ready(origin, api)
            worker = register(launch(args.guardian_python, environment, ["run", "worker"]))
            repeat = {**browser_config, "phase": "restart", "trace_id": first["trace_id"], "incident_id": first["incident_id"]}
            browser = register(Child([args.node, str(FIXTURES / "browser.cjs"), "--run"], repeat, cwd=ROOT))
            second = browser.result(90)
            check(second.get("status") == "passed" and browser.process.returncode == 0, "browser_restart_" + str(second.get("phase", "failed")))
            result["restart_journey"] = second
            step("controlled_api_worker_restart_preserves_accounting_and_resolution")
            proxy.cut()
            await_ready(origin, api, expected=503, seconds=15)
            check(request(origin, "/api/health")[0] == 200, "database_outage_changed_liveness")
            proxy.restore()
            await_ready(origin, api)
            step("database_transport_outage_readiness_503_and_recovery")
            check(issuer.counts["approved"] == issuer.counts["token"] == issuer.counts["jwks"] == 2, "actual_oidc_exchange_count_wrong")
            result["oidc_requests"] = dict(issuer.counts)
            for name in db.list_collection_names():
                content = json.dumps(list(db[name].find({}).limit(200)), default=str)
                check(issuer.client_secret not in content and not re.search(r"cg_ingest_[a-f0-9]{32}_[A-Za-z0-9_-]{43}", content), "secret_persisted_in_database")
            for child in children:
                check(issuer.client_secret.encode() not in child.buffers[0] + child.buffers[1], "secret_in_process_logs")
            # Stop roles while their own fixture services are still available.
            for child in reversed(children): child.close()
            with socket.socket() as probe:
                check(probe.connect_ex(("127.0.0.1", urlsplit(origin).port)) != 0, "api_listener_not_closed")
        result.update(status="passed", paid_provider_calls=0, customer_services=False,
            frontend_manifest_sha256=hashlib.sha256((args.static_dir / "asset-manifest.json").read_bytes()).hexdigest())
    except Exception as error:
        if isinstance(error, ChildStartupFailure): children.append(error.child)
        result["error_type"] = type(error).__name__
        if isinstance(error, CheckFailed) and re.fullmatch(r"[a-z_]{1,100}", str(error)): result["code"] = str(error)
    finally:
        cleanup = True
        for child in reversed(children):
            try: child.close()
            except Exception as error:
                cleanup = False
                result.setdefault("cleanup_errors", []).append({"kind": type(error).__name__,
                    "returncode": child.process.poll(), "readers_alive": sum(thread.is_alive() for thread in child.readers)})
        if created:
            try:
                remove_owned_database(admin, db, database, owner, children_clean=cleanup)
            except Exception as error:
                cleanup = False
                result.setdefault("cleanup_errors", []).append({"kind": type(error).__name__, "stage": "owned_database"})
        admin.close()
        result["cleanup_complete"] = cleanup
        if not cleanup: result["status"] = "failed"
    result.update(finished_at=datetime.now(timezone.utc).isoformat(), duration_seconds=round(time.monotonic() - started, 3),
        role_shutdown="owned_tree_termination" if os.name == "nt" else "sigterm_with_bounded_fallback")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit owned localhost guardian-r102 test replica")
    parser.add_argument("--guardian-python", help="Explicit Guardian interpreter")
    parser.add_argument("--standalone-url", help="Explicit separate owned localhost standalone Mongo negative fixture")
    parser.add_argument("--playwright", help="Explicit isolated Playwright module directory")
    parser.add_argument("--static-dir", help="Explicit allowlisted production frontend build")
    parser.add_argument("--node", default="node")
    parser.add_argument("--report", default="tools/reports/deployment-native/report.json")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    report = None
    try:
        args.mongo_url = validate_url(args.mongo_url)
        check(bool(args.standalone_url), "standalone_fixture_required")
        args.standalone_url = validate_url(args.standalone_url)
        check(urlsplit(args.mongo_url).port != urlsplit(args.standalone_url).port, "distinct_mongo_fixtures_required")
        report = Path(args.report).resolve()
        check(report.is_relative_to((ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
        check(bool(args.guardian_python and args.playwright and args.static_dir), "explicit_dependency_paths_required")
        args.guardian_python = shutil.which(args.guardian_python)
        args.node = shutil.which(args.node)
        check(args.guardian_python and args.node, "interpreter_missing")
        args.playwright, args.static_dir = Path(args.playwright).resolve(), Path(args.static_dir).resolve()
        check((args.playwright / "package.json").is_file() and (args.static_dir / "asset-manifest.json").is_file(), "fixture_dependencies_missing")
        report.parent.mkdir(parents=True, exist_ok=True)
        result = run_suite(args, report.parent)
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, CheckFailed): result["code"] = str(error)
    if report and report.is_relative_to((ROOT / "tools" / "reports").resolve()):
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__": raise SystemExit(main())
