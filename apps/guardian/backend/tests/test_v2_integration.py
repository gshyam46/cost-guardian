"""Independent v2 wire -> worker/store/authenticated API acceptance.

HTTPX MockTransport exercises real request construction and response parsing.
Mongo and transaction execution are simulated. These checks exercise durable
state and replay decisions, but cannot prove database atomicity, crash durability,
supported live server versions or source arrival latency.
"""

import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.langfuse_client import LangfuseTraceSource
from guardian.traces import LiveTraceReader


NOW = datetime.now(timezone.utc).replace(microsecond=0)
PRIVATE_BODY = "private-provider-response-must-not-escape"
OPAQUE_CURSOR = "private-cursor:+/with?reserved=&characters"
SOURCE_PATH = "/base/api/public/v2/observations"
API_HEADERS = {"X-Guardian-Key": "v2-integration-key"}


def observation(identifier="observation-1", **overrides):
    start = NOW - timedelta(minutes=1)
    row = {
        "id": identifier,
        "traceId": "workflow-" + identifier,
        "projectId": "test-project",
        "type": "GENERATION",
        "name": "answer-generator",
        "model": "test-model",
        "startTime": start.isoformat(),
        "endTime": (start + timedelta(seconds=0.5)).isoformat(),
        "usageDetails": {"input": 12, "output": 8, "total": 20},
        "inputUsage": 12,
        "outputUsage": 8,
        "totalUsage": 20,
        "costDetails": {"total": 0.75},
        "totalCost": 0.75,
        "latency": 0.5,
        "level": "DEFAULT",
    }
    row.update(overrides)
    return row


@pytest.fixture
def database():
    return AsyncMongoMockClient()["guardian_v2_integration"]


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
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", API_HEADERS["X-Guardian-Key"])
    return app


@pytest.fixture
def source_factory():
    sources = []

    def build(handler):
        # Omit api_version to exercise the configured default (v2).
        source = LangfuseTraceSource(
            host="https://source.invalid/base",
            public_key="test-public",
            secret_key="test-secret",
            transport=httpx.MockTransport(handler),
        )
        sources.append(source)
        return source

    yield build
    for source in sources:
        close = getattr(source, "close", None)
        if callable(close):
            close()


async def api_get(app, path, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, params=params, headers=API_HEADERS)


async def seed_cursor(worker, database):
    previous = (NOW - timedelta(minutes=2)).isoformat()
    await database.guardian_state.insert_one({
        "_id": worker.CURSOR_DOC_ID, "last_polled_at": previous,
    })
    return previous


@pytest.mark.anyio
async def test_default_v2_short_cursor_pages_reconcile_worker_and_live_totals(
    worker, database, api, monkeypatch, source_factory, caplog
):
    import api.routes as routes

    caplog.set_level(logging.INFO, logger="httpx")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={
                "data": [observation("first"), observation("second")],
                "meta": {"cursor": OPAQUE_CURSOR},
            })
        assert request.url.params["cursor"] == OPAQUE_CURSOR
        return httpx.Response(200, json={"data": [observation("third")], "meta": {}})

    source = source_factory(handler)
    previous = await seed_cursor(worker, database)
    await worker.poll_once(source)
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["read_status"] == "complete"
    assert state["last_polled_at"] != previous
    assert len(calls) == 2
    assert calls[0].url.params["fromStartTime"] == calls[1].url.params["fromStartTime"]
    assert calls[0].url.params["toStartTime"] == calls[1].url.params["toStartTime"]

    response = await api_get(api, "/api/guardian/metrics")
    response.raise_for_status()
    rows = response.json()
    assert sum(row["call_count"] for row in rows) == 3
    assert sum(row["total_cost_usd"] for row in rows) == pytest.approx(2.25)
    assert sum(row["total_tokens"] for row in rows) == 60
    assert all(row["avg_latency_ms"] == 500 for row in rows)

    monkeypatch.setattr(routes, "_live", LiveTraceReader(source))
    response = await api_get(api, "/api/guardian/live", calls=1)
    response.raise_for_status()
    body = response.json()
    assert body["stats"]["call_count"] == 3
    assert body["stats"]["total_cost_usd"] == pytest.approx(2.25)
    assert body["stats"]["total_tokens"] == 60
    assert len(body["calls"]) == 1
    assert OPAQUE_CURSOR not in json.dumps(body)
    assert state["active_window"] is None
    monitoring = await api_get(api, "/api/guardian/monitoring")
    assert OPAQUE_CURSOR not in monitoring.text
    assert "active_window" not in monitoring.text
    assert "private-cursor" not in caplog.text
    expected_auth = "Basic " + base64.b64encode(b"test-public:test-secret").decode()
    assert all(request.url.path == SOURCE_PATH for request in calls)
    assert all(request.headers["Authorization"] == expected_auth for request in calls)
    assert all(request.url.params["limit"] == "100" for request in calls)
    assert all(request.url.params["type"] == "GENERATION" for request in calls)
    assert all({"usage", "metrics", "trace_context"} <= set(request.url.params["fields"].split(",")) for request in calls)


