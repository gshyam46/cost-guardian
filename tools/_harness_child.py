"""Private single-application subprocess entry point for harness.py.

This file never imports both applications. Do not run it directly; the parent owns
its selected environment, deadline, localhost checks and process cleanup.
"""
from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import socket
import sys
import time
import types
import uuid
import warnings


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = sys.stdout
EXPECTED_AGENTS = {
    "profile_analyst", "market_hunter", "fit_evaluator", "roadmap_architect", "tooling_advisor"
}


class StepError(Exception):
    pass


def emit(**message):
    PROTOCOL.write(json.dumps(message) + "\n")
    PROTOCOL.flush()


def bootstrap(app: str):
    backend = ROOT / "apps" / ("guardian" if app == "guardian" else "founder-app") / "backend"
    # Python -I starts without cwd/PYTHONPATH/user-site imports. Add exactly ONE
    # application's module root; no other app's config/db/server can resolve.
    sys.path.insert(0, str(backend))
    import dotenv

    # Older dotenv releases may ignore PYTHON_DOTENV_DISABLED. Explicitly prevent
    # config.py (or an SDK) from loading an unselected, default .env file as well.
    dotenv.load_dotenv = lambda *_args, **_kwargs: False
    import dotenv.main
    dotenv.main.load_dotenv = dotenv.load_dotenv
    import config

    if Path(config.__file__).resolve().parent != backend:
        raise StepError("configuration_invalid")


def block_external_network():
    """An offline smoke can bind localhost but cannot dial any service."""
    def denied(*_args, **_kwargs):
        raise OSError("Network dialing is disabled in the offline harness")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied


def mocked_database():
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()
    module = types.ModuleType("db")
    module.client = client
    module.db = client["guardian_verify_offline"]

    async def close_database():
        client.close()

    module.close_database = close_database
    sys.modules["db"] = module
    return module.db


async def seed_offline():
    from guardian.models import SourceReadResult, TraceMetric
    from guardian.worker import poll_once
    from db import db
    from guardian.ledger import ObservationLedger

    # Explicitly opt this synthetic harness into mock semantics. Real transaction
    # evidence is provided separately by test_mongo_ledger.py.
    async def mock_transaction(self, callback):
        return await callback(None)
    ObservationLedger.transaction = mock_transaction

    now = datetime.now(timezone.utc)
    metrics = [
        TraceMetric(
            trace_id="guardian-verify-baseline-" + str(index), agent_name="synthetic_agent",
            observation_id="synthetic-baseline-" + str(index), source="synthetic",
            model="synthetic-model", cost_usd=0.01, total_tokens=500,
            latency_ms=800, status="success", timestamp=now - timedelta(minutes=30 - index),
        ) for index in range(6)
    ]
    metrics.append(TraceMetric(
        trace_id="guardian-verify-anomaly", agent_name="synthetic_agent", model="synthetic-model",
        observation_id="synthetic-anomaly", source="synthetic",
        cost_usd=5.0, total_tokens=500, latency_ms=800, status="success", timestamp=now,
    ))

    class SyntheticSource:
        available = True

        def fetch_generations(self, since, until=None, limit=500):
            selected = [metric for metric in metrics if metric.timestamp >= since and (until is None or metric.timestamp <= until)][:limit]
            return SourceReadResult(
                metrics=selected, records_read=len(selected), pages_fetched=1,
                status="complete", window_start=since, window_end=until,
            )

    if await poll_once(SyntheticSource()) != 1:
        raise StepError("offline_worker_failed")
    incident = await db.guardian_incidents.find_one({"detector": "cost_anomaly"})
    if not incident or incident["trace_ids"] != ["guardian-verify-anomaly"]:
        raise StepError("offline_worker_failed")
    rollups = await db.guardian_metrics.find({}).to_list(10)
    if sum(row["call_count"] for row in rollups) != 7 or abs(sum(row["total_cost_usd"] for row in rollups) - 5.06) > 1e-9:
        raise StepError("offline_worker_failed")
    return {"source": "synthetic", "persistence": "mongomock", "incident_id": incident["id"]}


async def verify_mongo_transactions(database):
    """Require real transaction support before any paid workload is started."""
    try:
        async with await database.client.start_session() as session:
            session.start_transaction()
            try:
                await database.guardian_preflight.insert_one({"_id": "transaction-capability"}, session=session)
            finally:
                await session.abort_transaction()
    except Exception:
        raise StepError("mongo_transactions_required") from None


