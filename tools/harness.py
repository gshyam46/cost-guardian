"""Stdlib-only parent process. Never imports either application's modules.

Children receive an allowlisted environment and run one app under its interpreter.
Application logs and exception messages are never copied into reports: they can
contain provider keys, connection strings or customer data.
"""
from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).with_name("_harness_child.py")
BACKENDS = {
    "guardian": ROOT / "apps" / "guardian" / "backend",
    "founder": ROOT / "apps" / "founder-app" / "backend",
}
DEFAULT_REPORT = Path(__file__).with_name("verify_mvp_report.json")
SYSTEM_KEYS = {
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "LANG", "LC_ALL", "LC_CTYPE",
}
COMMON_KEYS = {
    "MONGO_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
    "GUARDIAN_HARNESS_TEST_ONLY",
}
APP_KEYS = {
    "guardian": COMMON_KEYS | {
        "GUARDIAN_DB_NAME", "GUARDIAN_API_KEY", "GUARDIAN_PORT",
        "GUARDIAN_CORS_ORIGINS", "GUARDIAN_POLL_INTERVAL_SECONDS",
        "LANGFUSE_READ_API", "GUARDIAN_CONNECTION_ID",
    },
    "founder": COMMON_KEYS | {
        "DB_NAME", "CORS_ORIGINS", "GOOGLE_GEMINI_API_KEY", "EMERGENT_LLM_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
    },
}
ERROR_CODES = {
    "configuration_invalid", "interpreter_missing", "child_start_failed",
    "child_timeout", "child_failed", "child_protocol_invalid", "dependency_missing",
    "offline_worker_failed", "live_source_failed", "live_mapping_failed",
    "live_worker_failed", "test_database_not_empty", "founder_workload_failed", "mongo_transactions_required",
    "api_verification_failed", "report_write_failed", "interrupted",
}


class HarnessError(Exception):
    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "child_failed"
        super().__init__(self.code)


def parse_env_file(path: Path, app: str) -> dict[str, str]:
    """Read KEY=value, quoted values and full-line comments; no interpolation.

    Reject duplicate/unknown keys, export syntax and ${...} instead of resolving
    them using another application's environment. Normal app .env files are refused.
    """
    path = path.resolve()
    if path in {backend / ".env" for backend in BACKENDS.values()}:
        raise HarnessError("configuration_invalid")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise HarnessError("configuration_invalid") from None
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in APP_KEYS[app] or key in values or "${" in value:
            raise HarnessError("configuration_invalid")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise HarnessError("configuration_invalid")
            value = value[1:-1]
        if "\x00" in value:
            raise HarnessError("configuration_invalid")
        values[key] = value
    return values


def isolated_env(app: str, values: dict[str, str], inherited=None) -> dict[str, str]:
    """Only OS essentials survive; application/provider/Python/proxy vars do not."""
    inherited = os.environ if inherited is None else inherited
    env = {k: v for k, v in inherited.items() if k.upper() in SYSTEM_KEYS}
    if set(values) - APP_KEYS[app]:
        raise HarnessError("configuration_invalid")
    env.update(values)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    if app == "guardian":
        # This smoke proves the legacy API-key path; OIDC has its own acceptance.
        env["GUARDIAN_AUTH_MODE"] = "api_key"
        env["GUARDIAN_CAPTURE_MODE"] = "langfuse"
    return env


def validate_live_env(founder: dict, guardian: dict) -> None:
    for values, db_key in ((founder, "DB_NAME"), (guardian, "GUARDIAN_DB_NAME")):
        if values.get("GUARDIAN_HARNESS_TEST_ONLY") != "1":
            raise HarnessError("configuration_invalid")
        if not re.fullmatch(r"guardian_verify_[a-z0-9_]{1,40}", values.get(db_key, "")):
            raise HarnessError("configuration_invalid")
        for required in ("MONGO_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
            if not values.get(required):
                raise HarnessError("configuration_invalid")
        if not values["MONGO_URL"].startswith(("mongodb://", "mongodb+srv://")):
            raise HarnessError("configuration_invalid")
        if not values["LANGFUSE_HOST"].startswith(("https://", "http://")):
            raise HarnessError("configuration_invalid")
    if founder["DB_NAME"] == guardian["GUARDIAN_DB_NAME"]:
        raise HarnessError("configuration_invalid")
    if any(founder[key] != guardian[key] for key in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"
    )):
        raise HarnessError("configuration_invalid")
    if len(guardian.get("GUARDIAN_API_KEY", "")) < 16:
        raise HarnessError("configuration_invalid")
    if guardian.get("LANGFUSE_READ_API", "v2") not in {"v1", "v2"}:
        raise HarnessError("configuration_invalid")
    # The current sample app's fallback chain actually uses these two providers.
    if not (founder.get("GROQ_API_KEY") or founder.get("OPENROUTER_API_KEY")):
        raise HarnessError("configuration_invalid")