@pytest.mark.anyio
async def test_v2_terminal_empty_window_is_successful_empty_traffic(
    worker, database, api, monkeypatch, source_factory
):
    import api.routes as routes

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})

    source = source_factory(handler)
    previous = await seed_cursor(worker, database)
    await worker.poll_once(source)
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["last_polled_at"] != previous
    assert state["read_status"] == "complete"
    assert state["records_read"] == 0
    assert await database.guardian_metrics.count_documents({}) == 0

    monkeypatch.setattr(routes, "_live", LiveTraceReader(source))
    response = await api_get(api, "/api/guardian/live")
    response.raise_for_status()
    assert response.json()["stats"]["call_count"] == 0
    assert response.json()["calls"] == []
    assert len(requests) == 2
    assert all(request.url.path == SOURCE_PATH for request in requests)


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "error_code"), [
    (401, "authentication_failed"), (403, "authentication_failed"),
    (404, "unsupported_api"), (429, "rate_limited"), (500, "upstream_error"),
])
async def test_v2_upstream_failures_stop_worker_and_return_unavailable_without_fallback(
    status, error_code, worker, database, api, monkeypatch, source_factory, caplog
):
    import api.routes as routes

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"message": PRIVATE_BODY})

    source = source_factory(handler)
    previous = await seed_cursor(worker, database)
    assert await worker.poll_once(source) == 0
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous
    assert state["read_status"] == "failed"
    assert state["read_error_code"] == error_code
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_incidents.count_documents({}) == 0

    monkeypatch.setattr(routes, "_live", LiveTraceReader(source))
    response = await api_get(api, "/api/guardian/live")
    response.raise_for_status()
    body = response.json()
    assert body["available"] is True
    assert body["degraded"] is True
    assert body["stats"] is None
    assert body["coverage"]["status"] == "failed"
    assert body["coverage"]["reason"] == error_code
    run_response = await api_get(api, "/api/guardian/live/runs/workflow-1")
    assert run_response.status_code == 503
    assert calls and all(request.url.path == SOURCE_PATH for request in calls)
    assert PRIVATE_BODY not in response.text + run_response.text + json.dumps(state) + caplog.text
    assert "test-secret" not in response.text + run_response.text + json.dumps(state) + caplog.text


