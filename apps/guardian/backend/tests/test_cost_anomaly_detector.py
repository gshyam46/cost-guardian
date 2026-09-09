from datetime import datetime, timezone

from guardian.detectors import cost_anomaly
from guardian.models import TraceMetric


def _trace(trace_id, cost, agent="profile_analyst"):
    return TraceMetric(
        trace_id=trace_id,
        agent_name=agent,
        model="groq/llama-3.3-70b-versatile",
        cost_usd=cost,
        total_tokens=1000,
        latency_ms=800.0,
        status="success",
        timestamp=datetime.now(timezone.utc),
    )


def test_flags_cost_spike_far_above_baseline():
    baseline = [_trace(f"base-{i}", c) for i, c in enumerate([0.01, 0.011, 0.009, 0.0105, 0.0095, 0.01])]
    candidate = _trace("candidate-1", cost=0.5)

    results = cost_anomaly.evaluate(baseline, [candidate])

    assert len(results) == 1
    assert results[0].triggered
    assert results[0].detector == "cost_anomaly"
    assert results[0].trace_ids == ["candidate-1"]
    assert results[0].evidence["cost_usd"] == 0.5
    assert results[0].severity in {"medium", "high"}


def test_does_not_flag_normal_variation():
    baseline = [_trace(f"base-{i}", c) for i, c in enumerate([0.01, 0.011, 0.009, 0.0105, 0.0095, 0.01])]
    candidate = _trace("candidate-1", cost=0.0102)

    results = cost_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_skips_agents_with_insufficient_baseline():
    baseline = [_trace("base-1", 0.01)]  # below MIN_BASELINE_SAMPLES
    candidate = _trace("candidate-1", cost=5.0)

    results = cost_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_ignores_other_agents_baseline():
    baseline = [_trace(f"base-{i}", 0.01, agent="market_hunter") for i in range(6)]
    candidate = _trace("candidate-1", cost=0.5, agent="profile_analyst")

    results = cost_anomaly.evaluate(baseline, [candidate])

    assert results == []


def test_zero_variance_baseline_uses_multiplier_fallback():
    baseline = [_trace(f"base-{i}", 0.01) for i in range(6)]  # identical costs, stdev=0
    spike = _trace("candidate-1", cost=0.05)  # 5x baseline
    normal = _trace("candidate-2", cost=0.011)  # within tolerance

    spike_results = cost_anomaly.evaluate(baseline, [spike])
    normal_results = cost_anomaly.evaluate(baseline, [normal])

    assert len(spike_results) == 1
    assert normal_results == []


# --- JSON-safety of evidence -------------------------------------------------
# Regression: a zero-variance baseline used to report z_score = float("inf"), which
# is not representable in JSON. It reached the live dashboard as "z_score": null --
# silently destroying the evidence the incident asks the user to verify.

def test_zero_variance_evidence_is_json_serialisable():
    import json

    baseline = [_trace(f"base-{i}", 0.001) for i in range(6)]  # stdev == 0
    results = cost_anomaly.evaluate(baseline, [_trace("candidate-1", cost=0.05)])

    assert len(results) == 1
    evidence = results[0].evidence
    # Must survive a strict JSON round-trip with no Infinity/NaN.
    round_tripped = json.loads(json.dumps(evidence))
    assert round_tripped == evidence
    assert "z_score" not in evidence, "z-score is undefined for a flat baseline"
    assert evidence["cost_multiple"] == 50.0
    assert "inf" not in results[0].summary.lower()


def test_normal_baseline_still_reports_a_finite_z_score():
    import json

    baseline = [_trace(f"base-{i}", c) for i, c in enumerate([0.01, 0.011, 0.009, 0.0105, 0.0095, 0.01])]
    results = cost_anomaly.evaluate(baseline, [_trace("candidate-1", cost=0.5)])

    evidence = results[0].evidence
    assert json.loads(json.dumps(evidence)) == evidence
    assert isinstance(evidence["z_score"], float)
    assert evidence["z_score"] > 3
