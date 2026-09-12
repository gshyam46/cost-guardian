#!/usr/bin/env python
"""Real OpenAI SDKs -> owned localhost fixtures -> Guardian HTTP -> real Mongo.

No arguments print help using the standard library only. Execution requires an
explicit local replica and SDK Python interpreter. Provider and Guardian traffic
uses owned loopback listeners; no .env, provider account or customer data is read.
Synthetic credentials enter isolated children through stdin, never argv/reports.
Only random databases with this suite's ownership marker are removed.
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
import re
import shutil
import signal
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools" / "provider-fixtures"
CANARY = "synthetic-provider-private-π-content"
MODES = {"known", "stream", "missing", "early", "failure", "inconsistent"}


def dependencies():
    sys.path.insert(0, str(ROOT / "tools"))
    global capture, mongo, SYSTEM_KEYS
    import test_mongo_capture as capture
    import test_mongo_ledger as mongo
    from harness import SYSTEM_KEYS
    capture.load_dependencies()


def fixture_reply(api, mode, streaming):
    """Independent wire shapes; no dependency on adapter extraction helpers."""
    usage = {"input_tokens": 8, "input_tokens_details": {"cached_tokens": 3}, "output_tokens": 2,
             "output_tokens_details": {"reasoning_tokens": 1}, "total_tokens": 99 if mode == "inconsistent" else 10}
    if api == "responses":
        identifier = "resp_fixture_" + mode
        body = {"id": identifier, "object": "response", "created_at": 1700000000,
            "status": "failed" if mode == "failure" else "completed", "model": "synthetic-provider-model",
            "output": [{"id": "msg_fixture", "type": "message", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": CANARY, "annotations": []}]}],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "error": {"code": "server_error", "message": CANARY} if mode == "failure" else None,
            "usage": None if mode == "missing" else usage}
        if not streaming:
            return 200, body
        events = [{"type": "response.output_text.delta", "content_index": 0, "item_id": "msg_fixture",
                   "output_index": 0, "sequence_number": 1, "delta": CANARY},
                  {"type": "response.completed", "sequence_number": 2, "response": body}]
        return 200, "".join("event: " + row["type"] + "\ndata: " + json.dumps(row, ensure_ascii=False) + "\n\n" for row in events)
    if mode == "failure":
        return 400, {"error": {"message": CANARY, "type": "invalid_request_error", "code": "synthetic_failure"}}
    usage = {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 99 if mode == "inconsistent" else 10,
             "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens_details": {"reasoning_tokens": 1}}
    base = {"id": "chatcmpl_fixture_" + mode, "object": "chat.completion.chunk" if streaming else "chat.completion",
            "created": 1700000000, "model": "synthetic-provider-model"}
    if not streaming:
        return 200, {**base, "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": CANARY}}], "usage": None if mode == "missing" else usage}
    events = [{**base, "choices": [{"index": 0, "delta": {"content": CANARY}, "finish_reason": None}], "usage": None},
              {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": None},
              {**base, "choices": [], "usage": usage}]
    return 200, "".join("data: " + json.dumps(row, ensure_ascii=False) + "\n\n" for row in events) + "data: [DONE]\n\n"


class ProviderFixture:
    """Small owned HTTP server; retain only route/mode metadata, never content."""
    def __init__(self):
        self.server = None
        self.tasks = set()
        self.requests = []

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=16384)
        self.origin = "http://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout(10):
                raw = await reader.readuntil(b"\r\n\r\n")
                lines = raw.split(b"\r\n")
                method, path, _ = lines[0].decode("ascii").split(" ")
                headers = {key.lower(): value.strip() for key, value in (line.split(b":", 1) for line in lines[1:-2])}
                size = int(headers.get(b"content-length", b"0"))
                if method != "POST" or path not in ("/v1/responses", "/v1/chat/completions") or not 0 < size <= 8192:
                    return
                if headers.get(b"authorization") != b"Bearer synthetic-provider-key": return
                body = json.loads(await reader.readexactly(size))
                mode = body.get("model", "").removeprefix("fixture-")
                streaming = body.get("stream", False)
                if mode not in MODES or type(streaming) is not bool: return
                api = "responses" if path.endswith("responses") else "chat_completions"
                if api == "chat_completions" and streaming and body.get("stream_options") != {"include_usage": True}: return
                self.requests.append({"api": api, "mode": mode, "stream": streaming})
                status, reply = fixture_reply(api, mode, streaming)
                payload = (reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)).encode()
                kind = b"text/event-stream" if isinstance(reply, str) else b"application/json"
                if isinstance(reply, str):
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: " + kind + b"\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                    marker = payload.find("π".encode())
                    cuts = sorted({0, 1, 17, marker + 1, len(payload) // 2, len(payload)})
                    for start, stop in zip(cuts, cuts[1:]):
                        chunk = payload[start:stop]
                        writer.write(format(len(chunk), "x").encode() + b"\r\n" + chunk + b"\r\n")
                        await writer.drain()
                        await asyncio.sleep(0)
                    writer.write(b"0\r\n\r\n")
                else:
                    writer.write(b"HTTP/1.1 " + str(status).encode() + b" Synthetic\r\nContent-Type: " + kind
                        + b"\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except ConnectionError: pass
            self.tasks.discard(task)


async def stop_owned_process(process):
    """Reap the owned SDK process family, including Windows venv launchers."""
    if process.returncode is not None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
        await asyncio.to_thread(subprocess.run, [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    await asyncio.wait_for(process.wait(), 5)


async def run_owned_child(command, data, environment, *, timeout=30):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=environment, cwd=ROOT, **options)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(data), timeout)
        return process.returncode, stdout, stderr
    finally:
        if process.returncode is None:
            cleanup = asyncio.create_task(stop_owned_process(process))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise


async def sdk_child(language, api, configured, token, provider_origin, test_mode, sdk_python, node):
    config = {"origin": configured.public_url, "token": token, "provider_origin": provider_origin,
              "module_dir": str(ROOT / "examples" / "native-capture"), "api": api,
              "canary": CANARY, "test_mode": test_mode}
    environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    command = [sdk_python, "-I", str(FIXTURES / "python_child.py"), "--run-fixture"] if language == "python" \
        else [node, str(FIXTURES / "node_child.mjs"), "--run-fixture"]
    returncode, stdout, stderr = await run_owned_child(command, json.dumps(config).encode(), environment)
    mongo.check(len(stdout) <= 16384 and not stderr, language + "_provider_child_unexpected_output")
    mongo.check(token.encode() not in stdout and CANARY.encode() not in stdout, "provider_child_private_output")
    result = json.loads(stdout)
    if returncode or result.get("status") != "passed":
        phase = result.get("phase")
        raise mongo.CheckFailed(language + "_" + api + "_" + (phase if phase in MODES | {"configuration", "flush", "close"} else "failed"))
    stats = result["stats"]
    expected = 1 if test_mode else 6
    mongo.check(stats["enqueued_events"] == stats["confirmed_events"] == expected and stats["pending_events"] == 0
        and stats["unconfirmed_events"] == 0 and stats["closed"] and not stats["transport_active"], "sdk_exporter_not_confirmed_or_closed")
    mongo.check(all(isinstance(result.get(key), str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", result[key])
                    for key in ("runtime_version", "sdk_version")), "invalid_sdk_version_report")
    return result


async def pipeline(f, language, api, sdk_python, node):
    clock = asyncio.get_running_loop().time
    started = clock()
    phases = {}
    evidence = {"phase": "setup", "phase_seconds": phases}
    f.suite.details[language + "_" + api] = evidence

    def mark(phase):
        phases[phase] = round(clock() - started, 3)
        evidence["phase"] = phase

    suffix = "py" if language == "python" else "mjs"
    sources = [ROOT / "examples" / "native-capture" / (name + "." + suffix)
               for name in ("guardian_capture", "guardian_exporter", "guardian_openai")]
    source_hashes = lambda: {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in sources}
    hashes = source_hashes()
    with patch.dict(os.environ, {"GUARDIAN_SLACK_WEBHOOK_URL": ""}):
        async with capture.http_api(f) as (configured, client), ProviderFixture() as provider:
            store = capture.IdentityStore(f.db, configured)
            session = await store.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
            client.cookies.set(configured.session_cookie, session)
            response = await client.get("/api/guardian/access")
            mongo.check(response.status_code == 200, "sdk_owner_access_failed")
            headers = {"Origin": configured.ui_origin, "X-Guardian-CSRF": response.json()["csrf_token"]}
            from uuid import uuid4
            response = await client.post("/api/guardian/ingestion-keys", headers=headers,
                json={"label": "Synthetic SDK proof", "expires_in_days": 7, "request_id": str(uuid4())})
            mongo.check(response.status_code == 201, "sdk_owner_key_creation_failed")
            token = response.json()["token"]
            mark("test_sdk_started")
            await sdk_child(language, api, configured, token, provider.origin, True, sdk_python, node)
            mark("test_sdk_completed")
            mongo.check(await f.db.guardian_capture_inbox.count_documents({}) == 0
                        and await f.db.guardian_incidents.count_documents({}) == 0, "sdk_test_polluted_production")
            original = capture.CaptureService.ingest
            attempts = []

            async def lose_first_ack(service, sent_token, batch):
                result = await original(service, sent_token, batch)
                digest = capture.digest([capture.safe_metric(metric) for metric in batch.metrics])
                attempts.append((batch.batch_id, digest, result["replayed"]))
                if len(attempts) == 1:
                    error = capture.CaptureError(503, "capture_unavailable")
                    error.headers["Retry-After"] = "1"
                    raise error
                return result

            with patch.object(capture.CaptureService, "ingest", lose_first_ack):
                mark("production_sdk_started")
                result = await sdk_child(language, api, configured, token, provider.origin, False, sdk_python, node)
                mark("production_sdk_completed")
            first = [row for row in attempts if row[0] == attempts[0][0]]
            mongo.check(len(first) == 2 and first[0][:2] == first[1][:2] and [row[2] for row in first] == [False, True],
                        "sdk_export_retry_changed_batch_or_receipt")
            mongo.check(await f.db.guardian_capture_inbox.count_documents({}) == 6, "sdk_retry_duplicated_inbox")
            await f.ledger.release(f.lease)
            await capture.poll_direct_once(f.db, configured)
            mark("worker_completed")
            response = await client.get("/api/guardian/live/runs/" + result["trace_id"])
            mongo.check(response.status_code == 200 and len(response.json()["calls"]) == 6, "sdk_run_missing_calls")
            run = response.json()
            calls = {row["agent_name"]: row for row in run["calls"]}
            mongo.check(len({row["id"] for row in run["calls"]}) == 6 and all(row["cost_usd"] is None for row in run["calls"])
                        and run["cost_usd"] is None, "sdk_identity_duplicate_or_invented_cost")
            for mode in ("known", "stream"):
                row = calls["sdk-" + mode]
                mongo.check(row["total_tokens"] == 10 and row["status"] == "success", "sdk_known_usage_or_mutation_snapshot_wrong")
            for mode in ("missing", "early", "inconsistent"):
                mongo.check(calls["sdk-" + mode]["total_tokens"] is None, "sdk_missing_or_invalid_usage_became_known")
            mongo.check(calls["sdk-early"]["status"] == "unknown" and calls["sdk-failure"]["status"] == "error",
                        "sdk_terminal_or_early_close_status_incorrect")
            expected_known = 3 if api == "responses" else 2
            response = await client.get("/api/guardian/metrics")
            metrics = response.json()
            mongo.check(response.status_code == 200 and sum(row["call_count"] for row in metrics) == 6
                        and sum(row["cost_unknown_count"] for row in metrics) == 6
                        and sum(row["known_total_tokens"] for row in metrics) == expected_known * 10,
                        "sdk_usage_metrics_did_not_reconcile")
            response = await client.get("/api/guardian/incidents")
            mongo.check(response.status_code == 200 and len(response.json()) == 1, "sdk_error_incident_missing_or_duplicated")
            incident = response.json()[0]
            response = await client.post("/api/guardian/incidents/" + incident["id"] + "/resolve", headers=headers)
            mongo.check(response.status_code == 200 and response.json()["status"] == "resolved", "sdk_incident_resolve_failed")
            await capture.poll_direct_once(f.db, configured)
            response = await client.get("/api/guardian/incidents/" + incident["id"])
            mongo.check(response.status_code == 200 and response.json()["status"] == "resolved", "sdk_idle_replay_reopened_incident")
            for name in await f.db.list_collection_names():
                stored = json.dumps(await f.db[name].find({}).to_list(200), default=str, ensure_ascii=False)
                mongo.check(CANARY not in stored and token not in stored and "synthetic-provider-key" not in stored,
                            "sdk_private_content_or_credential_persisted")
            mongo.check(len(provider.requests) == 7 and sum(row["stream"] for row in provider.requests) == 2,
                        "unexpected_or_retried_provider_requests")
            mongo.check(source_hashes() == hashes, "provider_adapter_changed_during_case")
            mark("completed")
            evidence.update({"sdk_version": result["sdk_version"], "runtime_version": result["runtime_version"],
                "provider_transport": "localhost_http_json_and_fragmented_sse", "guardian_transport": "localhost_http",
                "production_events": 6, "test_events": 1, "known_total_tokens": expected_known * 10, "cost_unknown_events": 6,
                "error_incidents": 1, "resolved": True, "committed_receipt_replay": True,
                "consumer_mutation_did_not_change_usage": True, "raw_content_absent": True,
                "provider_requests": 7, "paid_provider_calls": 0, "source_sha256": hashes})


async def run_case(suite, name, test):
    # Two isolated SDK children each have a 30s deadline; the shared ledger
    # fault suite's 45s budget cannot contain both plus HTTP/worker checks.
    started = asyncio.get_running_loop().time()
    try:
        async with suite.fixture(name) as fixture:
            await asyncio.wait_for(test(fixture), timeout=90)
        result = {"name": name, "status": "passed"}
    except Exception as error:
        result = {"name": name, "status": "failed", "error_type": type(error).__name__}
        if isinstance(error, mongo.CheckFailed): result["code"] = str(error)
    result["duration_seconds"] = round(asyncio.get_running_loop().time() - started, 3)
    suite.results.append(result)


async def run_suite(uri, sdk_python, node):
    suite = mongo.Suite(uri)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        for language in ("python", "node"):
            for api in ("responses", "chat_completions"):
                await run_case(suite, language + "_" + api + "_actual_sdk_pipeline",
                    lambda f, lang=language, surface=api: pipeline(f, lang, surface, sdk_python, node))
        failed = sum(row["status"] != "passed" for row in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
            "finished_at": datetime.now(timezone.utc).isoformat(), "passed": len(suite.results) - failed, "failed": failed,
            "cleanup_complete": not suite.owned, "duration_seconds": round(asyncio.get_running_loop().time() - started, 3),
            "tests": suite.results, "evidence": suite.details}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only guardian-r102 replica URI")
    parser.add_argument("--sdk-python", help="Explicit interpreter containing the OpenAI Python fixture dependency")
    parser.add_argument("--node", default="node", help="Node interpreter; isolated fixture SDK must be installed")
    parser.add_argument("--report", help="Optional safe JSON artifact under tools/reports")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    report = None
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import test_mongo_ledger as safe_mongo
        uri = safe_mongo.validate_url(args.mongo_url)
        if args.report:
            candidate = Path(args.report).resolve()
            safe_mongo.check(candidate.is_relative_to((ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
            report = candidate
        safe_mongo.check(bool(args.sdk_python), "sdk_python_required")
        sdk_python = shutil.which(args.sdk_python)
        safe_mongo.check(sdk_python is not None, "sdk_python_missing")
        node = shutil.which(args.node)
        safe_mongo.check(node is not None, "node_interpreter_missing")
        safe_mongo.check((FIXTURES / "node_modules" / "openai" / "package.json").is_file(), "node_sdk_fixture_missing")
        dependencies()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("guardian.incident_engine").setLevel(logging.WARNING)
        result = asyncio.run(run_suite(uri, sdk_python, node))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if "safe_mongo" in locals() and isinstance(error, safe_mongo.CheckFailed): result["code"] = str(error)
    rendered = json.dumps(result, indent=2)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