def python_path(value: str) -> str:
    path = Path(value).resolve()
    if not path.is_file():
        raise HarnessError("interpreter_missing")
    return str(path)


class ChildProcess(AbstractContextManager):
    """Own one process: no shell, server reload, multiple workers or console.

    Only the first stdout line is a protocol message. It is never displayed, even
    if an SDK unexpectedly writes there. Every exit path reaps the owned process.
    """
    def __init__(self, python: str, app: str, mode: str, env: dict, request: dict):
        self.process = None
        self.reader = None
        self.messages = queue.Queue()
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        try:
            self.process = subprocess.Popen(
                [python_path(python), "-I", str(CHILD), mode],
                cwd=str(BACKENDS[app]), env=env, text=True, encoding="utf-8",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **options,
            )
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.close()
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException as error:
            # __enter__ has not happened yet, so the context manager cannot clean
            # up if Ctrl-C or thread startup fails after Popen succeeded.
            self.close()
            if isinstance(error, (HarnessError, KeyboardInterrupt, SystemExit)):
                raise
            raise HarnessError("child_start_failed") from None

    def _read(self):
        try:
            self.messages.put(self.process.stdout.readline(65536))
        except (OSError, ValueError):
            self.messages.put("")

    def receive(self, timeout: float) -> dict:
        try:
            line = self.messages.get(timeout=max(0.01, timeout))
        except queue.Empty:
            raise HarnessError("child_timeout") from None
        try:
            result = json.loads(line)
        except (ValueError, TypeError):
            raise HarnessError("child_protocol_invalid") from None
        if not isinstance(result, dict) or result.get("event") not in {"ready", "completed", "error"}:
            raise HarnessError("child_protocol_invalid")
        if result["event"] == "error":
            raise HarnessError(result.get("code", "child_failed"))
        return result

    def finish(self, timeout: float):
        try:
            code = self.process.wait(timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            raise HarnessError("child_timeout") from None
        if code != 0:
            raise HarnessError("child_failed")

    def close(self):
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                if os.name == "nt":
                    # Windows venv/Store python.exe can be a launcher which owns
                    # another Python process. Terminating only that wrapper leaks
                    # the server and its current-directory handle.
                    taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
                    subprocess.run(
                        [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=5, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout):
            if stream and not stream.closed:
                stream.close()
        if self.reader and self.reader.is_alive():
            self.reader.join(timeout=1)

    def __exit__(self, *_):
        self.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def http_json(port: int, path: str, key: str | None = None, cookie=False, timeout=5.0):
    """Always loopback. Never send the key through redirects or ambient proxies."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise HarnessError("child_protocol_invalid")
    if timeout <= 0:
        raise HarnessError("child_timeout")
    headers = {"X-Guardian-Key": key} if key else {}
    if cookie:
        headers = {"Cookie": "session_token=legacy-session-must-not-authenticate"}
    request = urllib.request.Request("http://127.0.0.1:" + str(port) + path, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=min(5, timeout)) as response:
            return response.status, json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        return error.code, None
    except (OSError, ValueError, urllib.error.URLError):
        raise HarnessError("api_verification_failed") from None


def verify_summary(summary: dict, offline_incident=None) -> dict:
    """Validate the bounded public count/window contract without app imports."""
    def count(value):
        if type(value) is not int or value < 0:
            raise ValueError
        return value

    def utc(value):
        if not isinstance(value, str):
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed

    try:
        coverage = summary["coverage"]
        if (summary["timezone"] != "UTC" or coverage["status"] != "complete"
                or count(coverage["invalid_timestamp_count"]) != 0):
            raise ValueError
        end = utc(summary["as_of"])
        start = end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=13)
        if end.microsecond % 1000 or utc(summary["window_start"]) != start or utc(summary["window_end"]) != end:
            raise ValueError
        points = summary["trends"]
        dates = [(start + timedelta(days=index)).date().isoformat() for index in range(14)]
        if not isinstance(points, list) or len(points) != 14 or [row["date"] for row in points] != dates:
            raise ValueError
        counts = [count(row["count"]) for row in points]
        overview = summary["overview"]
        opened, recent = count(overview["open_incidents"]), count(overview["incidents_last_7_days"])
        for field in ("open_by_severity", "open_by_detector"):
            if not isinstance(overview[field], dict) or sum(count(value) for value in overview[field].values()) != opened:
                raise ValueError
        if sum(counts[-7:]) != recent:
            raise ValueError
        if offline_incident is not None:
            created = utc(offline_incident["created_at"])
            if (not start <= created < end or opened != 1 or recent != 1
                    or overview["open_by_severity"] != {"high": 1}
                    or overview["open_by_detector"] != {"cost_anomaly": 1}
                    or sum(counts) != 1 or counts[dates.index(created.date().isoformat())] != 1):
                raise ValueError
        return {"summary_open_incidents": opened, "summary_recent_incidents": recent,
                "summary_trend_days": len(points), "summary_coverage": "complete", "summary_timezone": "UTC",
                "summary_window_start": start.isoformat(), "summary_window_end": end.isoformat()}
    except (KeyError, TypeError, ValueError, OverflowError):
        raise HarnessError("api_verification_failed") from None


def verify_access(access):
    """Require the declared shared-key contract, without trusting arbitrary 200s."""
    expected = {"authenticated": True, "auth_mode": "api_key", "deployment_mode": "single_project",
                "permissions": ["read", "resolve_incidents"]}
    if not isinstance(access, dict) or type(access.get("authenticated")) is not bool or access != expected:
        raise HarnessError("api_verification_failed")
    return {"access_verified": True, "access_mode": "api_key", "deployment_mode": "single_project"}


def verify_http(message: dict, key: str, deadline: float, offline: bool) -> dict:
    port = message.get("port")

    def request(path, presented_key=None, cookie=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError("child_timeout")
        return http_json(port, path, presented_key, cookie=cookie, timeout=remaining)

    while True:
        try:
            status, health = request("/api/health")
            if status == 200 and isinstance(health, dict) and health.get("service") == "cost-guardian":
                break
        except HarnessError as error:
            if error.code != "api_verification_failed":
                raise
        if time.monotonic() >= deadline:
            raise HarnessError("child_timeout")
        time.sleep(0.1)
    unauthorized = [
        request("/api/guardian/access")[0],
        request("/api/guardian/access", "incorrect-key")[0],
        request("/api/guardian/access", cookie=True)[0],
        request("/api/guardian/incidents")[0],
        request("/api/guardian/incidents", "incorrect-key")[0],
        request("/api/guardian/incidents", cookie=True)[0],
        request("/api/guardian/summary?days=14")[0],
        request("/api/guardian/summary?days=14", "incorrect-key")[0],
        request("/api/guardian/summary?days=14", cookie=True)[0],
    ]
    access_status, access = request("/api/guardian/access", key)
    if access_status != 200:
        raise HarnessError("api_verification_failed")
    access_counts = verify_access(access)
    status, incidents = request("/api/guardian/incidents", key)
    metric_status, metrics = request("/api/guardian/metrics", key)
    summary_status, summary = request("/api/guardian/summary?days=14", key)
    if unauthorized != [401] * 9 or status != 200 or metric_status != 200 or summary_status != 200:
        raise HarnessError("api_verification_failed")
    if not isinstance(incidents, list) or not isinstance(metrics, list):
        raise HarnessError("api_verification_failed")
    call_count = sum(row.get("call_count", 0) for row in metrics)
    if call_count < 1:
        raise HarnessError("api_verification_failed")
    detail = None
    if offline:
        target = message.get("incident_id")
        if not isinstance(target, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", target):
            raise HarnessError("child_protocol_invalid")
        if len(incidents) != 1 or incidents[0].get("id") != target or call_count != 7:
            raise HarnessError("api_verification_failed")
        detail_status, detail = request("/api/guardian/incidents/" + target, key)
        if detail_status != 200 or not isinstance(detail, dict) or detail.get("detector") != "cost_anomaly":
            raise HarnessError("api_verification_failed")
    summary_counts = verify_summary(summary, offline_incident=detail)
    return {"auth_denials_checked": 9, "incidents_returned": len(incidents), "metric_call_count": call_count, **access_counts, **summary_counts}


def add_step(report: dict, name: str, data=None):
    report["steps"].append({"name": name, "ok": True, "data": data or {}})
    print("[OK] " + name, flush=True)


def run_offline(args, report):
    key = secrets.token_urlsafe(32)
    env = isolated_env("guardian", {
        "MONGO_URL": "mongodb://127.0.0.1:1", "GUARDIAN_DB_NAME": "guardian_verify_offline",
        "GUARDIAN_API_KEY": key, "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "LANGFUSE_HOST": "http://127.0.0.1:1",
    })
    deadline = time.monotonic() + args.timeout
    with ChildProcess(args.guardian_python, "guardian", "guardian-offline", env, {}) as child:
        message = child.receive(deadline - time.monotonic())
        if message.get("event") != "ready" or message.get("source") != "synthetic" or message.get("persistence") != "mongomock":
            raise HarnessError("child_protocol_invalid")
        add_step(report, "synthetic source -> real worker/detector/store (mock persistence)")
        counts = verify_http(message, key, deadline, offline=True)
        add_step(report, "localhost Guardian HTTP incidents/metrics/summary and X-Guardian-Key", counts)


def run_live(args, report, runs: int):
    if not args.allow_live:
        raise HarnessError("configuration_invalid")
    founder = parse_env_file(Path(args.founder_env), "founder")
    guardian = parse_env_file(Path(args.guardian_env), "guardian")
    validate_live_env(founder, guardian)
    founder_python = python_path(args.founder_python)
    guardian_python = python_path(args.guardian_python)
    deadline = time.monotonic() + args.timeout
    receipts = []
    with ChildProcess(guardian_python, "guardian", "guardian-preflight", isolated_env("guardian", guardian), {}) as child:
        message = child.receive(deadline - time.monotonic())
        if message.get("event") != "completed" or message.get("source_api_version") != guardian.get("LANGFUSE_READ_API", "v2"):
            raise HarnessError("child_protocol_invalid")
        child.finish(deadline - time.monotonic())
    report["source_api_version"] = guardian.get("LANGFUSE_READ_API", "v2")
    add_step(report, "dedicated Guardian database preflight")
    for index in range(runs):
        with ChildProcess(founder_python, "founder", "founder", isolated_env("founder", founder), {"profile_index": index}) as child:
            receipt = child.receive(deadline - time.monotonic())
            child.finish(deadline - time.monotonic())
        if receipt.get("event") != "completed" or not re.fullmatch(r"[0-9a-f-]{36}", receipt.get("run_id", "")):
            raise HarnessError("child_protocol_invalid")
        try:
            datetime.fromisoformat(receipt["started_at"])
        except (KeyError, TypeError, ValueError):
            raise HarnessError("child_protocol_invalid") from None
        receipts.append({"run_id": receipt["run_id"], "started_at": receipt["started_at"]})
        add_step(report, "Founder workload " + str(index + 1) + " completed")
        if index < runs - 1:
            if time.monotonic() + args.pause_seconds >= deadline:
                raise HarnessError("child_timeout")
            time.sleep(args.pause_seconds)
    request = {"runs": receipts, "poll_timeout": min(args.poll_timeout, deadline - time.monotonic())}
    with ChildProcess(guardian_python, "guardian", "guardian-live", isolated_env("guardian", guardian), request) as child:
        message = child.receive(deadline - time.monotonic())
        if message.get("event") != "ready" or message.get("source") != "langfuse" or message.get("persistence") != "mongodb":
            raise HarnessError("child_protocol_invalid")
        if message.get("source_api_version") != report["source_api_version"]:
            raise HarnessError("child_protocol_invalid")
        add_step(report, "real grouped generations -> source mapping -> worker rollups", {"workloads": len(receipts)})
        counts = verify_http(message, guardian["GUARDIAN_API_KEY"], deadline, offline=False)
        add_step(report, "localhost Guardian HTTP incidents/metrics/summary and X-Guardian-Key", counts)


def positive_float(value):
    import math
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive number") from None
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return result


def bounded_runs(value):
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 20") from None
    if not 1 <= result <= 20:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 20")
    return result


def parser(baseline=False):
    result = argparse.ArgumentParser(description=(
        "Isolated Guardian verification. No arguments perform no work. "
        "Offline uses synthetic telemetry and mocked persistence; live makes paid model calls and test-database writes."
    ))
    modes = result.add_subparsers(dest="mode")
    if not baseline:
        offline = modes.add_parser("offline", help="synthetic source, mocked Mongo, real localhost HTTP; no external services")
        offline.add_argument("--guardian-python", required=True, help="Guardian environment's Python executable")
        offline.add_argument("--timeout", type=positive_float, default=45, help="total deadline in seconds (default: 45)")
        offline.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    live = modes.add_parser("live", help="explicit paid workload + dedicated Langfuse/Mongo verification")
    live.add_argument("--allow-live", action="store_true", required=True, help="authorize provider calls and dedicated test-project/database writes")
    for app in ("founder", "guardian"):
        live.add_argument("--" + app + "-python", required=True, help="this application's Python executable")
        live.add_argument("--" + app + "-env", required=True, help="dedicated test env file; application's normal .env is rejected")
    live.add_argument("--timeout", type=positive_float, default=3600 if baseline else 900, help="total deadline in seconds")
    live.add_argument("--poll-timeout", type=positive_float, default=120, help="maximum wait for Langfuse ingestion in seconds")
    live.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    if baseline:
        live.add_argument("--runs", type=bounded_runs, default=6, help="paid workload count, 1-20 (default: 6)")
        live.add_argument("--pause-seconds", type=positive_float, default=45)
    return result


def write_report(path: Path, report: dict):
    """Atomic report made only from known steps/counters/codes, never child logs."""
    path = path.resolve()
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as target:
            temp_path = Path(target.name)
            json.dump(report, target, indent=2)
            target.write("\n")
        temp_path.replace(path)
    except OSError:
        raise HarnessError("report_write_failed") from None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main(argv=None, baseline=False):
    cli = parser(baseline)
    args = cli.parse_args(argv)
    if args.mode is None:
        cli.print_help()
        return 0
    report = {
        "schema_version": 1, "mode": args.mode,
        "started_at": datetime.now(timezone.utc).isoformat(), "steps": [],
        "source": "synthetic" if args.mode == "offline" else "langfuse",
        "persistence": "mongomock" if args.mode == "offline" else "mongodb",
        "http_transport": "localhost_tcp",
        "limitations": [
            "No browser/UI or deployment/recovery validation.",
            "Offline synthetic-source verification is not live source end-to-end evidence."
            if args.mode == "offline" else
            "Real ingestion check only; an organic anomaly/incident and customer outcome are not guaranteed or asserted.",
        ],
    }
    code = 0
    try:
        if args.mode == "offline":
            run_offline(args, report)
        else:
            print("LIVE: provider calls and writes use the explicitly configured test environment.", flush=True)
            run_live(args, report, args.runs if baseline else 1)
    except HarnessError as error:
        report["failure_code"] = error.code
        print("[FAIL] " + error.code + ". See tools/README.md for remediation.", flush=True)
        code = 1
    except KeyboardInterrupt:
        report["failure_code"] = "interrupted"
        code = 130
    except Exception:
        report["failure_code"] = "child_failed"
        print("[FAIL] child_failed. See tools/README.md for remediation.", flush=True)
        code = 1
    report["ok"] = code == 0
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        write_report(args.report, report)
    except HarnessError:
        print("[FAIL] report_write_failed", flush=True)
        return 1
    return code