async def preflight():
    import uvicorn  # Verify the HTTP dependency before spending on a workload.
    from server import app
    from config import DB_NAME
    from db import db
    from guardian.langfuse_client import LangfuseTraceSource

    if os.environ.get("GUARDIAN_HARNESS_TEST_ONLY") != "1" or not DB_NAME.startswith("guardian_verify_"):
        raise StepError("configuration_invalid")
    await asyncio.wait_for(db.command("ping"), timeout=10)
    # A fresh named database is required for an attributable verification result.
    # Never erase existing data to force a pass, even in a test-named database.
    if await db.list_collection_names():
        raise StepError("test_database_not_empty")
    await verify_mongo_transactions(db)
    source = LangfuseTraceSource()
    if not source.available:
        raise StepError("live_source_failed")
    try:
        # Exercise the selected adapter, including v2 fields/cursor contract.
        # One accepted page is access evidence, not a full telemetry window.
        from guardian.source_io import run_source_read
        until = datetime.now(timezone.utc)
        result = await run_source_read(
            source.fetch_generations, since=until - timedelta(hours=24), until=until, limit=1,
        )
        if not result.complete and not (result.status == "partial" and result.error_code == "limit_reached"):
            raise StepError("live_source_failed")
    except Exception:
        source.close()
        raise StepError("live_source_failed") from None
    return source


def validate_live_rollups(receipts, candidates, rollups):
    """Reconcile the ACTUAL worker read, not an earlier successful source probe."""
    wanted_ids = {row["run_id"] for row in receipts}
    for run_id in wanted_ids:
        intended = [metric for metric in candidates if metric.trace_id == run_id]
        if {metric.agent_name for metric in intended} != EXPECTED_AGENTS:
            raise StepError("live_worker_failed")
        successes = [metric for metric in intended if metric.status == "success"]
        if not successes or any(
            metric.model == "unknown" or metric.total_tokens is None or metric.total_tokens <= 0
            or metric.latency_ms is None or metric.latency_ms <= 0
            or metric.cost_usd is None or metric.cost_usd <= 0
            or not math.isfinite(metric.cost_usd) or not math.isfinite(metric.latency_ms)
            for metric in successes
        ):
            raise StepError("live_mapping_failed")
    expected = {}
    for metric in candidates:
        hour = metric.timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        key = (hour, metric.agent_name)
        totals = expected.setdefault(key, {
            "call_count": 0, "error_count": 0, "total_cost_usd": 0.0,
            "total_tokens": 0, "sum_latency_ms": 0.0,
        })
        totals["call_count"] += 1
        totals["error_count"] += metric.status == "error"
        totals["total_cost_usd"] += metric.cost_usd if metric.cost_usd is not None else 0.0
        totals["total_tokens"] += metric.total_tokens if metric.total_tokens is not None else 0
        totals["sum_latency_ms"] += metric.latency_ms if metric.latency_ms is not None else 0.0
    stored = {(row["hour"], row["agent_name"]): row for row in rollups}
    if stored.keys() != expected.keys() or len(stored) != len(rollups):
        raise StepError("live_worker_failed")
    for key, totals in expected.items():
        if any(
            not math.isclose(stored[key].get(field, float("nan")), value, rel_tol=1e-9, abs_tol=1e-9)
            for field, value in totals.items()
        ):
            raise StepError("live_worker_failed")


async def ingest_live(request):
    source = await preflight()
    try:
        return await _ingest_live_from_source(request, source)
    finally:
        source.close()


async def _ingest_live_from_source(request, source):
    from db import db
    from guardian.worker import CURSOR_DOC_ID, poll_once

    receipts = request["runs"]
    wanted_ids = {row["run_id"] for row in receipts}
    started = min(datetime.fromisoformat(row["started_at"]) for row in receipts)
    deadline = time.monotonic() + request["poll_timeout"]
    selected = []
    while time.monotonic() < deadline:
        read = await asyncio.to_thread(source.fetch_generations, since=started - timedelta(seconds=1), limit=500)
        selected = [metric for metric in read.metrics if metric.trace_id in wanted_ids]
        if all(
            {metric.agent_name for metric in selected if metric.trace_id == run_id} == EXPECTED_AGENTS
            for run_id in wanted_ids
        ) and read.status == "complete":
            break
        await asyncio.sleep(min(5, max(0, deadline - time.monotonic())))
    else:
        raise StepError("live_source_failed")
    successes = [metric for metric in selected if metric.status == "success"]
    if not successes or any(
        metric.model == "unknown" or metric.total_tokens is None or metric.total_tokens <= 0
        or metric.latency_ms is None or metric.latency_ms <= 0
        or metric.cost_usd is None or metric.cost_usd <= 0
        for metric in successes
    ):
        raise StepError("live_mapping_failed")
    # Explicit test cursor avoids losing the start of long Founder runs to the
    # production worker's initial five-minute lookback. No detector is injected.
    await db.guardian_state.update_one(
        {"_id": CURSOR_DOC_ID},
        {"$set": {"last_polled_at": (started - timedelta(seconds=1)).isoformat()}},
        upsert=True,
    )
    class RecordedSource:
        """Delegate unchanged real data, retaining exactly what the worker saw."""
        available = source.available
        api_version = source.api_version
        window = None
        observed = None

        def fetch_generations(self, since, until=None, limit=500):
            self.window = source.fetch_generations(since=since, until=until, limit=limit)
            return self.window

        def fetch_generation_page(self, since, until, **kwargs):
            from guardian.models import SourceReadResult
            page = source.fetch_generation_page(since=since, until=until, **kwargs)
            if self.observed is None:
                self.observed = {}
            for row in page.rows:
                if row.disposition == "accepted":
                    metric = row.metric
                    self.observed[(metric.source, metric.project_id, metric.trace_id, metric.observation_id)] = metric
            self.window = SourceReadResult(metrics=list(self.observed.values()),
                status="complete" if page.status == "ok" and page.exhausted else "partial",
                window_start=since, window_end=until, api_version="v2")
            return page

    recorded = RecordedSource()
    await poll_once(recorded)
    rollups = await db.guardian_metrics.find({}).to_list(5000)
    state = await db.guardian_state.find_one({"_id": CURSOR_DOC_ID}) or {}
    if (recorded.window is None or recorded.window.status != "complete"
            or state.get("processing_status") != "complete" or state.get("read_status") != "complete"):
        raise StepError("live_worker_failed")
    # Initial ingestion accounts for the whole captured window, including history.
    candidates = recorded.window.metrics
    validate_live_rollups(receipts, candidates, rollups)
    return {"source": "langfuse", "persistence": "mongodb", "source_api_version": source.api_version}