@pytest.mark.anyio
async def test_v2_absent_run_is_a_bounded_empty_view_with_exact_source_filter(
    api, monkeypatch, source_factory
):
    import api.routes as routes

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})

    monkeypatch.setattr(routes, "_live", LiveTraceReader(source_factory(handler)))
    response = await api_get(api, "/api/guardian/live/runs/absent-workflow")

    response.raise_for_status()
    body = response.json()
    assert body["calls"] == []
    assert body["coverage"]["status"] == "complete"
    assert body["observation_state"] == "not_observed"
    assert body["workflow_status"] == "unknown"
    assert body["window_hours"] == 168
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == SOURCE_PATH
    assert request.url.params["traceId"] == "absent-workflow"
    start = datetime.fromisoformat(request.url.params["fromStartTime"])
    end = datetime.fromisoformat(request.url.params["toStartTime"])
    assert end - start == timedelta(days=7)
    assert start > NOW - timedelta(days=8)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [
    "cursor_cycle", "empty_continuation", "invalid_cursor", "missing_metadata",
    "later_page_failure",
])
async def test_v2_failed_later_page_preserves_durable_work_without_advancing_watermark(
    failure, worker, database, api, source_factory, caplog
):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "data": [observation("first")], "meta": {"cursor": OPAQUE_CURSOR},
            })
        assert len(calls) <= 3, "A non-progressing traversal must stop promptly"
        if failure == "later_page_failure":
            return httpx.Response(503, json={"message": PRIVATE_BODY})
        payload = {"data": [observation("second")], "meta": {}}
        if failure == "cursor_cycle":
            payload["meta"] = {"cursor": OPAQUE_CURSOR}
        elif failure == "empty_continuation":
            payload = {"data": [], "meta": {"cursor": "different-private-cursor"}}
        elif failure == "invalid_cursor":
            payload["meta"] = {"cursor": {"secret": PRIVATE_BODY}}
        elif failure == "missing_metadata":
            del payload["meta"]
        return httpx.Response(200, json=payload)

    previous = await seed_cursor(worker, database)
    assert await worker.poll_once(source_factory(handler)) == 0

    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous
    assert state["processing_status"] == "read_blocked"
    assert state["read_status"] == "failed"
    assert state["read_error_code"]
    assert state.get("source_watermark") is None
    assert state["active_window"]["cursor"] == OPAQUE_CURSOR
    assert state["active_window"]["page"] == 1
    assert await database.guardian_observations.count_documents({"state": "accepted", "pending": True}) == 1
    assert await database.guardian_page_receipts.count_documents({}) == 1
    assert await database.guardian_quarantine.count_documents({}) == 0
    # The accepted page is durable before downstream materialization; the next
    # poll can recover it even if the source remains unavailable.
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_incidents.count_documents({}) == 0
    assert 2 <= len(calls) <= 3
    assert PRIVATE_BODY not in json.dumps(state) + caplog.text
    monitoring = await api_get(api, "/api/guardian/monitoring")
    assert OPAQUE_CURSOR not in monitoring.text + caplog.text
    assert "active_window" not in monitoring.text


@pytest.mark.anyio
@pytest.mark.parametrize("disposition", ["replayed", "quarantined"])
async def test_v2_valid_terminal_page_durably_disposes_duplicate_or_invalid_row(
    disposition, worker, database, api, source_factory
):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={
                "data": [observation("first")], "meta": {"cursor": OPAQUE_CURSOR},
            })
        row = observation("first") if disposition == "replayed" else observation("second", id="")
        return httpx.Response(200, json={"data": [row], "meta": {}})

    previous = await seed_cursor(worker, database)
    await worker.poll_once(source_factory(handler))
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert len(calls) == 2
    assert state["last_polled_at"] != previous
    assert state["source_watermark"] == calls[0].url.params["toStartTime"]
    assert state["active_window"] is None
    assert state["read_status"] == ("complete" if disposition == "replayed" else "partial")
    assert state["read_error_code"] == (None if disposition == "replayed" else "quarantined_observations")
    assert state["duplicate_count"] == (1 if disposition == "replayed" else 0)
    assert state["invalid_count"] == (1 if disposition == "quarantined" else 0)
    assert await database.guardian_observations.count_documents({"state": "accepted"}) == 1
    assert await database.guardian_page_receipts.count_documents({}) == 2
    assert await database.guardian_quarantine.count_documents({}) == (1 if disposition == "quarantined" else 0)
    metrics = await api_get(api, "/api/guardian/metrics")
    metrics.raise_for_status()
    assert sum(row["call_count"] for row in metrics.json()) == 1
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(0.75)
    assert sum(row["total_tokens"] for row in metrics.json()) == 20


