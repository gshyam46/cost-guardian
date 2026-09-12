"""Independent R1 cross-boundary acceptance checks (docs/TELEMETRY.md).

These exercise actual normalization/source reads through the worker and stores.
External SDK transport and Mongo persistence are fakes; no fixture can establish
real database atomicity, settled telemetry completeness or replay safety.
"""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.detectors import cost_anomaly, reliability_anomaly
from guardian.langfuse_client import LangfuseTraceSource
from guardian.metrics import MongoMetricsStore
from guardian.models import SourceReadResult, TraceMetric


NOW = datetime.now(timezone.utc).replace(microsecond=0)
PRIVATE_ERROR = "provider-secret-and-private-response-must-not-escape"


def _observation(identifier="generation-1", **changes):
    start = NOW - timedelta(minutes=1)
    row = {
        "id": identifier,
        "trace_id": "workflow-" + identifier,
        "name": "answer-generator",
        "model": "test-model",
        "start_time": start,
        "end_time": start + timedelta(seconds=0.5),
        "calculated_total_cost": 0.75,
        "usage": {"input": 12, "output": 8, "total": 20},
        "latency": 0.5,
        "level": "DEFAULT",
    }
    row.update(changes)
    return row


class ReadSDK:
    def __init__(self, rows=(), fail_page=None):
        self.rows = list(rows)
        self.fail_page = fail_page
        self.calls = []

    def fetch_observations(self, **kwargs):
        self.calls.append(kwargs)
        page, limit = kwargs.get("page", 1), kwargs.get("limit", 100)
        if page == self.fail_page:
            raise ConnectionError(PRIVATE_ERROR)
        rows = [
            row for row in self.rows
            if kwargs["from_start_time"] <= row["start_time"] < kwargs["to_start_time"]
        ]
        offset = (page - 1) * limit
        return SimpleNamespace(
            data=rows[offset:offset + limit],
            meta=SimpleNamespace(
                page=page,
                limit=limit,
                total_items=len(rows),
                total_pages=(len(rows) + limit - 1) // limit,
            ),
        )


def _source(sdk):
    # tests/conftest.py clears credentials before application imports.
    source = LangfuseTraceSource()
    source._api_version = "v1"
    source._client = sdk
    return source


@pytest.fixture
def database():
    return AsyncMongoMockClient()["guardian_r1_contract"]


@pytest.fixture
def worker(monkeypatch, database):
    import guardian.worker as module

    monkeypatch.setattr(module, "db", database)
    return module


@pytest.fixture
def api(monkeypatch, database):
    import api.routes as routes
    import auth
    from server import app

    monkeypatch.setattr(routes, "db", database)
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", "r1-contract-test-key")
    return app


