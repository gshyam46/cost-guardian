from datetime import datetime, timezone

from guardian.detectors import reliability_anomaly
from guardian.models import TraceMetric


def _trace(trace_id, latency_ms=800.0, status="success", agent="profile_analyst"):
    return TraceMetric(
        trace_id=trace_id,
        agent_name=agent,
        model="groq/llama-3.3-70b-versatile",
        cost_usd=0.01,
        total_tokens=1000,
        latency_ms=latency_ms,
        status=status,
        timestamp=datetime.now(timezone.utc),
    )


def test_flags_call_failure_regardless_of_baseline():
    results = reliability_anomaly.evaluate([], [_trace("t1", status="error")])

    assert len(results) == 1
    assert results[0].severity == "high"
    assert results[0].trace_ids == ["t1"]
    assert results[0].evidence["status"] == "error"


def test_flags_latency_spike_above_baseline():
    baseline = [_trace(f"b{i}", latency_ms=lat) for i, lat in enumerate([800, 820, 790, 810, 805, 795])]
    candidate = _trace("c1", latency_ms=9000)

    results = reliability_anomaly.evaluate(baseline, [candidate])

    assert len(results) == 1
    assert results[0].detector == "reliability_anomaly"
    assert results[0].trace_ids == ["c1"]


def test_does_not_flag_normal_latency():
    baseline = [_trace(f"b{i}", latency_ms=lat) for i, lat in enumerate([800, 820, 790, 810, 805, 795])]
    candidate = _trace("c1", latency_ms=812)

    results = reliability_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_error_only_baseline_does_not_crash_and_does_not_flag():
    baseline = [_trace(f"b{i}", latency_ms=800, status="error") for i in range(6)]
    candidate = _trace("c1", latency_ms=850)

    results = reliability_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_skips_agents_with_insufficient_successful_baseline():
    baseline = [_trace("b1", latency_ms=800)]  # only 1 successful sample
    candidate = _trace("c1", latency_ms=50000)

    results = reliability_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_zero_variance_latency_evidence_is_json_serialisable():
    """Same float('inf') -> null JSON bug as cost_anomaly; see that test for context."""
    import json

    baseline = [_trace(f"b{i}", latency_ms=800) for i in range(6)]  # stdev == 0
    results = reliability_anomaly.evaluate(baseline, [_trace("c1", latency_ms=9000)])

    assert len(results) == 1
    evidence = results[0].evidence
    assert json.loads(json.dumps(evidence)) == evidence
    assert "z_score" not in evidence
    assert evidence["latency_multiple"] == 11.25
    assert "inf" not in results[0].summary.lower()
