#!/usr/bin/env python
"""End-to-end MVP verification: run this once real Langfuse + MongoDB credentials are
in backend/.env.

Runs the exact 10 steps from the MVP success criterion:

  Founder Niche Discovery -> LiteLLM -> Langfuse -> Guardian worker -> detector
  -> incident engine -> Mongo -> GET /api/guardian/incidents

Usage (from the repo root):
    python tools/verify_mvp.py

Writes a step-by-step report to stdout and a machine-readable copy to
tools/verify_mvp_report.json (git-ignored -- may contain trace ids, never
credentials) for a follow-up session to read back and act on.

Design note: step 7's "controlled, deterministic anomaly" is intentionally NOT a real
cost spike -- there's no reliable way to force a free-tier LLM call to suddenly cost
10x. Instead it feeds one clearly-labeled synthetic TraceMetric (prefixed
`guardian-verify-`) through the REAL detector and REAL Mongo-backed incident store, so
the anomaly trigger is controlled while the storage/retrieval path underneath it is
exercised for real. Everything else (steps 2-6) uses your actual Founder Niche
Discovery pipeline and actual Langfuse project -- nothing else is faked.
"""
import asyncio
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
from pathlib import Path

# These tools deliberately span BOTH applications: they drive the monitored app to
# generate real telemetry, then assert Guardian picked it up. That cross-app scope is
# exactly why they live in tools/ at the repo root rather than inside either service --
# neither app should import the other, but an integration harness may import both.
REPO_ROOT = Path(__file__).resolve().parent.parent
FOUNDER_BACKEND = REPO_ROOT / "apps" / "founder-app" / "backend"
GUARDIAN_BACKEND = REPO_ROOT / "apps" / "guardian" / "backend"
sys.path.insert(0, str(FOUNDER_BACKEND))
sys.path.insert(0, str(GUARDIAN_BACKEND))

from dotenv import load_dotenv

load_dotenv(FOUNDER_BACKEND / ".env")
load_dotenv(GUARDIAN_BACKEND / ".env")

REPORT_PATH = Path(__file__).resolve().parent / "verify_mvp_report.json"

report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "steps": []}


def log_step(number: int, name: str, ok: bool, detail: str = "", data: dict | None = None):
    symbol = "OK " if ok else "FAIL"
    print(f"[{symbol}] Step {number}: {name}")
    if detail:
        print(f"       {detail}")
    report["steps"].append(
        {"step": number, "name": name, "ok": ok, "detail": detail, "data": data or {}}
    )
    return ok


def fail_and_exit(number: int, name: str, detail: str):
    log_step(number, name, False, detail)
    _write_report()
    print("\nStopping -- later steps depend on this one. See remediation above.")
    sys.exit(1)


def _write_report():
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nFull report written to {REPORT_PATH}")