async def _metrics_response(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/guardian/metrics", headers={"X-Guardian-Key": "r1-contract-test-key"})
    response.raise_for_status()
    return response.json()


@pytest.mark.anyio
@pytest.mark.parametrize("read_case", ["first_page_failure", "later_page_failure", "row_cap", "invalid_identity"])
async def test_incomplete_source_read_preserves_checkpoint_and_all_candidate_writes(
    read_case, worker, database, caplog
):
    previous = NOW - timedelta(minutes=2)
    await database.guardian_state.insert_one({
        "_id": worker.CURSOR_DOC_ID,
        "last_polled_at": previous.isoformat(),
    })
    # Existing data must also survive a failed attempted ingestion unchanged.
    await database.guardian_metrics.insert_one({"_id": "existing-metric", "call_count": 7})
    await database.guardian_incidents.insert_one({"_id": "existing-incident", "title": "Preserve me"})
    before_metrics = await database.guardian_metrics.find({}).to_list(10)
    before_incidents = await database.guardian_incidents.find({}).to_list(10)

    if read_case == "first_page_failure":
        sdk = ReadSDK(fail_page=1)
    elif read_case == "later_page_failure":
        sdk = ReadSDK([_observation(str(index)) for index in range(150)], fail_page=2)
    elif read_case == "row_cap":
        sdk = ReadSDK([_observation(str(index)) for index in range(501)])
    else:
        sdk = ReadSDK([_observation(), _observation("malformed", id="")])

    result = await worker.poll_once(_source(sdk))

    assert result == 0
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous.isoformat()
    assert state["read_status"] == ("failed" if read_case == "first_page_failure" else "partial")
    assert await database.guardian_metrics.find({}).to_list(10) == before_metrics
    assert await database.guardian_incidents.find({}).to_list(10) == before_incidents
    assert PRIVATE_ERROR not in json.dumps(state)
    assert PRIVATE_ERROR not in caplog.text


@pytest.mark.anyio
async def test_successful_retry_after_read_failure_accounts_for_preserved_window(worker, database):
    previous = NOW - timedelta(minutes=2)
    await database.guardian_state.insert_one({
        "_id": worker.CURSOR_DOC_ID,
        "last_polled_at": previous.isoformat(),
    })
    sdk = ReadSDK([_observation()], fail_page=1)
    source = _source(sdk)

    await worker.poll_once(source)
    sdk.fail_page = None
    await worker.poll_once(source)

    rollups = await MongoMetricsStore(database).since(NOW - timedelta(hours=1))
    assert sum(row["call_count"] for row in rollups) == 1
    assert sum(row["total_cost_usd"] for row in rollups) == pytest.approx(0.75)
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert datetime.fromisoformat(state["last_polled_at"]) > previous
    assert state["read_status"] == "complete"


@pytest.mark.anyio
async def test_failed_result_without_optional_window_metadata_is_a_safe_stopped_read(worker, database):
    class UnavailableSource:
        def fetch_generations(self, **kwargs):
            return SourceReadResult(metrics=[], status="failed", error_code="not_configured")

    assert await worker.poll_once(UnavailableSource()) == 0

    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert "last_polled_at" not in state
    assert state["read_status"] == "failed"
    assert state["processing_status"] == "read_blocked"
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_incidents.count_documents({}) == 0


@pytest.mark.anyio
async def test_initial_window_does_not_move_forward_during_repeated_source_outages(worker, database, monkeypatch):
    class Clock(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(worker, "datetime", Clock)
    source = _source(ReadSDK(fail_page=1))
    await worker.poll_once(source)
    initial = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})

    Clock.current += timedelta(minutes=10)
    await worker.poll_once(source)

    later = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert later["initial_cursor_at"] == initial["initial_cursor_at"]
    assert "last_polled_at" not in later


def _metric(identifier, *, cost=0.01, latency=1000.0, status="success", tokens=20):
    return TraceMetric(
        trace_id=identifier,
        observation_id=identifier,
        agent_name="answer-generator",
        model="test-model",
        cost_usd=cost,
        total_tokens=tokens,
        latency_ms=latency,
        status=status,
        timestamp=NOW - timedelta(minutes=1),
    )


def test_unknown_cost_does_not_poison_baseline_or_create_a_cost_incident():
    known = [_metric("baseline-" + str(index)) for index in range(6)]
    unknown = [_metric("unknown-" + str(index), cost=None) for index in range(2)]

    results = cost_anomaly.evaluate(
        known + unknown,
        [_metric("cost-spike", cost=2.0), _metric("unpriced-candidate", cost=None)],
    )

    assert len(results) == 1
    assert results[0].trace_ids == ["cost-spike"]
    assert results[0].evidence["baseline_n"] == 6
    assert results[0].evidence["baseline_mean_usd"] == pytest.approx(0.01)


def test_unknown_cost_history_is_not_a_free_baseline():
    baseline = [_metric(str(index), cost=None) for index in range(6)]

    assert cost_anomaly.evaluate(baseline, [_metric("paid", cost=2.0)]) == []