@pytest.mark.anyio
@pytest.mark.parametrize("has_more", [False, True])
async def test_v2_exact_worker_page_budget_persists_progress_and_only_checkpoints_terminal(
    has_more, worker, database, api, source_factory
):
    calls = []

    def handler(request):
        calls.append(request)
        page_index = len(calls) - 1
        assert page_index < 5, "The source row budget must bound network pages"
        data = [observation(str(index)) for index in range(page_index * 100, (page_index + 1) * 100)]
        more = page_index < 4 or has_more
        return httpx.Response(200, json={
            "data": data, "meta": {"cursor": "continue-" + str(page_index)} if more else {},
        })

    previous = await seed_cursor(worker, database)
    await worker.poll_once(source_factory(handler))
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert len(calls) == 5
    assert all(request.url.params["limit"] == "100" for request in calls)
    assert await database.guardian_observations.count_documents({"state": "accepted"}) == 500
    assert await database.guardian_page_receipts.count_documents({}) == 5
    assert state["processing_status"] == "pending"
    response = await api_get(api, "/api/guardian/metrics")
    response.raise_for_status()
    assert sum(row["call_count"] for row in response.json()) == 500
    assert sum(row["total_cost_usd"] for row in response.json()) == pytest.approx(375)
    if has_more:
        assert state["last_polled_at"] == previous
        assert state["read_status"] == "pending"
        assert state["read_error_code"] is None
        assert state.get("source_watermark") is None
        assert state["active_window"]["cursor"] == "continue-4"
    else:
        assert state["last_polled_at"] != previous
        assert state["read_status"] == "complete"
        assert state["source_watermark"] == calls[0].url.params["toStartTime"]
        assert state["active_window"] is None


@pytest.mark.anyio
async def test_v2_more_than_500_rows_resume_with_fresh_client_and_overlap_does_not_inflate(
    worker, database, api, source_factory, caplog
):
    caplog.set_level(logging.INFO, logger="httpx")
    calls = []

    def handler(request):
        calls.append(request)
        cursor = request.url.params.get("cursor")
        index = 0 if cursor is None else int(cursor.removeprefix("private-page-"))
        assert 0 <= index <= 5
        return httpx.Response(200, json={
            "data": [observation(str(number)) for number in range(index * 100, (index + 1) * 100)],
            "meta": {"cursor": "private-page-" + str(index + 1)} if index < 5 else {},
        })

    previous = await seed_cursor(worker, database)
    await worker.poll_once(source_factory(handler))
    first = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    window = dict(first["active_window"])
    assert len(calls) == 5
    assert first["last_polled_at"] == previous
    assert first["read_status"] == "pending"
    assert window["cursor"] == "private-page-5"
    assert await database.guardian_observations.count_documents({}) == 500

    # A new HTTP/source instance has no in-memory traversal history to lean on.
    await worker.poll_once(source_factory(handler))
    second = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert len(calls) == 6
    assert calls[5].url.params["cursor"] == window["cursor"]
    assert {call.url.params["fromStartTime"] for call in calls} == {window["start"]}
    assert {call.url.params["toStartTime"] for call in calls} == {window["end"]}
    assert second["active_window"] is None
    assert second["source_watermark"] == second["last_polled_at"] == window["end"]
    assert second["read_status"] == "complete"
    assert second["processing_status"] == "pending"
    assert second["pending_observations"] > 0
    assert second.get("processing_watermark") is None
    assert await database.guardian_observations.count_documents({}) == 600
    assert await database.guardian_page_receipts.count_documents({}) == 6
    metrics = await api_get(api, "/api/guardian/metrics")
    assert sum(row["call_count"] for row in metrics.json()) == 600
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(450)
    assert sum(row["total_tokens"] for row in metrics.json()) == 12000

    # The next overlapping window re-reads all 600 source identities. Both its
    # bounded continuation and final checkpoint must preserve exact totals.
    await worker.poll_once(source_factory(handler))
    await worker.poll_once(source_factory(handler))
    final = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert len(calls) == 12
    assert final["active_window"] is None
    assert final["read_status"] == "complete"
    # Detector work has its own bounded budget and only evaluates after the
    # source window is complete. Accounting completion cannot imply it is done.
    assert final["processing_status"] == "pending"
    assert 0 < final["pending_observations"] < second["pending_observations"]
    assert final.get("processing_watermark") is None
    assert await database.guardian_observations.count_documents({}) == 600
    assert await database.guardian_quarantine.count_documents({}) == 0
    metrics = await api_get(api, "/api/guardian/metrics")
    assert sum(row["call_count"] for row in metrics.json()) == 600
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(450)
    assert sum(row["total_tokens"] for row in metrics.json()) == 12000
    monitoring = await api_get(api, "/api/guardian/monitoring")
    assert "private-page-" not in monitoring.text + caplog.text
    assert "active_window" not in monitoring.text


