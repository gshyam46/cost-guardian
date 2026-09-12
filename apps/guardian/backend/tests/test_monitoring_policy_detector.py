"""Customer-facing rule boundaries, independent of persistence and HTTP."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from guardian.detectors import cost_anomaly, monitoring_policy, reliability_anomaly
from guardian.incident_engine import signal_id
from guardian.models import TraceMetric
from policies.schema import DEFAULT_RULES


def metric(identifier="call", **changes):
    return replace(TraceMetric(trace_id="run", observation_id=identifier, project_id="project",
        agent_name="answer", model="model", cost_usd=1, cost_usd_decimal="1", total_tokens=12,
        latency_ms=100, status="success", timestamp=datetime.now(timezone.utc)), **changes)


def policy(revision=3, **changes):
    return {"revision": revision, "rules": {**DEFAULT_RULES, **changes}}


def evaluate(detector, candidate, *, baseline=(), snapshot=None, completed=(), available=True):
    return monitoring_policy.evaluate(detector, list(baseline), candidate, snapshot or policy(),
                                      list(completed), baseline_available=available)


@pytest.mark.parametrize("amount,expected", [("999999999.123456789011", False),
    ("999999999.123456789012", False), ("999999999.123456789013", True)])
def test_cost_limit_compares_exact_decimal_at_one_trillionth(amount, expected):
    threshold = "999999999.123456789012"
    # These values share a float representation. The source decimal remains the
    # authority for both the decision and its customer-visible evidence.
    assert float(amount) == float(threshold)
    result = evaluate(cost_anomaly, metric(cost_usd=float(amount), cost_usd_decimal=amount),
        snapshot=policy(max_call_cost_usd=threshold))
    assert bool(result.results) is expected
    assert result.done
    if expected:
        evidence = result.results[0].evidence
        assert evidence["observed_value"] == amount
        assert evidence["threshold_value"] == threshold
        assert evidence["comparison"] == "gt"
        assert evidence["reason"] == "cost_limit_exceeded"


@pytest.mark.parametrize("amount,expected", [(None, False), ("0", False), ("0.000000000001", True)])
def test_zero_limit_respects_unknown_and_measured_zero(amount, expected):
    candidate = metric(cost_usd=None if amount is None else float(amount), cost_usd_decimal=amount)
    result = evaluate(cost_anomaly, candidate, snapshot=policy(max_call_cost_usd="0"))
    assert bool(result.results) is expected


@pytest.mark.parametrize("status", ["success", "error", "unknown"])
def test_measured_latency_limit_does_not_depend_on_completion_status(status):
    result = evaluate(reliability_anomaly, metric(status=status, latency_ms=101),
        snapshot=policy(max_call_latency_ms=100, alert_on_errors=False), available=False)
    assert result.done
    assert len(result.results) == 1
    assert result.results[0].finding_kind == "latency_limit"
    assert result.results[0].evidence["observed_value"] == 101


@pytest.mark.parametrize("latency", [None, 0, 100])
def test_latency_equality_and_unknown_do_not_exceed_limit(latency):
    assert not evaluate(reliability_anomaly, metric(latency_ms=latency),
        snapshot=policy(max_call_latency_ms=100)).results


@pytest.mark.parametrize("milliseconds", [1001, 1007, 1011, 1023, 86400000])
def test_native_latency_uses_canonical_duration_at_exact_limit(milliseconds):
    start = datetime(2026, 9, 12, tzinfo=timezone.utc)
    end = start + timedelta(milliseconds=milliseconds)
    candidate = metric(source="guardian_direct", timestamp=start, ended_at=end,
        latency_ms=(end - start).total_seconds() * 1000)
    assert not evaluate(reliability_anomaly, candidate,
        snapshot=policy(max_call_latency_ms=milliseconds)).results
    result = evaluate(reliability_anomaly, candidate,
        snapshot=policy(max_call_latency_ms=milliseconds - 1))
    assert result.results[0].evidence["observed_value"] == milliseconds


def test_native_canonical_duration_does_not_fill_unknown_latency():
    candidate = metric(source="guardian_direct", latency_ms=None)
    candidate = replace(candidate, ended_at=candidate.timestamp + timedelta(seconds=2))
    assert not evaluate(reliability_anomaly, candidate,
        snapshot=policy(max_call_latency_ms=0)).results


def test_external_reported_latency_remains_authoritative_over_timestamps():
    candidate = metric(source="langfuse", latency_ms=100)
    candidate = replace(candidate, ended_at=candidate.timestamp + timedelta(seconds=2))
    assert not evaluate(reliability_anomaly, candidate,
        snapshot=policy(max_call_latency_ms=100)).results


@pytest.mark.parametrize("enabled,expected", [(False, 1), (True, 2)])
def test_error_toggle_only_controls_reported_failure_and_keeps_latency(enabled, expected):
    result = evaluate(reliability_anomaly, metric(status="error", latency_ms=200),
        snapshot=policy(max_call_latency_ms=100, alert_on_errors=enabled), available=False)
    assert len(result.results) == expected
    kinds = {item.finding_kind for item in result.results}
    assert ("call_failure" in kinds) is enabled
    assert "latency_limit" in kinds
    assert len({signal_id(item) for item in result.results}) == expected
    for item in result.results:
        assert item.evidence["policy_revision"] == 3
        json.dumps(asdict(item), allow_nan=False)


@pytest.mark.parametrize("detector,rule", [(cost_anomaly, {"max_call_cost_usd": "2"}),
                                         (reliability_anomaly, {"max_call_latency_ms": 200})])
def test_absolute_finding_takes_precedence_over_relative_outlier(detector, rule):
    history = [metric(str(i)) for i in range(6)]
    candidate = metric(cost_usd=9, cost_usd_decimal="9", latency_ms=900)
    result = evaluate(detector, candidate, baseline=history, snapshot=policy(**rule))
    assert len(result.results) == 1
    assert result.results[0].evidence["policy_kind"] == "absolute"


@pytest.mark.parametrize("detector,rule", [(cost_anomaly, {"max_call_cost_usd": "20"}),
                                         (reliability_anomaly, {"max_call_latency_ms": 2000})])
def test_below_absolute_limit_still_gets_existing_relative_protection(detector, rule):
    result = evaluate(detector, metric(cost_usd=9, cost_usd_decimal="9", latency_ms=900),
        baseline=[metric(str(i)) for i in range(6)], snapshot=policy(**rule))
    assert len(result.results) == 1
    assert result.results[0].evidence["policy_kind"] == "relative"
    assert result.results[0].evidence["policy_revision"] == 3
    assert result.results[0].evidence["baseline_n"] == 6


@pytest.mark.parametrize("amount,expected", [("0.009999999999", False), ("0.01", True), ("2", True)])
def test_free_history_has_explicit_finite_materiality_boundary(amount, expected):
    baseline = [metric(str(i), cost_usd=0, cost_usd_decimal="0") for i in range(6)]
    result = evaluate(cost_anomaly, metric(cost_usd=float(amount), cost_usd_decimal=amount), baseline=baseline)
    assert bool(result.results) is expected
    if expected:
        evidence = result.results[0].evidence
        assert evidence["reason"] == "zero_cost_transition"
        assert evidence["materiality_floor_usd"] == "0.01"
        assert evidence["baseline_mean_usd"] == 0
        assert evidence["cost_usd_decimal"] == amount
        json.dumps(asdict(result.results[0]), allow_nan=False)


def test_unknown_costs_do_not_create_a_free_baseline_or_satisfy_sample_minimum():
    unknown = [metric(str(i), cost_usd=None, cost_usd_decimal=None) for i in range(6)]
    candidate = metric(cost_usd=2, cost_usd_decimal="2")
    assert not evaluate(cost_anomaly, candidate, baseline=unknown).results
    free = [metric("free" + str(i), cost_usd=0, cost_usd_decimal="0") for i in range(4)]
    assert not evaluate(cost_anomaly, candidate, baseline=unknown + free).results
    result = evaluate(cost_anomaly, candidate, baseline=unknown + free + [metric("fifth", cost_usd=0, cost_usd_decimal="0")])
    assert result.results[0].evidence["baseline_n"] == 5


def test_relative_work_stays_pending_when_baseline_is_unavailable():
    result = evaluate(cost_anomaly, metric(), available=False)
    assert result.blocked and not result.done and not result.results
    retried = evaluate(cost_anomaly, metric(), completed=result.completed)
    assert retried.done and not retried.blocked


def test_absolute_limits_and_errors_complete_without_baseline():
    cost = evaluate(cost_anomaly, metric(), snapshot=policy(max_call_cost_usd="0.1"), available=False)
    failure = evaluate(reliability_anomaly, metric(status="error"), available=False)
    assert cost.done and len(cost.results) == 1
    assert failure.done and len(failure.results) == 1


def test_pinned_policy_version_and_observation_are_part_of_stable_signal_identity():
    candidate = metric()
    first = evaluate(cost_anomaly, candidate, snapshot=policy(max_call_cost_usd="0.5")).results[0]
    replay = evaluate(cost_anomaly, candidate, snapshot=policy(max_call_cost_usd="0.5")).results[0]
    revision = evaluate(cost_anomaly, candidate, snapshot=policy(revision=4, max_call_cost_usd="0.5")).results[0]
    second = evaluate(cost_anomaly, replace(candidate, observation_id="second"),
        snapshot=policy(max_call_cost_usd="0.5")).results[0]
    assert signal_id(first) == signal_id(replay)
    assert len({signal_id(first), signal_id(revision), signal_id(second)}) == 3


def test_already_completed_default_cost_v1_never_gets_rescored_as_v2():
    result = evaluate(cost_anomaly, metric(cost_usd=2, cost_usd_decimal="2"),
        baseline=[metric(str(i), cost_usd=0, cost_usd_decimal="0") for i in range(6)],
        completed=["cost_anomaly:1"], snapshot=policy(revision=0))
    assert result.done and result.results == [] and result.completed == ["cost_anomaly:1"]
