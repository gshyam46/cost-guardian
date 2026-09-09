#!/usr/bin/env python
"""Run the Founder Niche Discovery pipeline N times to build real per-agent baselines,
polling the Guardian worker after each run.

Why this exists: the cost and reliability detectors need >= MIN_BASELINE_SAMPLES (5)
prior calls per agent before they will evaluate anything at all. Until that history
exists, a genuinely anomalous run is silently ignored -- correct behaviour, but it
means "does the detector fire on organic data?" can't be answered from a single run.
This script builds that history against the real Langfuse project and real Mongo.

Usage (from the repo root):
    python tools/build_baseline.py            # default 6 runs
    python tools/build_baseline.py 10

Groq's free tier allows 8k tokens/min and one full run costs ~12k, so this paces
itself between runs. Expect it to take several minutes.
"""
import asyncio
import sys
import time
from datetime import datetime, timezone
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

PAUSE_BETWEEN_RUNS_SECONDS = 45

# Varied profiles so the runs aren't identical -- identical inputs would give a
# zero-variance baseline, which the detectors treat as a special case rather than a
# normal distribution.
PROFILES = [
    {
        "education": "BS Computer Science", "current_role": "Senior Software Engineer",
        "years_experience": 6, "tech_skills": ["Python", "React", "AWS"],
        "domain_skills": ["fintech"], "soft_skills": ["communication"],
        "previous_projects": "Internal analytics dashboard.",
        "excited_domains": ["developer tools"], "hours_per_week": 15,
        "runway_months": 6, "location": "Remote", "risk_appetite": "medium",
        "target_roles": ["founder"], "existing_portfolio": "", "github_url": "",
        "network_strength": "moderate", "learning_mode": "build-first",
    },
    {
        "education": "MSc Data Science", "current_role": "ML Engineer",
        "years_experience": 4, "tech_skills": ["Python", "PyTorch", "SQL"],
        "domain_skills": ["healthcare"], "soft_skills": ["research"],
        "previous_projects": "Medical imaging classifier.",
        "excited_domains": ["healthtech", "AI infrastructure"], "hours_per_week": 20,
        "runway_months": 12, "location": "Berlin", "risk_appetite": "high",
        "target_roles": ["technical founder"], "existing_portfolio": "",
        "github_url": "", "network_strength": "strong", "learning_mode": "theory-first",
    },
    {
        "education": "BA Economics", "current_role": "Product Manager",
        "years_experience": 8, "tech_skills": ["SQL", "Figma"],
        "domain_skills": ["e-commerce", "growth"], "soft_skills": ["leadership"],
        "previous_projects": "Scaled a marketplace to 1M users.",
        "excited_domains": ["commerce", "vertical SaaS"], "hours_per_week": 10,
        "runway_months": 9, "location": "London", "risk_appetite": "low",
        "target_roles": ["business founder"], "existing_portfolio": "",
        "github_url": "", "network_strength": "strong", "learning_mode": "mentor-led",
    },
]


async def main():
    target_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6

    from db import db, close_database
    from services.llm_fallback import configure_langfuse
    from services.orchestrator import NicheDiscoveryOrchestrator
    from guardian.langfuse_client import LangfuseTraceSource
    from guardian.worker import poll_once

    if not configure_langfuse():
        print("Langfuse not configured -- nothing would be traced. Aborting.")
        return 1

    await db.command("ping")
    orchestrator = NicheDiscoveryOrchestrator()
    source = LangfuseTraceSource()

    succeeded, failed, incidents_created = 0, 0, 0

    for run_number in range(1, target_runs + 1):
        profile = PROFILES[(run_number - 1) % len(PROFILES)]
        started = time.monotonic()
        print(f"\n=== Run {run_number}/{target_runs} ===", flush=True)
        try:
            await orchestrator.run(
                profile, f"baseline-user-{run_number}", f"baseline-profile-{run_number}"
            )
            succeeded += 1
            print(
                f"  completed in {time.monotonic() - started:.0f}s "
                f"run_id={orchestrator.last_run_id}",
                flush=True,
            )
        except Exception as e:
            failed += 1
            # A failed run is still useful signal -- it produces error generations for
            # the reliability detector -- so keep going rather than aborting the batch.
            print(f"  FAILED after {time.monotonic() - started:.0f}s: {type(e).__name__}: {e}", flush=True)

        if run_number < target_runs:
            print(f"  pausing {PAUSE_BETWEEN_RUNS_SECONDS}s for rate limits...", flush=True)
            await asyncio.sleep(PAUSE_BETWEEN_RUNS_SECONDS)

    # Let Langfuse finish ingesting, then run the worker over everything at once.
    print("\nWaiting 20s for Langfuse ingestion, then polling the worker...", flush=True)
    await asyncio.sleep(20)

    for cycle in range(1, 4):
        created = await poll_once(source)
        incidents_created += created
        print(f"  poll cycle {cycle}: {created} incident(s) created", flush=True)
        if cycle < 3:
            await asyncio.sleep(10)

    total_incidents = await db.guardian_incidents.count_documents({})
    total_rollups = await db.guardian_metrics.count_documents({})

    print("\n" + "=" * 60)
    print(f"Runs: {succeeded} succeeded, {failed} failed")
    print(f"Incidents created this batch: {incidents_created}")
    print(f"Total incidents in Mongo: {total_incidents}")
    print(f"Total metric rollups in Mongo: {total_rollups}")

    by_detector: dict = {}
    async for doc in db.guardian_incidents.find({}, {"_id": 0, "detector": 1}):
        by_detector[doc.get("detector", "?")] = by_detector.get(doc.get("detector", "?"), 0) + 1
    print(f"Incidents by detector: {by_detector}")

    await close_database()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