@pytest.mark.anyio
async def test_v2_prior_page_materializes_on_retry_while_source_remains_unavailable(
    worker, database, api, source_factory
):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "data": [observation()], "meta": {"cursor": OPAQUE_CURSOR},
            })
        assert request.url.params["cursor"] == OPAQUE_CURSOR
        return httpx.Response(503, json={"message": PRIVATE_BODY})

    previous = await seed_cursor(worker, database)
    source = source_factory(handler)
    await worker.poll_once(source)
    assert await database.guardian_metrics.count_documents({}) == 0
    assert await database.guardian_observations.count_documents({"pending": True}) == 1
    await worker.poll_once(source)
    assert len(calls) == 3
    state = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert state["last_polled_at"] == previous
    assert state.get("source_watermark") is None
    assert state["active_window"]["cursor"] == OPAQUE_CURSOR
    assert state["read_status"] == "failed"
    assert state["read_error_code"] == "upstream_error"
    # Metrics can recover immediately, while detectors retain pending work until
    # later source pages have supplied the candidate's complete bounded baseline.
    assert await database.guardian_observations.count_documents({"pending": True}) == 1
    assert await database.guardian_incidents.count_documents({}) == 0
    assert await database.guardian_page_receipts.count_documents({}) == 1
    metrics = await api_get(api, "/api/guardian/metrics")
    assert sum(row["call_count"] for row in metrics.json()) == 1
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(0.75)
    assert sum(row["total_tokens"] for row in metrics.json()) == 20


@pytest.mark.anyio
async def test_v2_quarantined_page_does_not_prevent_later_valid_observations(
    worker, database, api, monkeypatch, source_factory
):
    monkeypatch.setattr(worker, "SOURCE_ROW_LIMIT", 100)
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={
                "data": [observation("broken", startTime="not-a-timestamp", output=PRIVATE_BODY)],
                "meta": {"cursor": OPAQUE_CURSOR},
            })
        assert request.url.params["cursor"] == OPAQUE_CURSOR
        return httpx.Response(200, json={"data": [observation("valid")], "meta": {}})

    previous = await seed_cursor(worker, database)
    await worker.poll_once(source_factory(handler))
    first = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert first["last_polled_at"] == previous
    assert first["active_window"]["cursor"] == OPAQUE_CURSOR
    assert first["read_status"] == "partial"
    assert first["read_error_code"] == "quarantined_observations"
    assert await database.guardian_quarantine.count_documents({}) == 1
    await worker.poll_once(source_factory(handler))
    second = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert second["active_window"] is None
    assert second["source_watermark"] == first["active_window"]["end"]
    assert second["read_status"] == "partial"
    assert second["read_error_code"] == "quarantined_observations"
    assert second["quarantined_records"] == 1
    assert await database.guardian_observations.count_documents({"state": "accepted"}) == 1
    assert await database.guardian_page_receipts.count_documents({}) == 2
    metrics = await api_get(api, "/api/guardian/metrics")
    assert sum(row["call_count"] for row in metrics.json()) == 1
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(0.75)
    assert sum(row["total_tokens"] for row in metrics.json()) == 20
    quarantined = await database.guardian_quarantine.find({}).to_list(length=10)
    assert PRIVATE_BODY not in json.dumps(quarantined, default=str)
    assert "not-a-timestamp" not in json.dumps(quarantined, default=str)


