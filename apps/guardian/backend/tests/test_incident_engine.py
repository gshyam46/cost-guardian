import pytest

from guardian.detectors.base import DetectorResult
from guardian.incident_engine import process_detector_results
from guardian.store import InMemoryIncidentStore

pytestmark = pytest.mark.anyio


def _result(detector="cost_anomaly", trace_id="t1", triggered=True):
    return DetectorResult(
        triggered=triggered,
        detector=detector,
        trace_ids=[trace_id] if trace_id else [],
        severity="high",
        title="Cost spike",
        summary="spiked",
        evidence={"cost_usd": 1.0},
        agent_name="profile_analyst",
    )


async def test_creates_incident_for_triggered_result():
    store = InMemoryIncidentStore()

    created = await process_detector_results([_result()], store)

    assert len(created) == 1
    open_incidents = await store.list_open()
    assert len(open_incidents) == 1
    assert open_incidents[0].evidence == {"cost_usd": 1.0}
    assert open_incidents[0].status == "open"


async def test_ignores_non_triggered_results():
    store = InMemoryIncidentStore()

    created = await process_detector_results([_result(triggered=False)], store)

    assert created == []
    assert await store.list_open() == []


async def test_dedupes_same_detector_and_trace():
    store = InMemoryIncidentStore()

    await process_detector_results([_result(trace_id="t1")], store)
    created_again = await process_detector_results([_result(trace_id="t1")], store)

    assert created_again == []
    assert len(await store.list_open()) == 1


async def test_does_not_dedupe_different_traces():
    store = InMemoryIncidentStore()

    await process_detector_results([_result(trace_id="t1")], store)
    created_second = await process_detector_results([_result(trace_id="t2")], store)

    assert len(created_second) == 1
    assert len(await store.list_open()) == 2


async def test_skips_result_with_no_trace_ids():
    store = InMemoryIncidentStore()

    created = await process_detector_results([_result(trace_id=None)], store)

    assert created == []


async def test_resolve_removes_incident_from_open_list():
    store = InMemoryIncidentStore()
    created = await process_detector_results([_result(trace_id="t1")], store)

    await store.resolve(created[0].id)

    assert await store.list_open() == []
    resolved = await store.get(created[0].id)
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