def test_unknown_latency_and_outcome_do_not_hide_real_reliability_evidence():
    baseline = [_metric("baseline-" + str(index)) for index in range(6)]
    baseline.append(_metric("unmeasured-history", latency=None))
    candidates = [
        _metric("slow-call", latency=10000.0),
        _metric("failed-call", cost=None, latency=None, tokens=None, status="error"),
        _metric("unmeasured-call", latency=None),
        _metric("unknown-outcome", latency=None, status="unknown"),
    ]

    results = reliability_anomaly.evaluate(baseline, candidates)

    assert {result.trace_ids[0] for result in results} == {"slow-call", "failed-call"}
    slow = next(result for result in results if result.trace_ids == ["slow-call"])
    assert slow.evidence["baseline_n"] == 6
    failure = next(result for result in results if result.trace_ids == ["failed-call"])
    assert failure.evidence["status"] == "error"


@pytest.mark.anyio
async def test_mixed_known_and_unknown_measurements_reach_api_with_honest_denominators(database, api):
    await MongoMetricsStore(database).record([
        _metric("explicit-zero", cost=0.0, tokens=0, latency=0.0),
        _metric("unmeasured", cost=None, tokens=None, latency=None, status="unknown"),
        _metric("known-failure", cost=0.75, tokens=20, latency=1000.0, status="error"),
    ])

    rows = await _metrics_response(api)

    assert len(rows) == 1
    row = rows[0]
    assert row["call_count"] == 3
    assert row["error_count"] == 1
    assert row["unknown_status_count"] == 1
    assert row["total_cost_usd"] is None
    assert row["known_cost_usd"] == pytest.approx(0.75)
    assert (row["cost_known_count"], row["cost_unknown_count"]) == (2, 1)
    assert row["total_tokens"] is None
    assert row["known_total_tokens"] == 20
    assert (row["tokens_known_count"], row["tokens_unknown_count"]) == (2, 1)
    assert row["avg_latency_ms"] == 500.0
    assert (row["latency_known_count"], row["latency_unknown_count"]) == (2, 1)
    assert row["accounting_status"] == "ledger-1"


@pytest.mark.anyio
async def test_missing_optional_source_measurements_remain_observations_not_zeroes(worker, database, api):
    await database.guardian_state.insert_one({
        "_id": worker.CURSOR_DOC_ID,
        "last_polled_at": (NOW - timedelta(minutes=2)).isoformat(),
    })
    sdk = ReadSDK([_observation(
        calculated_total_cost=None, usage={}, latency=None, end_time=None,
    )])

    await worker.poll_once(_source(sdk))

    rows = await _metrics_response(api)
    assert len(rows) == 1
    row = rows[0]
    assert row["call_count"] == 1
    assert row["total_cost_usd"] is None
    assert row["total_tokens"] is None
    assert row["avg_latency_ms"] is None
    assert (row["cost_known_count"], row["cost_unknown_count"]) == (0, 1)
    assert (row["tokens_known_count"], row["tokens_unknown_count"]) == (0, 1)
    assert (row["latency_known_count"], row["latency_unknown_count"]) == (0, 1)
    assert await database.guardian_incidents.count_documents({}) == 0


