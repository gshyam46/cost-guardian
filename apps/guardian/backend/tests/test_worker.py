"""guardian/worker.py::poll_once() orchestration, against a mocked Mongo backend
(mongomock-motor) and a fake Langfuse source -- verifies the cursor/baseline/candidate
wiring and detector-failure isolation that unit tests on the individual pieces
(detectors, incident_engine, langfuse_client) don't cover. Still not a substitute for
running against a real Langfuse project; see docs/PROGRESS.md blockers.
"""
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.models import TraceMetric

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_db(monkeypatch):
    client = AsyncMongoMockClient()
    database = client["guardian_worker_test_db"]
    # worker.py bound `db` at import time via `from db import db` -- patch
    # its own reference, same reasoning as tests/test_guardian_api.py.
    import guardian.worker as worker_module

    monkeypatch.setattr(worker_module, "db", database)
    return database


class FakeSource:
    """Stands in for LangfuseTraceSource -- returns a canned list regardless of the
    since/limit args, since poll_once's own cursor filtering is what's under test."""

    def __init__(self, metrics):
        self.available = True
        self._metrics = metrics

    def fetch_recent_generations(self, since, limit=500):
        return self._metrics


def _trace(trace_id, cost, minutes_ago, agent="profile_analyst"):
    return TraceMetric(
        trace_id=trace_id,
        agent_name=agent,
        model="groq/llama-3.3-70b-versatile",
        cost_usd=cost,
        total_tokens=500,
        latency_ms=800.0,
        status="success",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


async def test_poll_once_creates_incident_for_anomalous_candidate(mock_db):
    from guardian.worker import poll_once

    # 6 baseline calls from 30-20 minutes ago (older than the default ~5 minute
    # cursor), then one brand new, wildly expensive call.
    baseline = [_trace(f"base-{i}", 0.01, minutes_ago=30 - i) for i in range(6)]
    candidate = _trace("candidate-1", cost=5.0, minutes_ago=0)

    source = FakeSource(baseline + [candidate])
    created_count = await poll_once(source)

    assert created_count == 1
    incidents = await mock_db.guardian_incidents.find({}).to_list(10)
    assert len(incidents) == 1
    assert incidents[0]["detector"] == "cost_anomaly"
    assert incidents[0]["trace_ids"] == ["candidate-1"]


async def test_poll_once_persists_cursor(mock_db):
    from guardian.worker import poll_once

    source = FakeSource([])
    await poll_once(source)

    cursor_doc = await mock_db.guardian_state.find_one({"_id": "guardian_worker_cursor"})
    assert cursor_doc is not None
    assert cursor_doc["last_polled_at"]


async def test_poll_once_returns_zero_when_no_new_candidates(mock_db):
    from guardian.worker import poll_once

    # Everything older than the default cursor window -> nothing counts as "new".
    old_only = [_trace(f"old-{i}", 0.01, minutes_ago=60) for i in range(6)]
    source = FakeSource(old_only)

    created_count = await poll_once(source)

    assert created_count == 0
    assert await mock_db.guardian_incidents.count_documents({}) == 0


async def test_poll_once_survives_a_broken_detector(mock_db, monkeypatch):
    """One detector raising must not stop the others or crash the poll cycle."""
    import guardian.worker as worker_module

    class BrokenDetector:
        NAME = "broken_detector"

        @staticmethod
        def evaluate(baseline, candidates):
            raise RuntimeError("simulated detector bug")

    monkeypatch.setattr(worker_module, "DETECTORS", [BrokenDetector, worker_module.pii])

    candidate = _trace("candidate-1", cost=0.01, minutes_ago=0)
    # give it PII to detect so we can prove the *other* detector still ran
    candidate.output_text = "Contact us at founder@example.com"
    source = FakeSource([candidate])

    created_count = await worker_module.poll_once(source)

    assert created_count == 1  # from the pii detector; broken_detector didn't crash the run
    incidents = await mock_db.guardian_incidents.find({}).to_list(10)
    assert incidents[0]["detector"] == "pii"
