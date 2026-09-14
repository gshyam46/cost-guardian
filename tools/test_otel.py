#!/usr/bin/env python
"""Installed OTel/OpenInference bridge -> owned collector -> real worker.

No arguments print stdlib-only help. Requires an explicit local wheel, pinned
dependency interpreters and isolated localhost replica. No package download,
developer .env, real provider call or user preview database is used. Authentication
is a synthetic identity-store fixture followed by the actual app-key API.
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
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/otel-fixtures/application.py"
CANARY = "synthetic-provider-private-\u03c0-content"
PHASES = ("programmatic", "openai", "founder", "langchain")


class VerificationFailed(Exception):
    """Fixed test error codes, never provider exceptions or request content."""


def check(condition, code):
    if not condition:
        raise VerificationFailed(code)


def environment():
    sys.path.insert(0, str(ROOT / "tools"))
    from harness import SYSTEM_KEYS
    value = {key: item for key, item in os.environ.items() if key.upper() in SYSTEM_KEYS}
    value.update(PYTHON_DOTENV_DISABLED="1", PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
        PIP_DISABLE_PIP_VERSION_CHECK="1", LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_TELEMETRY="False",
        DO_NOT_TRACK="1", LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="",
        LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")
    return value


def command(arguments, *, cwd, env=None, timeout=60):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(arguments, cwd=cwd, env=env or environment(), stdin=subprocess.DEVNULL,
        capture_output=True, timeout=timeout, **options)
    check(len(result.stdout) + len(result.stderr) <= 65536, "child_output_unbounded")
    return result


def install(wheel, sdk_python, dependencies, work):
    venv = work / "venv"
    created = command([sdk_python, "-I", "-m", "venv", "--without-pip", str(venv)], cwd=work)
    check(created.returncode == 0, "temporary_venv_creation_failed")
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = command([sdk_python, "-I", "-m", "pip", "--python", str(python), "install", "--no-index",
        "--no-deps", "--disable-pip-version-check", str(wheel)], cwd=work)
    check(installed.returncode == 0, "offline_wheel_installation_failed")
    query_code = "import json,sysconfig;print(json.dumps(sysconfig.get_path('purelib')))"
    query = command([str(python), "-I", "-c", query_code], cwd=work)
    check(query.returncode == 0, "temporary_site_unavailable")
    destination = Path(json.loads(query.stdout)).resolve()
    check(destination.is_relative_to(venv.resolve()), "temporary_site_scope_invalid")
    locations = []
    for interpreter in [sdk_python, *dependencies]:
        query = command([interpreter, "-I", "-c", query_code], cwd=work)
        check(query.returncode == 0, "dependency_site_unavailable")
        location = Path(json.loads(query.stdout)).resolve()
        check(location.is_dir() and location.name == "site-packages", "dependency_site_invalid")
        if location not in locations:
            locations.append(location)
    (destination / "explicit_fixture_dependencies.pth").write_text("\n".join(str(path) for path in locations) + "\n", encoding="utf8")
    console = venv / ("Scripts/sillage-run.exe" if os.name == "nt" else "bin/sillage-run")
    check(console.is_file(), "installed_console_missing")
    target = work / "original_otel_application.py"
    shutil.copyfile(FIXTURE, target)
    return python, console, target


def cli_checks(console, work, phases):
    env = environment()
    env.update(SILLAGE_URL="http://127.0.0.1:9", SILLAGE_ALLOW_LOCAL="true", SILLAGE_SERVICE_NAME="offline-otel-check",
        SILLAGE_INGEST_KEY="cg_ingest_" + "0" * 32 + "_" + "a" * 43)
    evidence = {}
    for phase in phases:
        if phase == "programmatic":
            continue
        layer = "litellm" if phase == "founder" else phase
        result = command([str(console), "--instrumentation", "openinference", "--instrumentors", layer, "--check"], cwd=work, env=env)
        check(result.returncode == 0, layer + "_compatibility_check_failed")
        check(env["SILLAGE_INGEST_KEY"].encode() not in result.stdout + result.stderr, "offline_check_leaked_key")
        parsed = json.loads(result.stdout)
        check(parsed.get("connected") is False and parsed.get("collector_checked") is False,
              "offline_check_claimed_connection")
        check(parsed.get("instrumentation_ready") is True and parsed.get("instrumentors_selected") == [layer],
              "offline_check_selected_wrong_layer")
        evidence[layer] = {"ready": True, "collector_checked": False}
    return evidence


async def application(python, console, target, work, config, phase):
    env = environment()
    env.update(SILLAGE_URL=config["collector"], SILLAGE_INGEST_KEY=config["token"], SILLAGE_ALLOW_LOCAL="true",
               SILLAGE_SERVICE_NAME="otel-" + phase)
    arguments = [str(python), "-I", str(target), phase]
    if phase not in ("programmatic", "replay"):
        layer = "litellm" if phase == "founder" else phase
        arguments = [str(console), "--instrumentation", "openinference", "--instrumentors", layer,
                     "--", "python", str(target), phase]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = await asyncio.create_subprocess_exec(*arguments, cwd=work, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(config).encode()), 80)
    finally:
        if process.returncode is None:
            from test_mongo_providers import stop_owned_process
            await stop_owned_process(process)
    check(len(stdout) + len(stderr) <= 65536, "application_output_unbounded")
    check(all(value.encode() not in stdout + stderr for value in (config["token"], CANARY, "synthetic-provider-key")),
          "application_private_output")
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


async def pipeline(fixture, python, console, target, work, phase):
    import test_mongo_capture as capture
    from test_mongo_providers import ProviderFixture
    founder = ROOT / "apps/founder-app/backend/services/llm_fallback.py"
    founder_hash = hashlib.sha256(founder.read_bytes()).hexdigest()
    async with capture.http_api(fixture) as (configured, client), ProviderFixture() as provider:
        identity = capture.IdentityStore(fixture.db, configured)
        session = await identity.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
        client.cookies.set(configured.session_cookie, session)
        access = await client.get("/api/guardian/access")
        check(access.status_code == 200, "fixture_owner_access_failed")
        response = await client.post("/api/guardian/ingestion-keys",
            headers={"Origin": configured.ui_origin, "X-Guardian-CSRF": access.json()["csrf_token"]},
            json={"label": "OpenTelemetry fixture", "expires_in_days": 7, "request_id": str(uuid4())})
        check(response.status_code == 201, "fixture_app_key_creation_failed")
        config = {"collector": configured.public_url, "provider": provider.origin, "token": response.json()["token"],
            "repository": str(ROOT), "work": str(work), "founder_source": str(founder.parents[1]),
            "legacy_run": "otel-founder-" + uuid4().hex}
        result = await application(python, console, target, work, config, phase)
        await fixture.ledger.release(fixture.lease)
        await capture.poll_direct_once(fixture.db, configured)
        response = await client.get("/api/guardian/live")
        check(response.status_code == 200, "live_read_failed")
        live = response.json()
        calls = live["calls"]
        check(all(row["cost_usd"] is None for row in calls), "price_was_inferred")
        evidence = {"application": result, "captured_calls": len(calls), "paid_provider_calls": 0,
                    "provider_requests": len(provider.requests)}
        if phase == "programmatic":
            expected = result["expected"]
            check(len(calls) == 4 and len(live["runs"]) == 1, "programmatic_call_or_run_count_wrong")
            actual = {row["id"]: row for row in calls}
            check(all(all(actual[row["id"]].get(key) == value for key, value in row.items()) for row in expected),
                  "trace_parent_agent_measurements_not_preserved")
            response = await client.get("/api/guardian/live/runs/" + expected[0]["trace_id"])
            run = response.json()
            check(len(run["calls"]) == 4 and run["workflow_status"] == "unknown" and run["latency_ms"] is None,
                  "run_invented_workflow_facts")
            replay = await application(python, console, target, work, config, "replay")
            check(await fixture.db.guardian_capture_inbox.count_documents({}) == 5, "duplicate_delivery_added_contribution")
            await capture.poll_direct_once(fixture.db, configured)
            row = await fixture.db.guardian_observations.find_one({"metric.observation_id": replay["replayed_id"]})
            check(row and row["state"] == "conflicted", "changed_span_not_quarantined")
            response = await client.get("/api/guardian/live/runs/" + replay["replayed_trace"])
            run = response.json()
            changed = next(call for call in run["calls"] if call["id"] == replay["replayed_id"])
            check(run["call_count"] == 4 and changed["total_tokens"] is None and changed["status"] == "unknown",
                  "conflicted_span_still_trusted")
            evidence.update(replay_once=True, changed_same_span_quarantined=True,
                            parent_references_exposed=True, workflow_outcome_unknown=True)
        elif phase == "openai":
            matrix = []
            for operation in result["operations"]:
                rows = [row for row in calls if row["agent_name"] == operation["agent"]]
                check(len(rows) <= 1, "nested_openai_duplicate_call")
                mode = operation["mode"]
                if mode in ("known", "stream", "failure"):
                    check(len(rows) == 1, operation["agent"] + "_missing_terminal_call")
                if rows and mode in ("known", "stream"):
                    check(rows[0]["total_tokens"] == 10, operation["agent"] + "_usage_lost")
                if rows and mode in ("early", "cancel"):
                    check(rows[0]["status"] != "success", operation["agent"] + "_interruption_claimed_success")
                if rows and mode == "failure":
                    check(rows[0]["status"] != "success", operation["agent"] + "_failure_claimed_success")
                matrix.append({**operation, "capture": "captured" if rows else "not_captured",
                               "status": rows[0]["status"] if rows else None,
                               "tokens": rows[0]["total_tokens"] if rows else None})
            check(sum(row["capture"] == "captured" for row in matrix) == len(calls), "unattributed_openai_call")
            check(len(provider.requests) == 16, "openai_provider_requests_changed")
            evidence["matrix"] = matrix
        elif phase == "founder":
            check(len(calls) == 10 and len(live["runs"]) == 1, "founder_nested_duplicate_or_missing_attempt")
            check({row["agent_name"] for row in calls} == set(result["agents"]), "founder_agent_context_lost")
            check({row["trace_id"] for row in calls} == {result["trace_id"]}, "founder_workflow_mapping_wrong")
            check(sum(row["status"] == "error" for row in calls) == 5, "founder_error_attempts_lost")
            check(sum(row["total_tokens"] or 0 for row in calls) == 50, "founder_usage_wrong")
            check(len(provider.requests) == 10, "founder_provider_attempts_changed")
            check(hashlib.sha256(founder.read_bytes()).hexdigest() == founder_hash, "original_founder_source_changed")
            evidence.update(original_source_sha256=founder_hash, agent_names_preserved=True,
                legacy_run_mapped_to_actual_otel_trace=True, nested_provider_not_double_counted=True,
                statuses={name: sum(row["status"] == name for row in calls) for name in ("success", "error", "unknown")})
        elif phase == "langchain":
            check(len(calls) == 2 and len(live["runs"]) == 1, "framework_grouping_or_llm_count_wrong")
            check(all(row["parent_observation_id"] for row in calls), "framework_parent_context_lost")
            check({row["agent_name"] for row in calls} == {"langchain-workflow"}, "framework_agent_context_lost")
            check(all(row["total_tokens"] is None for row in calls), "framework_usage_was_inferred")
            evidence.update(framework_children_grouped=True, opaque_sdk_inside_runnable_not_claimed=True,
                            non_llm_calls_not_counted=True)
        response = await client.get("/api/guardian/capture")
        check(response.json()["status"]["pending_events"] == 0, "collector_not_drained")
        for name in await fixture.db.list_collection_names():
            stored = json.dumps(await fixture.db[name].find({}).to_list(500), default=str, ensure_ascii=False)
            check(all(value not in stored for value in (CANARY, config["token"], session, "synthetic-provider-key")),
                  "private_content_in_numeric_storage")
        evidence.update(raw_content_absent=True, authentication="synthetic_identity_store_then_actual_key_api",
                        collector="actual_loopback_http", worker="actual_direct_worker")
        return evidence


async def run_suite(args, work, python, console, target):
    import test_mongo_capture as capture
    import test_mongo_ledger as mongo
    capture.load_dependencies()
    logging.disable(logging.CRITICAL)
    suite = mongo.Suite(args.mongo_url)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    evidence = {}
    try:
        version = await suite.preflight()
        for phase in args.phases:
            async with suite.fixture("otel_" + phase) as fixture:
                evidence[phase] = await asyncio.wait_for(pipeline(fixture, python, console, target, work, phase), 150)
        check(not suite.owned, "owned_database_cleanup_incomplete")
        return {"status": "passed", "mongo_version": version, "phases": evidence,
            "database_cleanup_complete": True, "duration_seconds": round(asyncio.get_running_loop().time() - started, 3)}
    except Exception as error:
        error.completed_phases = evidence
        error.database_cleanup_complete = not suite.owned
        raise
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", help="Explicit local wheel; never downloaded")
    parser.add_argument("--sdk-python", help="Interpreter with pinned OTel/OpenInference dependencies and pip")
    parser.add_argument("--dependency-python", action="append", default=[], help="Additional explicit third-party SDK environment; read-only")
    parser.add_argument("--mongo-url", help="Explicit isolated localhost guardian-r102 replica")
    parser.add_argument("--phases", nargs="+", choices=PHASES, default=list(PHASES))
    parser.add_argument("--report", help="Optional JSON evidence under tools/reports")
    args = parser.parse_args(argv)
    if not args.wheel:
        parser.print_help()
        return 0
    report, result = None, {"status": "failed"}
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from test_mongo_ledger import validate_url
        args.mongo_url = validate_url(args.mongo_url)
        wheel = Path(args.wheel).resolve()
        check(wheel.is_file() and wheel.suffix == ".whl", "local_wheel_required")
        sdk = shutil.which(args.sdk_python or "")
        check(sdk is not None, "sdk_python_required")
        dependencies = [shutil.which(value) for value in args.dependency_python]
        check(all(dependencies), "dependency_python_required")
        check(len(args.phases) == len(set(args.phases)), "duplicate_phases_not_allowed")
        if args.report:
            candidate = Path(args.report).resolve()
            check(candidate.is_relative_to((ROOT / "tools/reports").resolve()), "report_path_outside_reports")
            report = candidate
        with tempfile.TemporaryDirectory(prefix="sillage-otel-verification-") as temporary:
            work = Path(temporary).resolve()
            check(not work.is_relative_to(ROOT), "temporary_environment_inside_checkout")
            python, console, target = install(wheel, sdk, dependencies, work)
            local = cli_checks(console, work, args.phases)
            result = asyncio.run(run_suite(args, work, python, console, target))
            result.update(cli=local, wheel_name=wheel.name, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                          installed_outside_checkout=True)
        result["temporary_environment_removed"] = True
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, VerificationFailed) or type(error).__name__ == "CheckFailed":
            result["code"] = str(error)
        if type(getattr(error, "completed_phases", None)) is dict:
            result["completed_phases"] = error.completed_phases
            result["database_cleanup_complete"] = error.database_cleanup_complete
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
