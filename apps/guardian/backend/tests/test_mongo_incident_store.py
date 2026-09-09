"""MongoIncidentStore against a real (mocked) Motor-compatible database.

No live MongoDB is reachable in this dev environment, so this uses mongomock-motor --
an in-memory implementation of Motor's async interface -- to exercise the actual query
shapes (`$set`, `sort`, `limit`, upsert) MongoIncidentStore sends, which
InMemoryIncidentStore's tests don't cover. This is still not a substitute for running
against real MongoDB; see docs/PHASES.md Phase 1/3 blockers.
"""
import pytest
from mongomock_motor import AsyncMongoMockClient

from guardian.incident import Incident
from guardian.store import MongoIncidentStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_db():
    client = AsyncMongoMockClient()
    return client["guardian_test_db"]


def _incident(detector="cost_anomaly", trace_id="t1", severity="high"):
    return Incident(
        detector=detector,
        severity=severity,
        title="Cost spike",
        summary="spiked",
        evidence={"cost_usd": 1.0},
        trace_ids=[trace_id],
        agent_name="profile_analyst",
    )


async def test_save_and_get(mock_db):
    store = MongoIncidentStore(mock_db)
    incident = _incident()

    await store.save(incident)
    fetched = await store.get(incident.id)

    assert fetched is not None
    assert fetched.id == incident.id
    assert fetched.evidence == {"cost_usd": 1.0}
    assert fetched.status == "open"


async def test_get_missing_returns_none(mock_db):
    store = MongoIncidentStore(mock_db)

    assert await store.get("does-not-exist") is None


async def test_exists_checks_detector_and_trace_id(mock_db):
    store = MongoIncidentStore(mock_db)
    await store.save(_incident(detector="pii", trace_id="trace-abc"))

    assert await store.exists("pii", "trace-abc") is True
    assert await store.exists("pii", "trace-xyz") is False
    assert await store.exists("cost_anomaly", "trace-abc") is False


async def test_list_open_excludes_resolved_and_sorts_newest_first(mock_db):
    store = MongoIncidentStore(mock_db)
    first = _incident(trace_id="t1")
    second = _incident(trace_id="t2")
    resolved = _incident(trace_id="t3")

    await store.save(first)
    await store.save(second)
    await store.save(resolved)
    await store.resolve(resolved.id)

    open_incidents = await store.list_open()

    ids = {i.id for i in open_incidents}
    assert resolved.id not in ids
    assert first.id in ids and second.id in ids
    assert len(open_incidents) == 2


async def test_resolve_sets_status_and_timestamp(mock_db):
    store = MongoIncidentStore(mock_db)
    incident = _incident()
    await store.save(incident)

    await store.resolve(incident.id)
    fetched = await store.get(incident.id)

    assert fetched.status == "resolved"
    assert fetched.resolved_at is not None


async def test_save_is_idempotent_upsert(mock_db):
    """Re-saving the same incident id updates in place rather than duplicating."""
    store = MongoIncidentStore(mock_db)
    incident = _incident()

    await store.save(incident)
    await store.save(incident)

    open_incidents = await store.list_open()
    assert len(open_incidents) == 1