@pytest.mark.anyio
async def test_existing_legacy_bucket_requires_explicit_cutover_before_new_accounting(database, api):
    from guardian.ledger import LedgerError
    from guardian.metrics import hour_bucket, rollup_id

    hour = hour_bucket(NOW - timedelta(minutes=1))
    await database.guardian_metrics.insert_one({
        "_id": rollup_id(hour, "answer-generator"),
        "hour": hour,
        "agent_name": "answer-generator",
        "call_count": 2,
        "error_count": 0,
        "total_cost_usd": 2.0,
        "total_tokens": 100,
        "sum_latency_ms": 1000.0,
    })

    with pytest.raises(LedgerError, match="legacy_metrics_migration_required"):
        await MongoMetricsStore(database).record([_metric("new-call", cost=0.75)])

    row = (await _metrics_response(api))[0]
    assert row["call_count"] == 2
    assert row["coverage_status"] == "legacy"
    assert row["total_cost_usd"] is None
    assert row["known_cost_usd"] is None
    assert row["cost_known_count"] is None
    assert row["total_tokens"] is None
    assert row["avg_latency_ms"] is None
    stored = await database.guardian_metrics.find_one({"_id": rollup_id(hour, "answer-generator")})
    assert stored["total_cost_usd"] == pytest.approx(2.0)
    assert await database.guardian_observations.count_documents({}) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("measurements", "nullable_fields", "issue"),
    [
        ({"calculated_total_cost": "1e308"}, ("total_cost_usd", "known_cost_usd"), "cost_total_out_of_range"),
        ({"latency": "1e305"}, ("avg_latency_ms",), "latency_total_out_of_range"),
        ({"usage": {"total": (1 << 63) - 1}}, ("total_tokens", "known_total_tokens"), "tokens_total_out_of_range"),
    ],
)
async def test_valid_source_values_that_overflow_rollups_remain_json_safe(
    measurements, nullable_fields, issue, worker, database, api
):
    """Finite individual measurements do not guarantee a representable aggregate.

    This exercises mock persistence only; real Mongo overflow and reconciliation
    behavior require the R1-02 database suite. Public JSON must remain usable even
    when a stored aggregate cannot represent its constituent measurements.
    """
    await database.guardian_state.insert_one({
        "_id": worker.CURSOR_DOC_ID,
        "last_polled_at": (NOW - timedelta(minutes=2)).isoformat(),
    })
    source = _source(ReadSDK([
        _observation("large-" + str(index), **measurements) for index in range(2)
    ]))

    await worker.poll_once(source)

    row = (await _metrics_response(api))[0]
    assert row["call_count"] == 2
    for field in nullable_fields:
        assert row[field] is None
    assert issue in row["aggregate_issues"]
    json.dumps(row, allow_nan=False)


@pytest.mark.anyio
async def test_worker_source_transport_runs_outside_the_event_loop_thread(worker):
    class ThreadRecordingSDK(ReadSDK):
        def fetch_observations(self, **kwargs):
            self.thread_id = threading.get_ident()
            return super().fetch_observations(**kwargs)

    sdk = ThreadRecordingSDK()
    event_loop_thread = threading.get_ident()

    await worker.poll_once(_source(sdk))

    assert sdk.thread_id != event_loop_thread


@pytest.mark.anyio
@pytest.mark.parametrize("abandon", ["cancel", "timeout"])
async def test_abandoned_awaiters_cannot_release_capacity_while_source_threads_still_run(abandon):
    from guardian.source_io import MAX_SOURCE_READS, SourceReadBusy, SourceReadTimeout, run_source_read

    loop = asyncio.get_running_loop()
    release = threading.Event()
    started = [asyncio.Event() for _ in range(MAX_SOURCE_READS)]
    finished = [asyncio.Event() for _ in range(MAX_SOURCE_READS)]

    def blocked_read(index):
        loop.call_soon_threadsafe(started[index].set)
        try:
            if not release.wait(timeout=5):
                raise RuntimeError("Test cleanup failed to release the source fixture")
            return index
        finally:
            loop.call_soon_threadsafe(finished[index].set)

    timeout = 0.2 if abandon == "timeout" else 5
    tasks = [
        asyncio.create_task(run_source_read(blocked_read, index, timeout=timeout))
        for index in range(MAX_SOURCE_READS)
    ]
    try:
        # The loop remains available while every actual source thread is blocked.
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), timeout=2)
        if abandon == "cancel":
            for task in tasks:
                task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        expected_error = asyncio.CancelledError if abandon == "cancel" else SourceReadTimeout
        assert all(isinstance(outcome, expected_error) for outcome in outcomes)

        with pytest.raises(SourceReadBusy):
            await run_source_read(lambda: "must not be queued", timeout=0.1)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in finished)), timeout=2)

    # Thread completion releases its permit just after the fixture signals finish.
    # Retry only that scheduling boundary, under an explicit short deadline.
    async def confirm_capacity_recovered():
        while True:
            try:
                return await run_source_read(lambda: "recovered", timeout=1)
            except SourceReadBusy:
                await asyncio.sleep(0)

    assert await asyncio.wait_for(confirm_capacity_recovered(), timeout=1) == "recovered"
