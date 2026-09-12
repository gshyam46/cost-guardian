"""guardian/worker.py::poll_once() orchestration, against a mocked Mongo backend
(mongomock-motor) and a fake Langfuse source -- verifies the cursor/baseline/candidate
wiring and detector-failure isolation that unit tests on the individual pieces
(detectors, incident_engine, langfuse_client) don't cover. Still not a substitute for
running against a real Langfuse project; see docs/PROGRESS.md blockers.
"""
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.models import SourceReadResult, TraceMetric

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

    def fetch_generations(self, since, until=None, limit=500):
        return SourceReadResult(metrics=self._metrics, status="complete", window_start=since, window_end=until)


def _trace(trace_id, cost, minutes_ago, agent="profile_analyst"):
    return TraceMetric(
        trace_id=trace_id,
        observation_id=trace_id,
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


async def test_checkpoint_older_than_source_window_is_not_silently_discarded(mock_db):
    import guardian.worker as worker_module

    previous = datetime.now(timezone.utc) - timedelta(hours=25)
    await worker_module._save_cursor(previous)

    class Source:
        def fetch_generations(self, **kwargs):
            raise AssertionError("A newer query cannot recover the missing history")

    assert await worker_module.poll_once(Source()) == 0
    state = await mock_db.guardian_state.find_one({"_id": worker_module.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous.isoformat()
    assert state["read_error_code"] == "checkpoint_outside_window"
    assert state["processing_status"] == "read_blocked"
    assert await mock_db.guardian_metrics.count_documents({}) == 0


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


async def test_failed_attempt_does_not_reuse_previous_read_counts(mock_db):
    import guardian.worker as worker_module

    previous = datetime.now(timezone.utc) - timedelta(minutes=2)
    await worker_module._save_cursor(previous)
    await worker_module._record_health(
        read_status="complete", pages_fetched=3, records_read=250,
        invalid_count=2, source_fetched_at=previous.isoformat(),
        detector_failures=1,
    )

    class Source:
        def fetch_generations(self, **kwargs):
            raise RuntimeError("synthetic source failure")

    assert await worker_module.poll_once(Source()) == 0
    state = await mock_db.guardian_state.find_one({"_id": worker_module.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous.isoformat()
    assert state["read_status"] == "failed"
    assert state["records_read"] == state["pages_fetched"] == state["invalid_count"] == 0
    assert state["source_fetched_at"] is None
    assert state["detector_failures"] == 0
    assert state["window_end"] == state["last_attempt_at"]


async def test_query_change_cannot_restart_a_traversal_under_a_new_fingerprint(mock_db):
    import guardian.worker as worker_module
    from guardian.models import SourcePageResult, SourceRowDisposition

    previous = datetime.now(timezone.utc) - timedelta(minutes=2)
    await worker_module._save_cursor(previous)

    class ChangingQuery:
        api_version = "v2"
        calls = 0

        def fetch_generation_page(self, since, until, **kwargs):
            self.calls += 1
            if self.calls == 1:
                candidate = _trace("first-page", cost=0.75, minutes_ago=1)
                return SourcePageResult(
                    rows=[SourceRowDisposition(0, "accepted", "first-row", metric=candidate)],
                    status="ok", window_start=since, window_end=until,
                    query_fingerprint="original-query", next_cursor="continuation", exhausted=False,
                    records_read=1,
                )
            if self.calls == 2:
                return SourcePageResult(
                    rows=[], status="failed", window_start=since, window_end=until,
                    query_fingerprint="changed-query", request_cursor=kwargs.get("cursor"),
                    error_code="query_mismatch",
                )
            # Clearing the saved fingerprint would let a changed source query
            # pretend to complete the original traversal on a third request.
            return SourcePageResult(
                rows=[], status="ok", window_start=since, window_end=until,
                query_fingerprint="changed-query", exhausted=True,
            )

    source = ChangingQuery()
    await worker_module.poll_once(source)

    state = await mock_db.guardian_state.find_one({"_id": worker_module.CURSOR_DOC_ID})
    assert source.calls == 2
    assert state["last_polled_at"] == previous.isoformat()
    assert state["active_window"]["query_fingerprint"] == "original-query"
    assert state["active_window"]["cursor"] == "continuation"


async def test_expired_worker_cannot_overwrite_replacement_worker_health(mock_db, monkeypatch):
    import guardian.worker as worker_module
    from config import GUARDIAN_CONNECTION_ID
    from guardian.ledger import ObservationLedger

    replacement = ObservationLedger(mock_db, GUARDIAN_CONNECTION_ID)
    replacement_lease = None
    expected = {
        "processing_status": "reading", "read_status": "reading",
        "read_error_code": None, "last_finished_at": None,
        "last_attempt_at": "replacement-attempt",
    }

    async def interrupted_read(source, window):
        nonlocal replacement_lease
        await mock_db.guardian_leases.update_one(
            {"_id": replacement.lease_id},
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
        )
        replacement_lease = await replacement.acquire("replacement-owner")
        assert replacement_lease is not None
        await mock_db.guardian_state.update_one(
            {"_id": worker_module.CURSOR_DOC_ID}, {"$set": expected},
        )
        raise RuntimeError("Previous worker's source request failed after takeover")

    monkeypatch.setattr(worker_module, "_read_page", interrupted_read)
    try:
        await worker_module.poll_once(FakeSource([]))
        state = await mock_db.guardian_state.find_one({"_id": worker_module.CURSOR_DOC_ID})
        assert {key: state.get(key) for key in expected} == expected
    finally:
        if replacement_lease is not None:
            await replacement.release(replacement_lease)


async def test_later_history_page_can_supply_baseline_before_candidate_is_marked_processed(mock_db, monkeypatch):
    import guardian.worker as worker_module
    from guardian.models import SourcePageResult, SourceRowDisposition

    monkeypatch.setattr(worker_module, "SOURCE_ROW_LIMIT", 100)
    candidate = _trace("recent-expensive-call", cost=5.0, minutes_ago=1)
    history = [_trace("older-baseline-" + str(index), cost=0.01, minutes_ago=30 - index)
               for index in range(6)]

    class DescendingHistory:
        api_version = "v2"

        def fetch_generation_page(self, since, until, **kwargs):
            cursor = kwargs.get("cursor")
            values = [candidate] if cursor is None else history
            rows = [SourceRowDisposition(index, "accepted", item.observation_id, metric=item)
                    for index, item in enumerate(values)]
            return SourcePageResult(
                rows=rows, status="ok", window_start=since, window_end=until,
                request_cursor=cursor, query_fingerprint="same-fixed-query",
                next_cursor="older-history" if cursor is None else None,
                exhausted=cursor is not None, records_read=len(rows),
            )

    source = DescendingHistory()
    await worker_module.poll_once(source)
    await worker_module.poll_once(source)

    incidents = await mock_db.guardian_incidents.find({"detector": "cost_anomaly"}).to_list(10)
    assert len(incidents) == 1
    assert incidents[0]["trace_ids"] == [candidate.trace_id]
    assert incidents[0]["evidence"]["baseline_n"] == 6