@pytest.mark.anyio
@pytest.mark.parametrize("reject_twice", [False, True])
async def test_v2_rejected_cursor_restarts_same_query_once_and_replay_is_idempotent(
    reject_twice, worker, database, api, monkeypatch, source_factory
):
    monkeypatch.setattr(worker, "SOURCE_ROW_LIMIT", 100)
    calls = []
    rejected = 0

    def handler(request):
        nonlocal rejected
        calls.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(200, json={
                "data": [observation("first")], "meta": {"cursor": OPAQUE_CURSOR},
            })
        assert request.url.params["cursor"] == OPAQUE_CURSOR
        if rejected == 0 or reject_twice:
            rejected += 1
            return httpx.Response(400, json={"message": PRIVATE_BODY})
        return httpx.Response(200, json={"data": [observation("second")], "meta": {}})

    previous = await seed_cursor(worker, database)
    source = source_factory(handler)
    await worker.poll_once(source)
    original = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    window = dict(original["active_window"])
    await worker.poll_once(source)
    restarted = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert restarted["active_window"]["cursor"] is None
    assert restarted["active_window"]["query_fingerprint"] == window["query_fingerprint"]
    assert restarted["active_window"]["restarts"] == 1
    assert restarted["last_polled_at"] == previous
    await worker.poll_once(source)
    replayed = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert replayed["duplicate_count"] == 1
    assert await database.guardian_observations.count_documents({}) == 1
    await worker.poll_once(source)
    final = await database.guardian_state.find_one({"_id": worker.CURSOR_DOC_ID})
    assert len(calls) == 4
    assert {call.url.params["fromStartTime"] for call in calls} == {window["start"]}
    assert {call.url.params["toStartTime"] for call in calls} == {window["end"]}
    if reject_twice:
        assert final["read_status"] == "failed"
        assert final["read_error_code"] == "invalid_query"
        assert final["active_window"]["restarts"] == 1
        assert final["active_window"]["cursor"] == OPAQUE_CURSOR
        assert final["last_polled_at"] == previous
        assert final.get("source_watermark") is None
    else:
        assert final["read_status"] == "complete"
        assert final["active_window"] is None
        assert final["last_polled_at"] == final["source_watermark"] == window["end"]
    count = 1 if reject_twice else 2
    assert await database.guardian_observations.count_documents({}) == count
    assert await database.guardian_quarantine.count_documents({}) == 0
    metrics = await api_get(api, "/api/guardian/metrics")
    assert sum(row["call_count"] for row in metrics.json()) == count
    assert sum(row["total_cost_usd"] for row in metrics.json()) == pytest.approx(count * 0.75)
    assert sum(row["total_tokens"] for row in metrics.json()) == count * 20


@pytest.mark.anyio
@pytest.mark.parametrize("partial_top_total", [0, 12])
async def test_v2_default_aggregate_zeroes_do_not_fabricate_measurement_coverage(
    partial_top_total, worker, database, api, source_factory
):
    # Upstream v2 computes aggregate fields with zero defaults even when their
    # detailed maps are empty. Explicit detail zero remains an actual measurement.
    # A contradictory positive top-level total must not override a partial map.
    rows = [
        observation("unmeasured", usageDetails={}, inputUsage=0, outputUsage=0,
                    totalUsage=0, costDetails={}, totalCost=0),
        observation("measured-zero", usageDetails={"input": 0, "output": 0, "total": 0},
                    inputUsage=0, outputUsage=0, totalUsage=0,
                    costDetails={"total": 0}, totalCost=0),
        observation("partial-usage", usageDetails={"input": 12}, inputUsage=12,
                    outputUsage=0, totalUsage=partial_top_total, costDetails={"total": 0}, totalCost=0),
    ]
    source = source_factory(lambda request: httpx.Response(200, json={"data": rows, "meta": {}}))
    await seed_cursor(worker, database)
    await worker.poll_once(source)

    response = await api_get(api, "/api/guardian/metrics")
    response.raise_for_status()
    row = response.json()[0]
    assert row["call_count"] == 3
    assert row["total_cost_usd"] is None
    assert row["known_cost_usd"] == 0
    assert (row["cost_known_count"], row["cost_unknown_count"]) == (2, 1)
    assert row["total_tokens"] is None
    assert row["known_total_tokens"] == 0
    assert (row["tokens_known_count"], row["tokens_unknown_count"]) == (1, 2)
