"""Stable finding identity and insert-only lifecycle behavior.

Mongo tests use mongomock with explicit scheduling points. They check concurrent
application behavior and Mongo operation shape, not real database isolation,
transaction commit/abort behavior, or lease fencing.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError

from guardian.detectors import cost_anomaly, pii, reliability_anomaly
from guardian.detectors.base import DetectorResult
from guardian.incident_engine import process_detector_results, signal_id
from guardian.models import TraceMetric
from guardian.store import InMemoryIncidentStore, MongoIncidentStore


def result(**changes):
    finding = DetectorResult(
        triggered=True, detector="reliability_anomaly", trace_ids=["workflow-1"],
        observation_ids=["generation-1"], source="langfuse", project_id="project-1",
        rule_version="1", finding_kind="call_failure", agent_name="answer-agent",
        severity="high", title="Call failed", summary="Investigate this failure",
        evidence={"status": "error"},
    )
    return replace(finding, **changes)


def metric(identifier="generation-1", **changes):
    candidate = TraceMetric(
        trace_id="workflow-1", observation_id=identifier, source="langfuse",
        project_id="project-1", agent_name="answer-agent", model="test-model",
        cost_usd=0.01, total_tokens=10, latency_ms=1000, status="success",
        timestamp=datetime.now(timezone.utc),
    )
    return replace(candidate, **changes)


class SchedulingCollection:
    """Expose races that instantaneous mock I/O otherwise conceals."""

    def __init__(self, collection):
        self.collection = collection

    async def find_one(self, *args, **kwargs):
        value = await self.collection.find_one(*args, **kwargs)
        await asyncio.sleep(0)
        return value

    async def update_one(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await self.collection.update_one(*args, **kwargs)

    def find(self, *args, **kwargs):
        return self.collection.find(*args, **kwargs)


@pytest.fixture(params=["memory", "mongo"])
def store(request):
    if request.param == "memory":
        return InMemoryIncidentStore()
    database = AsyncMongoMockClient()["guardian_signal_identity"]
    return MongoIncidentStore(SimpleNamespace(
        guardian_incidents=SchedulingCollection(database.guardian_incidents),
    ))


@pytest.mark.anyio
async def test_concurrent_replay_creates_one_incident_even_when_narrative_changes(store):
    batches = await asyncio.gather(*(
        process_detector_results([result(title="Presentation " + str(index),
                                         evidence={"rendered_attempt": index})], store)
        for index in range(24)
    ))

    assert sum(len(batch) for batch in batches) == 1
    persisted = await store.list_open()
    assert len(persisted) == 1
    assert persisted[0].id == signal_id(result())


@pytest.mark.anyio
async def test_replay_preserves_resolved_status_time_and_original_evidence(store):
    created = await process_detector_results([result()], store)
    incident_id = created[0].id
    await store.resolve(incident_id)
    resolved = await store.get(incident_id)
    resolved_at = resolved.resolved_at

    created_again = await process_detector_results([
        result(title="New wording", evidence={"status": "error", "new_detail": 1}),
    ], store)

    assert created_again == []
    persisted = await store.get(incident_id)
    assert persisted.status == "resolved"
    assert persisted.resolved_at == resolved_at
    assert persisted.evidence == {"status": "error"}
    assert persisted.title == "Call failed"
    assert await store.list_open() == []


@pytest.mark.anyio
@pytest.mark.parametrize("agents", [("answer-agent", "answer-agent"), ("planner", "retriever")])
async def test_each_failed_observation_survives_even_inside_one_trace(store, agents):
    candidates = [metric("generation-" + str(index), agent_name=agent, status="error")
                  for index, agent in enumerate(agents)]

    created = await process_detector_results(reliability_anomaly.evaluate([], candidates), store)

    assert len(created) == 2
    assert len({incident.id for incident in created}) == 2
    assert sorted(incident.agent_name for incident in await store.list_open()) == sorted(agents)


@pytest.mark.anyio
async def test_legacy_callers_remain_compatible_without_inventing_observation_ids(store):
    legacy = result(observation_ids=[], project_id=None, finding_kind="anomaly")

    first = await process_detector_results([legacy], store)
    repeat = await process_detector_results([legacy], store)
    other_agent = await process_detector_results([replace(legacy, agent_name="other-agent")], store)

    assert len(first) == len(other_agent) == 1
    assert repeat == []
    assert legacy.observation_ids == []


@pytest.mark.parametrize("changes", [
    {"source": "another-source"}, {"project_id": "project-2"},
    {"trace_ids": ["workflow-2"]}, {"observation_ids": ["generation-2"]},
    {"detector": "another-detector"}, {"rule_version": "2"},
    {"finding_kind": "latency_regression"},
])
def test_source_and_rule_boundaries_produce_distinct_signal_ids(changes):
    assert signal_id(result()) != signal_id(result(**changes))


def test_connection_scope_and_canonical_lists_are_stable():
    first = result(trace_ids=["b", "a"], observation_ids=["two", "one"])
    reordered = result(trace_ids=["a", "b", "a"], observation_ids=["one", "two"])
    assert signal_id(first) == signal_id(reordered)
    assert signal_id(first, scope_id="connection-1") != signal_id(first, scope_id="connection-2")
    assert signal_id(result()) == signal_id(result(agent_name="renamed-agent"))
    # Delimiters in upstream IDs cannot collide by string concatenation.
    assert signal_id(result(trace_ids=["a|b"], observation_ids=["c"])) != signal_id(
        result(trace_ids=["a"], observation_ids=["b|c"]))


@pytest.mark.parametrize(("detector", "candidate", "kind"), [
    (cost_anomaly, metric(cost_usd=2), "cost_spike"),
    (reliability_anomaly, metric(status="error"), "call_failure"),
    (reliability_anomaly, metric(latency_ms=10000), "latency_regression"),
    (pii, metric(output_text="contact test@example.com"), "pii_pattern"),
])
def test_detectors_propagate_source_observation_and_versioned_finding_identity(detector, candidate, kind):
    baseline = [metric("baseline-" + str(index)) for index in range(6)]

    findings = detector.evaluate(baseline, [candidate])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.observation_ids == [candidate.observation_id]
    assert finding.source == candidate.source
    assert finding.project_id == candidate.project_id
    assert finding.rule_version == detector.RULE_VERSION
    assert finding.finding_kind == kind


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"trace_ids": [""]}, {"observation_ids": [""]}, {"source": ""},
    {"rule_version": ""}, {"finding_kind": ""}, {"trace_ids": "not-a-list"},
])
async def test_malformed_identity_is_not_persisted(changes):
    store = InMemoryIncidentStore()

    assert await process_detector_results([result(**changes)], store) == []
    assert await store.list_open() == []


@pytest.mark.anyio
async def test_store_forwards_the_transaction_session_without_claiming_mock_atomicity():
    session = object()
    collection = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(upserted_id="created")))
    store = MongoIncidentStore(SimpleNamespace(guardian_incidents=collection), session=session)

    created = await process_detector_results([result()], store, scope_id="connection-1")

    assert len(created) == 1
    assert collection.update_one.await_args.kwargs["session"] is session


@pytest.mark.anyio
async def test_duplicate_key_inside_transaction_is_not_hidden_as_a_successful_replay():
    collection = SimpleNamespace(update_one=AsyncMock(side_effect=DuplicateKeyError("synthetic conflict")))
    store = MongoIncidentStore(SimpleNamespace(guardian_incidents=collection), session=object())

    with pytest.raises(DuplicateKeyError):
        await process_detector_results([result()], store)