async def founder_workload(request):
    from services.llm_fallback import configure_langfuse
    from services.orchestrator import NicheDiscoveryOrchestrator

    if os.environ.get("GUARDIAN_HARNESS_TEST_ONLY") != "1" or not configure_langfuse():
        raise StepError("configuration_invalid")
    # Deliberately synthetic customer profile; all generated telemetry is test data.
    profiles = [
        ("Senior Software Engineer", ["Python", "React"], "developer tools"),
        ("ML Engineer", ["Python", "SQL"], "AI infrastructure"),
        ("Product Manager", ["SQL", "Figma"], "commerce"),
    ]
    role, skills, domain = profiles[request.get("profile_index", 0) % len(profiles)]
    profile = {
        "education": "BS Computer Science", "current_role": role, "years_experience": 6,
        "tech_skills": skills, "domain_skills": [domain], "soft_skills": ["communication"],
        "previous_projects": "Synthetic verification project.", "excited_domains": [domain],
        "hours_per_week": 15, "runway_months": 6, "location": "Remote",
        "risk_appetite": "medium", "target_roles": ["founder"], "existing_portfolio": "",
        "github_url": "", "network_strength": "moderate", "learning_mode": "build-first",
    }
    orchestrator = NicheDiscoveryOrchestrator()
    started = datetime.now(timezone.utc).isoformat()
    try:
        report = await orchestrator.run(profile, "guardian-verify-" + str(uuid.uuid4()), "guardian-verify-" + str(uuid.uuid4()))
        if report.status != "completed":
            raise StepError("founder_workload_failed")
        # LiteLLM emits callbacks asynchronously. Give those callbacks time, then
        # require actual arrival at Langfuse in the other process (never assume it).
        await asyncio.sleep(10)
    except Exception:
        raise StepError("founder_workload_failed") from None
    return {"run_id": orchestrator.last_run_id, "started_at": started}


async def serve(evidence):
    import uvicorn
    from server import app

    # Keep the socket open from allocation through uvicorn startup: no free-port
    # race, no fixed port collision, and bind only to loopback.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, log_level="critical", access_log=False,
            host="127.0.0.1", port=listener.getsockname()[1],
        ))
        emit(event="ready", port=listener.getsockname()[1], **evidence)
        await server.serve(sockets=[listener])
    finally:
        listener.close()


async def run(mode, request):
    if mode == "founder":
        bootstrap("founder")
        emit(event="completed", **await founder_workload(request))
        return
    bootstrap("guardian")
    if mode == "guardian-offline":
        block_external_network()
        mocked_database()
        await serve(await seed_offline())
        return
    from db import close_database
    try:
        if mode == "guardian-preflight":
            source = await preflight()
            try:
                emit(event="completed", source_api_version=source.api_version)
            finally:
                source.close()
        elif mode == "guardian-live":
            await serve(await ingest_live(request))
        else:
            raise StepError("configuration_invalid")
    finally:
        await close_database()


def main():
    modes = {"founder", "guardian-preflight", "guardian-live", "guardian-offline"}
    if len(sys.argv) != 2 or sys.argv[1] not in modes:
        return 2
    # Keep all SDK/app output private, including warnings and import-time logging.
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore")
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            request = json.loads(sys.stdin.readline(65536))
            asyncio.run(run(sys.argv[1], request))
            return 0
        except ModuleNotFoundError:
            emit(event="error", code="dependency_missing")
        except StepError as error:
            emit(event="error", code=str(error))
        except Exception:
            emit(event="error", code="child_failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
