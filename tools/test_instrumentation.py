#!/usr/bin/env python
"""Installed wheel/launcher -> original SDKs -> local collector -> real worker.

No arguments print stdlib-only help. Requires an explicit wheel, SDK interpreter
and owned localhost test replica. The wheel is installed outside the checkout in
a fresh temporary venv. Existing environments and user preview data are untouched.
Authentication is a synthetic identity-store fixture, not a browser/OIDC proof.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/instrumentation-fixtures/application.py"
CANARY = "synthetic-provider-private-\u03c0-content"


class VerificationFailed(Exception):
    """Test-authored error codes only; never expose application exception text."""


def check(condition, code):
    if not condition:
        raise VerificationFailed(code)


def environment():
    # Importing this module or printing help must not load application packages.
    sys.path.insert(0, str(ROOT / "tools"))
    from harness import SYSTEM_KEYS
    result = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
    result.update(PYTHON_DOTENV_DISABLED="1", PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
        PIP_DISABLE_PIP_VERSION_CHECK="1", LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_TELEMETRY="False",
        DO_NOT_TRACK="1", LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="")
    return result


def command(arguments, *, cwd, env=None, timeout=45):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    completed = subprocess.run(arguments, cwd=cwd, env=env or environment(), stdin=subprocess.DEVNULL,
        capture_output=True, timeout=timeout, **options)
    check(len(completed.stdout) + len(completed.stderr) <= 65536, "child_output_unbounded")
    return completed


def check_environment():
    env = environment()
    env.update(SILLAGE_URL="http://127.0.0.1:9", SILLAGE_INGEST_KEY="cg_ingest_" + "0" * 32 + "_" + "a" * 43,
        SILLAGE_ALLOW_LOCAL="true", SILLAGE_SERVICE_NAME="installed-fixture")
    return env


def install(wheel, sdk_python, work):
    venv = work / "venv"
    created = command([sdk_python, "-I", "-m", "venv", "--without-pip", str(venv)], cwd=work)
    check(created.returncode == 0, "temporary_venv_creation_failed")
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = command([sdk_python, "-I", "-m", "pip", "--python", str(python), "install",
        "--no-index", "--no-deps", "--disable-pip-version-check", str(wheel)], cwd=work)
    check(installed.returncode == 0, "offline_wheel_installation_failed")
    console = venv / ("Scripts/sillage-run.exe" if os.name == "nt" else "bin/sillage-run")
    check(console.is_file(), "installed_console_entrypoint_missing")
    # A real fresh installation has no model SDK. Valid endpoint/key syntax
    # must not misleadingly pass the readiness check before adapters exist.
    missing = command([str(console), "--check"], cwd=work, env=check_environment())
    check(missing.returncode == 3, "missing_sdk_check_did_not_fail")
    parsed = json.loads(missing.stdout)
    check(parsed.get("configuration") == "valid" and parsed.get("instrumentation_ready") is False
        and parsed.get("connected") is False, "missing_sdk_check_claimed_readiness")
    # Reuse explicit third-party dependencies read-only. No app package or source
    # directories enter the temporary environment until the Founder-only fixture.
    query = command([sdk_python, "-I", "-c", "import json,sysconfig;print(json.dumps(sysconfig.get_path('purelib')))"], cwd=work)
    check(query.returncode == 0, "sdk_dependency_path_unavailable")
    dependencies = Path(json.loads(query.stdout)).resolve()
    check(dependencies.is_dir() and dependencies.name == "site-packages", "sdk_dependency_path_invalid")
    query = command([str(python), "-I", "-c", "import json,sysconfig;print(json.dumps(sysconfig.get_path('purelib')))"], cwd=work)
    destination = Path(json.loads(query.stdout)).resolve()
    check(destination.is_relative_to(venv.resolve()), "temporary_site_scope_invalid")
    (destination / "fixture_sdk_dependencies.pth").write_text(str(dependencies) + "\n", encoding="utf-8")
    target = work / "original_application.py"
    shutil.copyfile(FIXTURE, target)
    return python, console, target


def cli_checks(python, console, work):
    env = check_environment()
    versions = command([str(console), "--check"], cwd=work, env=env)
    check(versions.returncode == 0, "offline_launcher_check_failed")
    check(env["SILLAGE_INGEST_KEY"].encode() not in versions.stdout + versions.stderr, "offline_check_leaked_key")
    parsed = json.loads(versions.stdout)
    # A locally valid configuration cannot claim receipt from the closed port.
    check(parsed.get("connected") is not True, "offline_check_claimed_connection")
    check(parsed.get("instrumentation_ready") is True, "supported_sdk_not_ready")
    target = work / "exit_application.py"
    target.write_text("import sys\nassert sys.argv[1:] == ['one argument', '--literal']\nraise SystemExit(7)\n", encoding="utf-8")
    exited = command([str(console), "--", "python", str(target), "one argument", "--literal"], cwd=work, env=env)
    check(exited.returncode == 7, "launcher_changed_arguments_or_exit_code")
    invalid = {**env, "GUARDIAN_INGEST_KEY": "different-synthetic-key"}
    rejected = command([str(console), "--check"], cwd=work, env=invalid)
    check(rejected.returncode != 0, "conflicting_credentials_not_rejected")
    return {"console_entrypoint": True, "offline_check": True, "arguments_preserved": True,
        "exit_code_preserved": True, "conflicting_configuration_rejected": True,
        "missing_sdk_exit_3": True, "supported_sdk_ready": True}


async def application(console, target, work, config, token, phase):
    env = environment()
    env.update(SILLAGE_URL=config["collector"], SILLAGE_INGEST_KEY=token, SILLAGE_ALLOW_LOCAL="true",
        SILLAGE_SERVICE_NAME="installed-fixture", OPENAI_API_KEY="synthetic-provider-key",
        OPENAI_API_BASE=config["provider"] + "/v1")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = await asyncio.create_subprocess_exec(str(console), "--", "python", str(target), phase,
        cwd=work, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, **options)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(config).encode()), 55)
    finally:
        if process.returncode is None:
            from test_mongo_providers import stop_owned_process
            await stop_owned_process(process)
    check(len(stdout) + len(stderr) <= 65536, "application_output_unbounded")
    check(all(value.encode() not in stdout + stderr for value in (token, CANARY, "synthetic-provider-key")),
        "application_output_contains_private_canary")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise VerificationFailed(phase + "_application_protocol_invalid") from None
    if process.returncode != 0 or result.get("status") != "passed":
        kind = result.get("error_type")
        check(kind in {"AssertionError", "TypeError", "AttributeError", "RuntimeError", "ModuleNotFoundError", "ValueError"},
            phase + "_application_failed")
        lines = result.get("fixture_lines", [])
        suffix = "_lines_" + "_".join(lines) if lines and all(type(line) is str and line.isdecimal() for line in lines) else ""
        raise VerificationFailed(phase + "_application_" + kind + suffix)
    return result


async def pipeline(fixture, console, target, work):
    import test_mongo_capture as capture
    from test_mongo_providers import ProviderFixture
    evidence = {}
    source = ROOT / "apps/founder-app/backend/services/llm_fallback.py"
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    async with capture.http_api(fixture) as (configured, client), ProviderFixture() as provider:
        # Clearly scoped test fixture identity. Browser/OIDC behavior is covered
        # by test_deployment.py and is not inferred from this store-created token.
        identity = capture.IdentityStore(fixture.db, configured)
        owner_session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
        client.cookies.set(configured.session_cookie, owner_session)
        response = await client.get("/api/guardian/access")
        check(response.status_code == 200, "fixture_owner_access_failed")
        headers = {"Origin": configured.ui_origin, "X-Guardian-CSRF": response.json()["csrf_token"]}
        response = await client.post("/api/guardian/ingestion-keys", headers=headers,
            json={"label": "Installed wheel fixture", "expires_in_days": 7, "request_id": str(uuid4())})
        check(response.status_code == 201, "fixture_ingestion_key_creation_failed")
        token = response.json()["token"]
        config = {"collector": configured.public_url, "provider": provider.origin,
            "repository": str(ROOT), "work": str(work), "founder_source": str(ROOT / "apps/founder-app/backend"),
            "trace_id": "founder-installed-" + uuid4().hex}
        evidence["openai"] = await application(console, target, work, config, token, "openai")
        check(await fixture.db.guardian_capture_inbox.count_documents({}) == 25, "openai_capture_count_not_25")
        evidence["founder"] = await application(console, target, work, config, token, "founder")
        check(await fixture.db.guardian_capture_inbox.count_documents({}) == 35, "nested_provider_capture_or_missing_founder_call")
        await fixture.ledger.release(fixture.lease)
        await capture.poll_direct_once(fixture.db, configured)
        response = await client.get("/api/guardian/live/runs/" + config["trace_id"])
        check(response.status_code == 200, "founder_run_not_processed")
        calls = response.json()["calls"]
        check(len(calls) == 10 and len({call["id"] for call in calls}) == 10, "founder_attempt_identity_incorrect")
        check({call["agent_name"] for call in calls} == {"profile_analyst", "market_hunter", "fit_evaluator", "roadmap_architect", "tooling_advisor"},
            "original_founder_agent_metadata_lost")
        check(sum(call["status"] == "error" for call in calls) == 5
            and sum(call["status"] == "success" for call in calls) == 5, "founder_fallback_outcomes_wrong")
        check(all(call["cost_usd"] is None for call in calls), "founder_cost_inferred")
        response = await client.get("/api/guardian/metrics")
        rows = response.json()
        check(response.status_code == 200 and sum(row["call_count"] for row in rows) == 35, "processed_call_count_wrong")
        check(sum(row["error_count"] for row in rows) == 9, "processed_error_count_wrong")
        check(sum(row["unknown_status_count"] for row in rows) == 5, "interrupted_calls_claimed_success")
        check(sum(row["cost_unknown_count"] for row in rows) == 35, "unknown_cost_changed")
        check(sum(row["known_total_tokens"] for row in rows) == 230, "usage_snapshot_or_nested_tokens_wrong")
        response = await client.get("/api/guardian/capture")
        status = response.json()["status"]
        check(status["processed_events"] == 35 and status["pending_events"] == 0, "capture_processing_not_current")
        for name in await fixture.db.list_collection_names():
            stored = json.dumps(await fixture.db[name].find({}).to_list(400), default=str, ensure_ascii=False)
            check(all(value not in stored for value in (CANARY, token, owner_session, "synthetic-provider-key")),
                "numeric_storage_contains_private_content")
        check(len(provider.requests) == 26, "unexpected_provider_request_count")
        check(hashlib.sha256(source.read_bytes()).hexdigest() == source_before, "founder_source_changed_during_verification")
        evidence.update(events=35, provider_requests=26, known_tokens=230, errors=9, interrupted_unknown=5,
            cost_unknown=35, paid_provider_calls=0, original_founder_source_sha256=source_before,
            openai_structured_parse_and_stream_managers=True,
            provider_transport="owned_loopback_http_plus_mock_transport_parse_managers_and_cancellation",
            authentication="synthetic_identity_store_fixture_then_real_key_api", raw_content_absent=True,
            collector="actual_loopback_http", worker="actual_direct_worker", nested_capture_suppressed=True)
    return evidence


async def run_suite(args, work, console, target):
    import test_mongo_capture as capture
    import test_mongo_ledger as mongo
    capture.load_dependencies()
    logging.disable(logging.CRITICAL)
    suite = mongo.Suite(args.mongo_url)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        async with suite.fixture("installed_instrumentation") as fixture:
            evidence = await asyncio.wait_for(pipeline(fixture, console, target, work), 150)
        check(not suite.owned, "owned_database_cleanup_incomplete")
        return {"status": "passed", "mongo_version": version, "evidence": evidence,
            "database_cleanup_complete": True, "duration_seconds": round(asyncio.get_running_loop().time() - started, 3)}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", help="Explicit locally built .whl; never downloaded by this verifier")
    parser.add_argument("--sdk-python", help="Interpreter with pinned actual OpenAI/LiteLLM dependencies and pip")
    parser.add_argument("--mongo-url", help="Explicit isolated localhost guardian-r102 replica")
    parser.add_argument("--report", help="Optional JSON evidence under tools/reports")
    args = parser.parse_args(argv)
    if not args.wheel:
        parser.print_help()
        return 0
    report = None
    result = {"status": "failed"}
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from test_mongo_ledger import validate_url
        args.mongo_url = validate_url(args.mongo_url)
        wheel = Path(args.wheel).resolve()
        check(wheel.is_file() and wheel.suffix == ".whl", "local_wheel_required")
        sdk = shutil.which(args.sdk_python or "")
        check(sdk is not None, "sdk_python_required")
        if args.report:
            candidate = Path(args.report).resolve()
            check(candidate.is_relative_to((ROOT / "tools/reports").resolve()), "report_path_outside_reports")
            report = candidate
        with tempfile.TemporaryDirectory(prefix="sillage-installed-verification-") as temporary:
            work = Path(temporary).resolve()
            check(not work.is_relative_to(ROOT), "temporary_environment_inside_checkout")
            python, console, target = install(wheel, sdk, work)
            local = cli_checks(python, console, work)
            result = asyncio.run(run_suite(args, work, console, target))
            result.update(cli=local, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                wheel_name=wheel.name, installed_outside_checkout=True)
        result["temporary_environment_removed"] = True
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, VerificationFailed) or type(error).__name__ == "CheckFailed":
            result["code"] = str(error)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
