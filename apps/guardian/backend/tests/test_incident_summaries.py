"""Incident summary acceptance through authenticated ASGI routes.

These fixtures use mocked persistence, not a real Mongo query planner or server.
The real-database suite separately establishes aggregation/operator support.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import OperationFailure


NOW = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
HEADERS = {"X-Guardian-Key": "incident-summary-test-key"}


class CursorWithMotorListLimit:
    """mongomock-motor ignores to_list(length); preserve the real driver cap."""
    def __init__(self, cursor):
        self.cursor = cursor

    def __aiter__(self):
        return self.cursor.__aiter__()

    def sort(self, *args, **kwargs):
        return type(self)(self.cursor.sort(*args, **kwargs))

    def limit(self, *args, **kwargs):
        return type(self)(self.cursor.limit(*args, **kwargs))

    async def to_list(self, length=None):
        rows = await self.cursor.to_list(length)
        return rows if length is None else rows[:length]


class CollectionWithMotorListLimit:
    def __init__(self, collection):
        self.collection = collection

    def __getattr__(self, name):
        return getattr(self.collection, name)

    def find(self, *args, **kwargs):
        return CursorWithMotorListLimit(self.collection.find(*args, **kwargs))

    def aggregate(self, *args, **kwargs):
        return CursorWithMotorListLimit(self.collection.aggregate(*args, **kwargs))


@pytest.fixture
def environment(monkeypatch):
    import api.routes as routes
    import auth
    from server import app

    database = AsyncMongoMockClient()["guardian_incident_summaries_test"]
    clock = SimpleNamespace(now=NOW)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    monkeypatch.setattr(routes, "datetime", FixedDatetime)
    monkeypatch.setattr(routes, "db", SimpleNamespace(
        guardian_incidents=CollectionWithMotorListLimit(database.guardian_incidents),
        guardian_state=database.guardian_state,
    ))
    monkeypatch.setattr(auth, "GUARDIAN_API_KEY", HEADERS["X-Guardian-Key"])
    return app, routes, database, clock


def incident(identifier, *, at=NOW - timedelta(minutes=1), status="open", detector="cost_anomaly", severity="high"):
    return {
        "_id": identifier, "id": identifier, "status": status,
        "detector": detector, "severity": severity,
        "created_at": at.isoformat() if isinstance(at, datetime) else at,
        "created_at_utc": at, "summary_schema": 1,
        "title": "Synthetic finding", "summary": "Fixture",
        "evidence": {}, "trace_ids": [f"trace-{identifier}"],
    }


async def request(app, path, *, headers=HEADERS):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/guardian{path}", headers=headers)


@pytest.mark.anyio
async def test_overview_counts_every_open_incident_and_exact_breakdowns(environment):
    app, _, database, _ = environment
    rows = [incident(f"cost-{n}") for n in range(700)]
    rows += [incident(f"error-{n}", detector="reliability_anomaly", severity="medium") for n in range(600)]
    rows += [incident(f"pii-{n}", detector="pii", severity="low") for n in range(27)]
    rows += [incident(f"resolved-{n}", status="resolved") for n in range(41)]
    await database.guardian_incidents.insert_many(rows)

    response = await request(app, "/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["open_incidents"] == 1327
    assert body["open_by_severity"] == {"high": 700, "medium": 600, "low": 27}
    assert body["open_by_detector"] == {"cost_anomaly": 700, "reliability_anomaly": 600, "pii": 27}
    assert body["incidents_last_7_days"] == 1368
    assert sum(body["open_by_severity"].values()) == body["open_incidents"]
    assert sum(body["open_by_detector"].values()) == body["open_incidents"]


@pytest.mark.anyio
async def test_trend_counts_every_matching_incident_beyond_ten_thousand(environment):
    app, _, database, _ = environment
    yesterday = NOW - timedelta(days=1)
    await database.guardian_incidents.insert_many([
        incident(f"bulk-{n}", at=yesterday, status="resolved" if n % 2 else "open")
        for n in range(10007)
    ])

    response = await request(app, "/trends?days=3")
    assert response.status_code == 200
    counts = {point["date"]: point["count"] for point in response.json()}
    assert counts[yesterday.date().isoformat()] == 10007
    assert sum(counts.values()) == 10007


@pytest.mark.anyio
@pytest.mark.parametrize("current", [
    datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
    datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc),
    datetime(2026, 5, 1, 23, 59, tzinfo=timezone.utc),
])
async def test_trends_are_utc_calendar_days_including_today_across_boundaries(environment, current):
    app, _, database, clock = environment
    clock.now = current
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=2)
    await database.guardian_incidents.insert_many([
        incident("start-included", at=start),
        incident("one-millisecond-before", at=start - timedelta(milliseconds=1)),
        incident("yesterday", at=midnight - timedelta(hours=1)),
        incident("today-midnight", at=midnight),
        incident("as-of-excluded", at=current),
        incident("future-excluded", at=current + timedelta(milliseconds=1)),
    ])

    response = await request(app, "/trends?days=3")
    assert response.status_code == 200
    assert response.json() == [
        {"date": start.date().isoformat(), "count": 1},
        {"date": (start + timedelta(days=1)).date().isoformat(), "count": 1},
        {"date": midnight.date().isoformat(), "count": 1},
    ]


@pytest.mark.anyio
async def test_recent_overview_excludes_future_incidents_without_hiding_open_status(environment):
    app, _, database, _ = environment
    await database.guardian_incidents.insert_many([
        incident("current"), incident("future", at=NOW + timedelta(days=1)),
    ])
    response = await request(app, "/overview")
    assert response.status_code == 200
    assert response.json()["open_incidents"] == 2
    assert response.json()["incidents_last_7_days"] == 1


@pytest.mark.anyio
async def test_recent_overview_uses_same_seven_utc_calendar_days_as_trend(environment):
    app, _, database, _ = environment
    start = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    await database.guardian_incidents.insert_many([
        incident("first-day-midnight", at=start),
        incident("previous-calendar-day", at=start - timedelta(milliseconds=1)),
        incident("recent", status="resolved"),
        incident("exact-as-of", at=NOW),
    ])
    overview = await request(app, "/overview")
    trends = await request(app, "/trends?days=7")
    assert overview.status_code == trends.status_code == 200
    assert overview.json()["incidents_last_7_days"] == 2
    assert sum(point["count"] for point in trends.json()) == 2


@pytest.mark.anyio
async def test_summary_returns_coherent_coverage_and_requested_window(environment):
    app, _, database, _ = environment
    await database.guardian_incidents.insert_many([
        incident("recent-open"),
        incident("recent-resolved", status="resolved"),
        incident("five-days-old", at=NOW - timedelta(days=5)),
        incident("older-than-week", at=NOW - timedelta(days=8)),
    ])
    response = await request(app, "/summary?days=3")
    assert response.status_code == 200
    body = response.json()
    assert body["overview"] == {
        "open_incidents": 3,
        "open_by_severity": {"high": 3},
        "open_by_detector": {"cost_anomaly": 3},
        "incidents_last_7_days": 3,
    }
    assert body["trends"] == [
        {"date": "2025-12-30", "count": 0},
        {"date": "2025-12-31", "count": 0},
        {"date": "2026-01-01", "count": 2},
    ]
    assert body["coverage"] == {"status": "complete", "invalid_timestamp_count": 0}
    assert body["timezone"] == "UTC"
    assert datetime.fromisoformat(body["as_of"]) == NOW
    assert datetime.fromisoformat(body["window_end"]) == NOW
    assert datetime.fromisoformat(body["window_start"]) == datetime(2025, 12, 30, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_summary_uses_millisecond_half_open_cutoff(environment):
    app, _, database, clock = environment
    clock.now = NOW.replace(microsecond=123456)
    await database.guardian_incidents.insert_many([
        incident("before-cutoff", at=NOW.replace(microsecond=122000)),
        incident("at-cutoff", at=NOW.replace(microsecond=123000)),
        incident("after-cutoff", at=NOW.replace(microsecond=124000)),
    ])
    response = await request(app, "/summary?days=1")
    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["as_of"]) == NOW.replace(microsecond=123000)
    assert body["overview"]["incidents_last_7_days"] == 1
    assert body["trends"] == [{"date": "2026-01-01", "count": 1}]


@pytest.mark.anyio
async def test_summary_unknown_categories_remain_counted_without_unbounded_keys(environment):
    app, _, database, _ = environment
    rows = [incident("known")]
    rows += [incident(f"custom-{n}", severity=f"custom-severity-{n}", detector=f"custom-detector-{n}") for n in range(70)]
    rows += [incident("nulls", severity=None, detector=None)]
    rows += [incident("containers", severity=["high"], detector={"rule": "cost_anomaly"})]
    missing = incident("missing")
    del missing["severity"], missing["detector"]
    rows.append(missing)
    await database.guardian_incidents.insert_many(rows)

    response = await request(app, "/summary")
    assert response.status_code == 200
    overview = response.json()["overview"]
    assert overview["open_incidents"] == 74
    assert overview["open_by_severity"] == {"high": 1, "unknown": 73}
    assert overview["open_by_detector"] == {"cost_anomaly": 1, "unknown": 73}


@pytest.mark.anyio
async def test_real_incident_store_writes_feed_summary_and_keep_public_iso_dates(environment):
    from guardian.incident import Incident
    from guardian.store import MongoIncidentStore

    app, _, database, _ = environment
    source_time = (NOW - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    store = MongoIncidentStore(database)
    first = Incident(id="ordinary-save", detector="cost_anomaly", severity="high",
                     title="Synthetic cost finding", summary="Fixture", created_at=source_time)
    second = Incident(id="stable-insert", detector="reliability_anomaly", severity="medium",
                      title="Synthetic failure", summary="Fixture", created_at=source_time)
    await store.save(first)
    assert await store.create_if_absent(second) is True
    assert await store.create_if_absent(second) is False

    summary = await request(app, "/summary?days=1")
    assert summary.status_code == 200
    assert summary.json()["overview"]["incidents_last_7_days"] == 2
    assert summary.json()["trends"] == [{"date": "2026-01-01", "count": 2}]
    detail = await request(app, "/incidents/stable-insert")
    assert detail.status_code == 200
    assert datetime.fromisoformat(detail.json()["created_at"]) == source_time
    assert "created_at_utc" not in detail.json()
    assert "summary_schema" not in detail.json()


class FailingCollection:
    """Fail each real collection read boundary with sensitive backend diagnostics."""
    def __init__(self, failure_stage="aggregate"):
        self.failure_stage = failure_stage

    async def create_index(self, *args, **kwargs):
        return "fixture-index"

    def find(self, *args, **kwargs):
        raise OperationFailure("mongodb://private.invalid/database credential-fixture")

    def aggregate(self, *args, **kwargs):
        if self.failure_stage == "cursor":
            return self
        raise OperationFailure("mongodb://private.invalid/database credential-fixture")

    async def to_list(self, *args, **kwargs):
        raise OperationFailure("mongodb://private.invalid/database credential-fixture")

    async def count_documents(self, *args, **kwargs):
        raise OperationFailure("mongodb://private.invalid/database credential-fixture")


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/overview", "/trends?days=7", "/summary?days=7"])
@pytest.mark.parametrize("failure_stage", ["aggregate", "cursor"])
async def test_summary_failure_is_unavailable_and_never_successful_zero(environment, monkeypatch, caplog, path, failure_stage):
    app, routes, _, _ = environment
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=FailingCollection(failure_stage)))
    response = await request(app, path)
    assert response.status_code == 503
    assert "private.invalid" not in response.text
    assert "credential-fixture" not in response.text
    assert "private.invalid" not in caplog.text
    assert "credential-fixture" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/overview", "/trends?days=7", "/summary?days=7"])
@pytest.mark.parametrize("headers", [{}, {"X-Guardian-Key": "wrong-key"}])
async def test_summary_auth_rejects_before_database_access(environment, monkeypatch, path, headers):
    app, routes, _, _ = environment
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=FailingCollection()))
    response = await request(app, path, headers=headers)
    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("days", ["0", "91", "many"])
async def test_summary_rejects_unsupported_day_windows_before_database_access(environment, monkeypatch, days):
    app, routes, _, _ = environment
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=FailingCollection()))
    response = await request(app, f"/summary?days={days}")
    assert response.status_code == 422


class BlockedCollection:
    def __init__(self):
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = asyncio.Event()

    async def create_index(self, *args, **kwargs):
        return "fixture-index"

    def aggregate(self, *args, **kwargs):
        return self

    async def to_list(self, *args, **kwargs):
        self.entered.set()
        try:
            await self.release.wait()
            raise AssertionError("This query must be cancelled before it produces a summary")
        finally:
            self.finished.set()


@pytest.mark.anyio
async def test_slow_summary_is_unavailable_and_releases_awaited_cursor(environment, monkeypatch):
    import guardian.summaries as summaries

    app, routes, _, _ = environment
    collection = BlockedCollection()
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=collection))
    monkeypatch.setattr(summaries, "WAIT_SECONDS", 0.02)
    response = await request(app, "/summary")
    assert response.status_code == 503
    assert collection.entered.is_set()
    assert collection.finished.is_set()


@pytest.mark.anyio
async def test_cancelled_summary_does_not_continue_computing_or_return_empty_success(environment, monkeypatch):
    app, routes, _, _ = environment
    collection = BlockedCollection()
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=collection))
    pending = asyncio.create_task(request(app, "/summary"))
    try:
        await asyncio.wait_for(collection.entered.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=1)
        await asyncio.wait_for(collection.finished.wait(), timeout=1)
    finally:
        collection.release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
async def test_failed_index_setup_can_retry_and_successful_reads_do_not_repeat_setup(environment, monkeypatch):
    app, routes, database, _ = environment

    class InitiallyUnavailableIndexes(CollectionWithMotorListLimit):
        attempts = 0

        async def create_index(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise OperationFailure("Temporary fixture setup failure")
            return await self.collection.create_index(*args, **kwargs)

    await database.guardian_incidents.insert_one(incident("retained-during-setup-outage"))
    collection = InitiallyUnavailableIndexes(database.guardian_incidents)
    monkeypatch.setattr(routes, "db", SimpleNamespace(guardian_state=routes.db.guardian_state, guardian_incidents=collection))
    failed = await request(app, "/summary?days=1")
    assert failed.status_code == 503
    recovered = await request(app, "/summary?days=1")
    assert recovered.status_code == 200
    assert recovered.json()["overview"]["open_incidents"] == 1
    attempts_after_success = collection.attempts
    again = await request(app, "/summary?days=1")
    assert again.status_code == 200
    assert collection.attempts == attempts_after_success