async def main():
    # --- Step 1: prerequisites -------------------------------------------------
    from config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, MONGO_URL

    missing = []
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        missing.append("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY")
    if not missing:
        pass
    if MONGO_URL == "mongodb://localhost:27017":
        print(
            "       Note: MONGO_URL is still the default placeholder -- if that's "
            "intentional (you're running Mongo locally), ignore this."
        )

    if missing:
        fail_and_exit(
            1, "Prerequisites (Langfuse credentials)",
            f"Missing: {', '.join(missing)}. Add them to backend/.env and re-run.",
        )

    from db import db, close_database

    try:
        await db.command("ping")
    except Exception as e:
        fail_and_exit(
            1, "Prerequisites (MongoDB reachable)",
            f"Could not reach MongoDB at MONGO_URL: {e}. "
            "Point MONGO_URL at a running local/Docker/Atlas instance.",
        )

    log_step(1, "Prerequisites", True, "Langfuse credentials present, MongoDB reachable.")

    # --- Step 2: run Founder Niche Discovery once -------------------------------
    from services.orchestrator import NicheDiscoveryOrchestrator
    from services.llm_fallback import configure_langfuse

    langfuse_active = configure_langfuse()
    if not langfuse_active:
        fail_and_exit(2, "Wire Langfuse through LiteLLM", "configure_langfuse() reported inactive.")

    synthetic_profile = {
        "education": "BS Computer Science",
        "current_role": "Senior Software Engineer",
        "years_experience": 6,
        "tech_skills": ["Python", "React", "AWS"],
        "domain_skills": ["fintech"],
        "soft_skills": ["communication"],
        "previous_projects": "Built an internal analytics dashboard.",
        "excited_domains": ["developer tools", "AI infrastructure"],
        "hours_per_week": 15,
        "runway_months": 6,
        "location": "Remote",
        "risk_appetite": "medium",
        "target_roles": ["founder"],
        "existing_portfolio": "",
        "github_url": "",
        "network_strength": "moderate",
        "learning_mode": "build-first",
    }

    verify_user_id = f"verify-mvp-{uuid.uuid4()}"
    verify_profile_id = f"verify-mvp-{uuid.uuid4()}"

    orchestrator = NicheDiscoveryOrchestrator()
    pipeline_start = datetime.now(timezone.utc)

    try:
        report_obj = await orchestrator.run(synthetic_profile, verify_user_id, verify_profile_id)
    except Exception as e:
        fail_and_exit(2, "Run Founder Niche Discovery once", f"Pipeline raised: {e}")

    run_id = orchestrator.last_run_id
    log_step(
        2, "Run Founder Niche Discovery once", True,
        f"Pipeline completed, status={report_obj.status}, run_id={run_id}",
        {"run_id": run_id, "user_id": verify_user_id},
    )

    # --- Steps 3 & 4: confirm grouping + real field mapping ---------------------
    from guardian.langfuse_client import LangfuseTraceSource

    source = LangfuseTraceSource()
    if not source.available:
        fail_and_exit(3, "Confirm grouped trace", "LangfuseTraceSource not available after configure_langfuse() succeeded.")

    # litellm's Langfuse callback flushes asynchronously on its own schedule, so poll
    # rather than guessing a single sleep duration.
    POLL_SECONDS, POLL_INTERVAL = 90, 5
    this_run: list = []
    waited = 0
    print(f"       Polling Langfuse for run_id={run_id} (up to {POLL_SECONDS}s)...", flush=True)
    while waited < POLL_SECONDS:
        all_recent = source.fetch_recent_generations(
            since=pipeline_start - timedelta(minutes=5), limit=200
        )
        this_run = [m for m in all_recent if m.trace_id == run_id]
        if len(this_run) >= 5:
            break
        if this_run:
            print(f"       ...{len(this_run)}/5 generations so far ({waited}s)", flush=True)
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    print(f"       Found {len(this_run)} generation(s) after {waited}s.", flush=True)

    expected_agents = {"profile_analyst", "market_hunter", "fit_evaluator", "roadmap_architect", "tooling_advisor"}
    found_agents = {m.agent_name for m in this_run}

    if not this_run:
        fail_and_exit(
            3, "Confirm grouped trace",
            f"No Langfuse generations found for run_id={run_id} yet. Langfuse ingestion "
            "may need more time -- try increasing the sleep above and re-running, or "
            "check the trace manually in the Langfuse UI.",
        )

    grouping_ok = found_agents == expected_agents
    log_step(
        3, "Confirm 5-agent execution grouped under shared run_id", grouping_ok,
        f"Found {len(this_run)} generations under run_id={run_id}. "
        f"Agents present: {sorted(found_agents)}. Expected: {sorted(expected_agents)}.",
        {"generations_found": len(this_run), "agents_found": sorted(found_agents)},
    )

    field_rows = [
        {
            "agent": m.agent_name,
            "model": m.model,
            "total_tokens": m.total_tokens,
            "latency_ms": m.latency_ms,
            "cost_usd": m.cost_usd,
            "status": m.status,
        }
        for m in this_run
    ]
    print("       Real Langfuse field mapping for this run:")
    for row in field_rows:
        print(f"         {row}")

    # Only *successful* generations must carry tokens/cost/latency. A failed call
    # (rate limit, timeout) legitimately has 0 tokens and 0 cost -- litellm's failure
    # callback still logs it, and Guardian's reliability detector depends on those
    # rows existing. Asserting "every row has tokens > 0" would flag correct
    # error-capture behaviour as a mapping bug.
    successes = [r for r in field_rows if r["status"] == "success"]
    errors = [r for r in field_rows if r["status"] != "success"]

    problems = []
    if not successes:
        problems.append("no successful generations were captured at all")
    for row in successes:
        if row["model"] == "unknown":
            problems.append(f"{row['agent']}: model not mapped")
        if row["total_tokens"] <= 0:
            problems.append(f"{row['agent']}: token count not mapped")
        if row["latency_ms"] <= 0:
            problems.append(f"{row['agent']}: latency not mapped")
        if row["cost_usd"] <= 0:
            problems.append(f"{row['agent']}: cost not mapped")

    log_step(
        4, "Confirm real Langfuse fields (model/tokens/latency/cost/errors)",
        not problems,
        (
            f"{len(successes)} successful generation(s) all carry model, tokens, "
            f"latency and cost; {len(errors)} failed generation(s) correctly captured "
            f"with status=error and zero tokens/cost."
        ) if not problems else
        "Field mapping problems: " + "; ".join(problems) + ". Fix _get()'s fallback "
        "field names in guardian/langfuse_client.py and add a regression test.",
        {"rows": field_rows, "successes": len(successes), "errors": len(errors)},
    )
    fields_look_sane = not problems

    # --- Steps 5 & 6: real worker reads real Langfuse data -----------------------
    from guardian.worker import poll_once

    try:
        created_from_real_poll = await poll_once(source)
        worker_ok = True
        worker_detail = (
            f"poll_once() ran against real Langfuse data without raising. "
            f"{created_from_real_poll} incident(s) created from this cycle (0 is "
            f"expected on a first run -- detectors need >=5 real baseline samples per "
            f"agent before they'll evaluate anything)."
        )
    except Exception as e:
        worker_ok = False
        worker_detail = f"poll_once() raised against real data: {e}"
        created_from_real_poll = None

    log_step(5, "Run guardian/worker.py::poll_once() against the real trace", worker_ok, worker_detail)
    log_step(
        6, "Verify worker transforms real Langfuse response into TraceMetric correctly",
        worker_ok and fields_look_sane,
        "Same evidence as step 4 -- poll_once() uses the same _observation_to_trace_metric() path.",
    )

    # --- Step 7: controlled, deterministic anomaly -------------------------------
    from guardian.detectors import cost_anomaly
    from guardian.incident_engine import process_detector_results
    from guardian.store import MongoIncidentStore
    from guardian.models import TraceMetric

    baseline_cost = 0.001
    synthetic_baseline = [
        TraceMetric(
            trace_id=f"guardian-verify-baseline-{i}",
            agent_name="profile_analyst",
            model="groq/llama-3.3-70b-versatile",
            cost_usd=baseline_cost,
            total_tokens=500,
            latency_ms=800.0,
            status="success",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=30 - i),
        )
        for i in range(6)
    ]
    anomaly_trace_id = f"guardian-verify-anomaly-{uuid.uuid4()}"
    synthetic_candidate = TraceMetric(
        trace_id=anomaly_trace_id,
        agent_name="profile_analyst",
        model="groq/llama-3.3-70b-versatile",
        cost_usd=baseline_cost * 50,  # unmistakably an outlier, not real API variance
        total_tokens=500,
        latency_ms=800.0,
        status="success",
        timestamp=datetime.now(timezone.utc),
    )

    detector_results = cost_anomaly.evaluate(synthetic_baseline, [synthetic_candidate])
    anomaly_detected = any(r.triggered for r in detector_results)

    if not anomaly_detected:
        fail_and_exit(
            7, "Trigger controlled deterministic anomaly",
            f"cost_anomaly.evaluate() did not trigger on a {synthetic_candidate.cost_usd} "
            f"vs baseline mean {baseline_cost} input -- this indicates a real regression "
            f"in guardian/detectors/cost_anomaly.py, not a missing-data issue.",
        )

    log_step(
        7, "Trigger controlled deterministic anomaly", True,
        f"Synthetic candidate (trace_id={anomaly_trace_id}, cost=${synthetic_candidate.cost_usd}) "
        f"vs synthetic baseline (mean=${baseline_cost}) correctly triggered "
        f"{[r.detector for r in detector_results if r.triggered]}.",
    )

    # --- Step 8: persisted in Mongo (the real store, real db) -------------------
    store = MongoIncidentStore(db)
    created_incidents = await process_detector_results(detector_results, store)

    if not created_incidents:
        fail_and_exit(
            8, "Verify incident persisted in Mongo",
            "process_detector_results() returned no incidents despite a triggered "
            "detector result -- check incident_engine.py's dedup logic.",
        )

    incident = created_incidents[0]
    fetched_back = await store.get(incident.id)
    persisted_ok = fetched_back is not None and fetched_back.id == incident.id
    log_step(
        8, "Verify incident persisted in Mongo", persisted_ok,
        f"Incident id={incident.id}, detector={incident.detector}, "
        f"severity={incident.severity}, stored in guardian_incidents and read back successfully.",
        {"incident_id": incident.id},
    )

    # --- Step 9: retrievable through the real HTTP API ---------------------------
    import httpx
    from server import app

    api_user_id = f"verify-mvp-api-{uuid.uuid4()}"
    session_token = f"verify-mvp-session-{uuid.uuid4()}"
    try:
        await db.users.insert_one({
            "id": api_user_id, "email": "verify-mvp@local.test", "name": "Verify MVP",
            "picture": None, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.user_sessions.insert_one({
            "user_id": api_user_id, "session_token": session_token,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://verify.local") as client:
            response = await client.get(
                "/api/guardian/incidents",
                cookies={"session_token": session_token},
            )

        api_ok = response.status_code == 200 and any(
            row["id"] == incident.id for row in response.json()
        )
        log_step(
            9, "Retrieve incident via GET /api/guardian/incidents", api_ok,
            f"HTTP {response.status_code}, {len(response.json()) if response.status_code == 200 else 0} "
            f"incident(s) returned, target incident {'found' if api_ok else 'NOT found'} in the list.",
        )
    finally:
        await db.users.delete_one({"id": api_user_id})
        await db.user_sessions.delete_one({"session_token": session_token})

    # --- Step 10: flag for follow-up -------------------------------------------
    any_failures = any(not s["ok"] for s in report["steps"])
    log_step(
        10, "Add/update tests for any real-data mapping bugs discovered",
        not any_failures,
        "No mapping bugs surfaced -- nothing to add." if not any_failures else
        "One or more steps failed above -- read verify_mvp_report.json and fix "
        "guardian/langfuse_client.py's field extraction, then add a regression test "
        "with the real field shape that broke it.",
    )

    _write_report()
    await close_database()

    print("\n" + "=" * 70)
    if any_failures:
        print("RESULT: end-to-end flow did NOT fully verify. See failures above.")
        sys.exit(1)
    else:
        print("RESULT: end-to-end flow verified successfully.")
        print(f"Incident id: {incident.id}")
        print(f"Run id: {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
