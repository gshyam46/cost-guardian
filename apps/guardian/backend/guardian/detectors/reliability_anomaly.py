"""Latency/error reliability detector.

Two independent checks, deliberately kept separate rather than merged into one score:
1. Any failed call is always flagged -- an error doesn't need a baseline to be bad.
2. Latency is compared against that agent's own recent successful-call baseline
   (z-score), same reasoning as cost_anomaly: a naturally-slow agent shouldn't be
   flagged just for being itself, only for deviating from itself.
"""
import statistics
from typing import List

from ..models import TraceMetric
from .base import DetectorResult, observation_identity

NAME = "reliability_anomaly"
RULE_VERSION = "1"

MIN_BASELINE_SAMPLES = 5
LATENCY_Z_SCORE_THRESHOLD = 3.0
NO_VARIANCE_MULTIPLIER = 3.0


def evaluate(baseline: List[TraceMetric], candidates: List[TraceMetric]) -> List[DetectorResult]:
    results: List[DetectorResult] = []

    successful_baseline_by_agent: dict[str, list[TraceMetric]] = {}
    for trace in baseline:
        if trace.status == "success" and trace.latency_ms is not None:
            successful_baseline_by_agent.setdefault(trace.agent_name, []).append(trace)

    for candidate in candidates:
        if candidate.status == "error":
            results.append(
                DetectorResult(
                    triggered=True,
                    detector=NAME,
                    trace_ids=[candidate.trace_id],
                    severity="high",
                    title=f"Call failure in {candidate.agent_name}",
                    summary=f"{candidate.agent_name} call failed (status={candidate.status}).",
                    evidence={"status": candidate.status, "model": candidate.model},
                    agent_name=candidate.agent_name,
                    **observation_identity(candidate, "call_failure", RULE_VERSION),
                )
            )
            continue

        if candidate.status != "success" or candidate.latency_ms is None:
            continue

        agent_baseline = successful_baseline_by_agent.get(candidate.agent_name, [])
        if len(agent_baseline) < MIN_BASELINE_SAMPLES:
            continue

        latencies = [t.latency_ms for t in agent_baseline]
        mean = statistics.mean(latencies)
        stdev = statistics.pstdev(latencies)

        # Same JSON-safety reasoning as cost_anomaly: float("inf") serialises to null
        # and silently destroys the evidence, so a zero-variance baseline reports a
        # finite multiple instead of an undefined z-score.
        latency_multiple = (candidate.latency_ms / mean) if mean > 0 else None
        if stdev == 0:
            triggered = mean > 0 and candidate.latency_ms > mean * NO_VARIANCE_MULTIPLIER
            z_score = None
            comparison = (
                f"{latency_multiple:.1f}x the baseline mean (baseline had no variance, "
                f"so a z-score is undefined)" if latency_multiple else "above a zero baseline"
            )
        else:
            z_score = (candidate.latency_ms - mean) / stdev
            triggered = z_score >= LATENCY_Z_SCORE_THRESHOLD
            comparison = f"z-score={z_score:.2f}"

        if not triggered:
            continue

        evidence = {
            "latency_ms": candidate.latency_ms,
            "baseline_mean_ms": mean,
            "baseline_stdev_ms": stdev,
            "baseline_n": len(agent_baseline),
        }
        if z_score is not None:
            evidence["z_score"] = round(z_score, 3)
        if latency_multiple is not None:
            evidence["latency_multiple"] = round(latency_multiple, 2)

        results.append(
            DetectorResult(
                triggered=True,
                detector=NAME,
                trace_ids=[candidate.trace_id],
                severity="medium",
                title=f"Latency regression in {candidate.agent_name}",
                summary=(
                    f"{candidate.agent_name} latency {candidate.latency_ms:.0f}ms, vs a "
                    f"baseline mean of {mean:.0f}ms over {len(agent_baseline)} calls "
                    f"({comparison})."
                ),
                evidence=evidence,
                agent_name=candidate.agent_name,
                **observation_identity(candidate, "latency_regression", RULE_VERSION),
            )
        )

    return results
