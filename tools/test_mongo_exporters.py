#!/usr/bin/env python
"""Python/Node exporters -> owned localhost HTTP API -> real Mongo -> accounting.

No arguments print help using only the standard library. Explicit --mongo-url
requires a localhost guardian-r102 test replica. Only marker-owned random case
databases are removed. No .env, model provider or identity provider is accessed.
Child exporters receive the synthetic ingestion credential over stdin, never in
command arguments, inherited application environment or report artifacts.
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
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CANARY = "synthetic-provider-content-must-never-be-captured"


PYTHON_CHILD = r'''
import json, sys
from datetime import datetime, timezone
from uuid import uuid4
phase = "configuration"
exporter = None
try:
    config = json.loads(sys.stdin.read(8192))
    sys.path.insert(0, config["module_dir"])
    from guardian_exporter import BackgroundExporter
    from python_app import run_call, stream_call
    exporter = BackgroundExporter(origin=config["origin"], token=config["token"],
        allow_local=True, test_mode=config["test_mode"])
    trace = "python-" + uuid4().hex
    common = {"agent_name": "synthetic-python", "model": "synthetic/model", "trace_id": trace}
    phase = "known_completion"
    handle = exporter.start_call(**common)
    assert handle.finish("success", cost_usd="0.01", input_tokens=2, output_tokens=1)["accepted"]
    assert handle.finish("error")["code"] == "already_finished"
    ids = {"known": handle.observation_id}
    if not config["test_mode"]:
        phase = "result_identity"
        value = {"content": config["canary"]}
        assert run_call(exporter, lambda: value, **common) is value
        phase = "complete_stream"
        chunks = [value, {"content": config["canary"]}]
        items = list(stream_call(exporter, lambda: iter(chunks), **common))
        assert len(items) == 2 and all(left is right for left, right in zip(items, chunks))
        phase = "early_stream"
        stream = stream_call(exporter, lambda: iter(chunks), **common)
        assert next(stream) is value
        stream.close()
        phase = "error_identity"
        original = RuntimeError(config["canary"])
        def failing():
            raise original
        try:
            run_call(exporter, failing, **common)
        except RuntimeError as caught:
            assert caught is original
        else:
            raise AssertionError()
        phase = "explicit_retry"
        first, second = exporter.start_call(**common), exporter.start_call(**common)
        assert first.observation_id != second.observation_id
        assert first.trace_id == second.trace_id == trace
        assert first.finish("error", cost_usd="0.02", input_tokens=1, output_tokens=1)["accepted"]
        assert second.finish("success", cost_usd="0.03", input_tokens=3, output_tokens=2)["accepted"]
        ids.update(retry_error=first.observation_id, retry_success=second.observation_id)
        phase = "immutable_admission"
        stamp = datetime.now(timezone.utc).isoformat()
        event = dict(common, observation_id="zero-" + uuid4().hex, started_at=stamp,
            ended_at=stamp, status="success", cost_usd="0", input_tokens=0, output_tokens=0)
        ids["zero"] = event["observation_id"]
        assert exporter.emit(event)["accepted"]
        event["cost_usd"] = "900"
        phase = "reject_raw_fields"
        assert exporter.emit(dict(event, output=config["canary"])) == {"accepted": False, "code": "invalid_event"}
    phase = "flush"
    flushed = exporter.flush(timeout=15)
    assert flushed["drained"] and flushed["confirmed"]
    phase = "close"
    closed = exporter.close(timeout=2)
    assert closed["drained"] and closed["confirmed"]
    assert exporter.close(timeout=0)["confirmed"]
    assert not exporter.start_call(**common).finish("unknown")["accepted"]
    print(json.dumps({"status": "passed", "trace_id": trace, "ids": ids, "stats": exporter.snapshot(), "runtime_version": sys.version.split()[0]}))
except BaseException as error:
    if exporter is not None:
        exporter.close(timeout=0)
    print(json.dumps({"status": "failed", "phase": phase, "error_type": type(error).__name__}))
    sys.exit(1)
'''


NODE_CHILD = r'''
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
let phase = 'configuration', exporter;
const check = condition => { if (!condition) throw new Error('scenario_assertion'); };
try {
  let raw = '';
  for await (const chunk of process.stdin) { raw += chunk; check(raw.length <= 8192); }
  const config = JSON.parse(raw);
  const {BackgroundExporter} = await import(pathToFileURL(config.module_dir + '/guardian_exporter.mjs'));
  const {runCall, streamCall} = await import(pathToFileURL(config.module_dir + '/node_app.mjs'));
  exporter = new BackgroundExporter({origin: config.origin, token: config.token,
    allowLocal: true, testMode: config.test_mode});
  const trace = 'node-' + randomUUID(), common = {agent_name: 'synthetic-node', model: 'synthetic/model', trace_id: trace};
  phase = 'known_completion';
  const handle = exporter.startCall(common);
  check(handle.finish({status: 'success', cost_usd: '0.01', input_tokens: 2, output_tokens: 1}).accepted);
  check(handle.finish({status: 'error'}).code === 'already_finished');
  const ids = {known: handle.observation_id};
  if (!config.test_mode) {
    phase = 'result_identity';
    const value = {content: config.canary};
    check(await runCall(exporter, common, async () => value) === value);
    phase = 'complete_stream';
    const chunks = [value, {content: config.canary}], items = [];
    async function* provider() { yield* chunks; }
    for await (const item of streamCall(exporter, common, provider)) items.push(item);
    check(items.length === 2 && items.every((item, index) => item === chunks[index]));
    phase = 'early_stream';
    for await (const item of streamCall(exporter, common, provider)) { check(item === value); break; }
    phase = 'error_identity';
    const original = new Error(config.canary);
    let caughtOriginal = false;
    try { await runCall(exporter, common, async () => { throw original; }); }
    catch (caught) { caughtOriginal = caught === original; }
    check(caughtOriginal);
    phase = 'explicit_retry';
    const first = exporter.startCall(common), second = exporter.startCall(common);
    check(first.observation_id !== second.observation_id && first.trace_id === second.trace_id && first.trace_id === trace);
    check(first.finish({status: 'error', cost_usd: '0.02', input_tokens: 1, output_tokens: 1}).accepted);
    check(second.finish({status: 'success', cost_usd: '0.03', input_tokens: 3, output_tokens: 2}).accepted);
    ids.retry_error = first.observation_id; ids.retry_success = second.observation_id;
    phase = 'immutable_admission';
    const stamp = new Date().toISOString();
    const event = {...common, observation_id: 'zero-' + randomUUID(), started_at: stamp, ended_at: stamp,
      status: 'success', cost_usd: '0', input_tokens: 0, output_tokens: 0};
    ids.zero = event.observation_id;
    check(exporter.emit(event).accepted);
    event.cost_usd = '900';
    phase = 'reject_raw_fields';
    const rejected = exporter.emit({...event, output: config.canary});
    check(!rejected.accepted && rejected.code === 'invalid_event');
  }
  phase = 'flush';
  const flushed = await exporter.flush(15000);
  check(flushed.drained && flushed.confirmed);
  phase = 'close';
  const closed = await exporter.close(2000);
  check(closed.drained && closed.confirmed && (await exporter.close(0)).confirmed);
  check(!exporter.startCall(common).finish({status: 'unknown'}).accepted);
  console.log(JSON.stringify({status: 'passed', trace_id: trace, ids, stats: exporter.snapshot(), runtime_version: process.versions.node}));
} catch (error) {
  if (exporter) await exporter.close(0);
  console.log(JSON.stringify({status: 'failed', phase, error_type: error?.constructor?.name || 'Error'}));
  process.exitCode = 1;
}
'''


def dependencies():
    # Deferred so no-argument/help work under Python -I -S without site packages.
    sys.path.insert(0, str(ROOT / "tools"))
    global capture, mongo, identity, SYSTEM_KEYS
    import test_mongo_capture as capture
    import test_mongo_ledger as mongo
    import test_mongo_identity as identity
    from harness import SYSTEM_KEYS
    capture.load_dependencies()


async def child(language, origin, token, test_mode, node):
    config = {"origin": origin, "token": token, "test_mode": test_mode,
              "module_dir": str(ROOT / "examples" / "native-capture"), "canary": CANARY}
    environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    command = [sys.executable, "-I", "-S", "-c", PYTHON_CHILD] if language == "python" else [node, "--input-type=module", "-e", NODE_CHILD]
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment, cwd=ROOT)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(config).encode()), 25)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    mongo.check(len(stdout) <= 16384 and not stderr, language + "_child_unexpected_output")
    mongo.check(token.encode() not in stdout and CANARY.encode() not in stdout, language + "_child_private_output")
    result = json.loads(stdout)
    if process.returncode != 0 or result.get("status") != "passed":
        # Only this harness's finite phase names may enter a failure report.
        phases = {"configuration", "known_completion", "result_identity", "complete_stream", "early_stream",
                  "error_identity", "explicit_retry", "immutable_admission", "reject_raw_fields", "flush", "close"}
        phase = result.get("phase")
        raise mongo.CheckFailed(language + "_child_" + (phase if phase in phases else "failed"))
    stats = result["stats"]
    expected = 1 if test_mode else 8
    mongo.check(stats["enqueued_events"] == stats["confirmed_events"] == expected,
                language + "_child_counts_not_confirmed")
    mongo.check(stats["pending_events"] == stats["unconfirmed_events"] == stats["pending_bytes"] == 0,
                language + "_child_counts_not_drained")
    mongo.check(stats["closed"] and not stats["transport_active"], language + "_child_transport_not_closed")
    mongo.check(stats["rejected_events"] == (1 if test_mode else 2), language + "_child_rejected_count_wrong")
    mongo.check(isinstance(result.get("runtime_version"), str)
                and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", result["runtime_version"]), "invalid_runtime_version")
    return result


async def language_pipeline(f, language, node):
    names = ("guardian_exporter.py", "guardian_capture.py", "python_app.py") if language == "python" \
        else ("guardian_exporter.mjs", "guardian_capture.mjs", "node_app.mjs")

    def source_hashes():
        return {name: hashlib.sha256((ROOT / "examples" / "native-capture" / name).read_bytes()).hexdigest()
                for name in names}

    source_before = source_hashes()
    async with capture.http_api(f) as (configured, client):
        store = capture.IdentityStore(f.db, configured)
        session = await store.create_session({"issuer": configured.issuer, "subject": "owner-subject"})
        client.cookies.set(configured.session_cookie, session)
        response = await client.get("/api/guardian/access")
        mongo.check(response.status_code == 200, "named_access_failed")
        headers = {"Origin": configured.ui_origin, "X-Guardian-CSRF": response.json()["csrf_token"]}
        response = await client.post("/api/guardian/ingestion-keys", headers=headers,
            json={"label": "Synthetic " + language + " exporter", "expires_in_days": 7, "request_id": str(uuid4())})
        mongo.check(response.status_code == 201, "owner_key_creation_failed")
        token = response.json()["token"]
        tested = await child(language, configured.public_url, token, True, node)
        for collection in ("guardian_capture_inbox", "guardian_observations", "guardian_metrics", "guardian_incidents"):
            mongo.check(await f.db[collection].count_documents({}) == 0, "test_export_created_production_data")
        state = await f.db.guardian_state.find_one({"_id": "direct_capture"})
        mongo.check(state and state.get("last_test_received_at") and not state.get("last_received_at"),
                    "test_export_claimed_real_traffic")

        original = capture.CaptureService.ingest
        attempts, receipt_replays, wire_digests = [], [], []
        import capture.routes as capture_routes
        original_read = capture_routes.read_json

        async def observe_wire(request):
            original_receive = request._receive
            fingerprint = hashlib.sha256()

            async def receive():
                message = await original_receive()
                if message["type"] == "http.request":
                    fingerprint.update(message.get("body", b""))
                return message

            request._receive = receive
            try:
                # Preserve the actual route's bounded streaming parser; observe
                # a content hash without buffering or retaining request bytes.
                return await original_read(request)
            finally:
                request._receive = original_receive
                wire_digests.append(fingerprint.hexdigest())

        async def lose_first_ack(service, sent_token, batch):
            result = await original(service, sent_token, batch)
            if not batch.test_mode:
                attempts.append((batch.batch_id, capture.digest([capture.safe_metric(metric) for metric in batch.metrics])))
                receipt_replays.append(result["replayed"])
                if len(attempts) == 1:
                    error = capture.CaptureError(503, "capture_unavailable")
                    # Deterministic one-second floor keeps this fault proof bounded.
                    error.headers["Retry-After"] = "1"
                    raise error
            return result

        with patch.object(capture.CaptureService, "ingest", lose_first_ack), \
                patch.object(capture_routes, "read_json", observe_wire):
            result = await child(language, configured.public_url, token, False, node)
        mongo.check(len(attempts) == 2 and attempts[0] == attempts[1], "delivery_retry_changed_batch")
        mongo.check(len(wire_digests) == 2 and wire_digests[0] == wire_digests[1], "delivery_retry_changed_wire_bytes")
        mongo.check(receipt_replays == [False, True], "delivery_retry_did_not_use_replay_receipt")
        mongo.check(result["stats"]["export_attempts"] == 2, "nested_or_missing_transport_retry")
        mongo.check(await f.db.guardian_capture_inbox.count_documents({}) == 8, "replayed_batch_duplicated_inbox")
        response = await client.get("/api/guardian/capture")
        mongo.check(response.status_code == 200 and response.json()["status"]["pending_events"] == 8,
                    "pending_export_not_visible")
        # Machine authority alone may write but cannot read the dashboard.
        saved = dict(client.cookies)
        client.cookies.clear()
        response = await client.get("/api/guardian/metrics", headers={"X-Guardian-Ingest-Key": token})
        mongo.check(response.status_code == 401, "machine_key_obtained_dashboard_authority")
        client.cookies.update(saved)
        await f.ledger.release(f.lease)
        await capture.poll_direct_once(f.db, configured)
        response = await client.get("/api/guardian/metrics")
        mongo.check(response.status_code == 200, "metrics_unavailable")
        rows = response.json()
        mongo.check(sum(row["call_count"] for row in rows) == 8, "metrics_call_count_inflated")
        mongo.check(sum(row["error_count"] for row in rows) == 2, "error_terminal_count_wrong")
        mongo.check(sum(row["unknown_status_count"] for row in rows) == 1, "early_stream_claimed_completion")
        mongo.check(sum(row["cost_known_count"] for row in rows) == 4
                    and sum(row["cost_unknown_count"] for row in rows) == 4, "unknown_cost_became_free")
        mongo.check(abs(sum(row["known_cost_usd"] for row in rows) - 0.06) < 1e-12,
                    "known_cost_did_not_reconcile")
        mongo.check(sum(row["known_total_tokens"] for row in rows) == 10, "tokens_did_not_reconcile")
        response = await client.get("/api/guardian/live/runs/" + result["trace_id"])
        mongo.check(response.status_code == 200, "run_evidence_unavailable")
        run = response.json()
        mongo.check(len(run["calls"]) == 8 and run["cost_usd"] is None and run["total_tokens"] is None,
                    "run_unknown_totals_not_preserved")
        by_id = {row["id"]: row for row in run["calls"]}
        ids = result["ids"]
        mongo.check(by_id[ids["zero"]]["cost_usd"] == 0, "caller_mutation_changed_admitted_event")
        mongo.check(by_id[ids["retry_error"]]["status"] == "error"
                    and by_id[ids["retry_success"]]["status"] == "success", "explicit_retry_attempts_lost")
        mongo.check(run["workflow_status"] == "unknown" and run["langfuse_url"] is None,
                    "direct_calls_invented_workflow_or_vendor_evidence")
        response = await client.get("/api/guardian/incidents")
        mongo.check(response.status_code == 200 and len(response.json()) == 2, "error_incidents_not_reconciled")
        mongo.check(all(not row["trace_urls"] for row in response.json()), "direct_incident_invented_vendor_url")
        response = await client.get("/api/guardian/capture")
        status = response.json()["status"]
        mongo.check(status["pending_events"] == 0 and status["processed_events"] == 8,
                    "processed_status_not_reconciled")
        for name in await f.db.list_collection_names():
            documents = await f.db[name].find({}).to_list(200)
            rendered = json.dumps(documents, default=str)
            mongo.check(CANARY not in rendered and token not in rendered, "private_value_persisted")
        # Re-running an idle worker must leave derived values unchanged.
        await capture.poll_direct_once(f.db, configured)
        response = await client.get("/api/guardian/metrics")
        mongo.check(response.status_code == 200 and response.json() == rows, "idle_worker_changed_accounting")
        mongo.check(source_hashes() == source_before, "exporter_source_changed_during_case")
        f.suite.details[language] = {"transport": "localhost_http", "runtime_version": result["runtime_version"], "production_events": 8,
            "source_sha256": source_before,
            "test_events": 1, "known_cost_usd": 0.06, "unknown_cost_events": 4,
            "known_tokens": 10, "error_calls": 2, "unknown_calls": 1, "incidents": 2,
            "transport_attempts": 2, "committed_receipt_replay": True, "raw_content_absent": True,
            "retry_wire_bytes_identical": True,
            "test_mode_separate": True, "application_result_and_error_identity": True,
            "terminal_stream_semantics": True, "explicit_retry_ids_distinct": True,
            "exporter_closed": result["stats"]["closed"] and tested["stats"]["closed"]}


async def run_suite(uri, node):
    suite = mongo.Suite(uri)
    suite.details = {}
    started = asyncio.get_running_loop().time()
    try:
        version = await suite.preflight()
        for language in ("python", "node"):
            await suite.run(language + "_exporter_actual_http_pipeline",
                            lambda fixture, lang=language: language_pipeline(fixture, lang, node))
        failed = sum(result["status"] != "passed" for result in suite.results)
        return {"status": "failed" if failed or suite.owned else "passed", "mongo_version": version,
            "finished_at": datetime.now(timezone.utc).isoformat(), "passed": len(suite.results) - failed,
            "failed": failed, "cleanup_complete": not suite.owned,
            "duration_seconds": round(asyncio.get_running_loop().time() - started, 3),
            "tests": suite.results, "evidence": suite.details}
    finally:
        suite.admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", help="Explicit localhost-only guardian-r102 replica-set URI")
    parser.add_argument("--node", default="node", help="Node interpreter (default: node on PATH)")
    parser.add_argument("--report", help="Optional safe JSON artifact under tools/reports")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        parser.print_help()
        return 0
    report = None
    try:
        # Validation is stdlib-only and precedes application dependency loading.
        sys.path.insert(0, str(ROOT / "tools"))
        import test_mongo_ledger as safe_mongo
        uri = safe_mongo.validate_url(args.mongo_url)
        if args.report:
            report = Path(args.report).resolve()
            safe_mongo.check(report.is_relative_to((ROOT / "tools" / "reports").resolve()), "report_path_outside_reports")
        node = shutil.which(args.node)
        safe_mongo.check(node is not None, "node_interpreter_missing")
        dependencies()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        result = asyncio.run(run_suite(uri, node))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if "safe_mongo" in locals() and isinstance(error, safe_mongo.CheckFailed):
            result["code"] = str(error)
    rendered = json.dumps(result, indent=2)
    if report is not None and report.is_relative_to((ROOT / "tools" / "reports").resolve()):
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
