"""Cost/token anomaly detector.

Deterministic, statistical: flags a candidate trace whose cost is a z-score outlier
against that same agent's own recent baseline. No LLM call, no fixed dollar threshold
(a fixed threshold can't tell "this agent is always expensive" from "this agent just
got expensive") -- each agent is compared only against its own history.
"""
import statistics
from typing import List

from ..models import TraceMetric
from .base import DetectorResult

NAME = "cost_anomaly"

MIN_BASELINE_SAMPLES = 5
Z_SCORE_THRESHOLD = 3.0
HIGH_SEVERITY_Z_SCORE = 4.5
NO_VARIANCE_MULTIPLIER = 3.0  # fallback when baseline stdev is 0


def evaluate(baseline: List[TraceMetric], candidates: List[TraceMetric]) -> List[DetectorResult]:
    results: List[DetectorResult] = []

    baseline_by_agent: dict[str, list[TraceMetric]] = {}
    for trace in baseline:
        baseline_by_agent.setdefault(trace.agent_name, []).append(trace)

    for candidate in candidates:
        agent_baseline = baseline_by_agent.get(candidate.agent_name, [])
        if len(agent_baseline) < MIN_BASELINE_SAMPLES:
            continue

        costs = [t.cost_usd for t in agent_baseline]
        mean = statistics.mean(costs)
        stdev = statistics.pstdev(costs)

        # When the baseline has no variance a z-score is undefined (division by zero),
        # so fall back to a plain multiple of the mean. Reporting float("inf") here
        # was a real bug: it is not representable in JSON, so it reached the UI as
        # "z_score": null -- destroying the very evidence the incident asks the user
        # to verify. `cost_multiple` is finite, JSON-safe, and easier to read anyway.
        cost_multiple = (candidate.cost_usd / mean) if mean > 0 else None
        if stdev == 0:
            triggered = mean > 0 and candidate.cost_usd > mean * NO_VARIANCE_MULTIPLIER
            z_score = None
            severity = "high"  # a flat baseline broken this hard is not a subtle signal
            comparison = (
                f"{cost_multiple:.1f}x the baseline mean (baseline had no variance, "
                f"so a z-score is undefined)" if cost_multiple else "above a zero baseline"
            )
        else:
            z_score = (candidate.cost_usd - mean) / stdev
            triggered = z_score >= Z_SCORE_THRESHOLD
            severity = "high" if z_score >= HIGH_SEVERITY_Z_SCORE else "medium"
            comparison = f"z-score={z_score:.2f}"

        if not triggered:
            continue

        evidence = {
            "cost_usd": candidate.cost_usd,
            "baseline_mean_usd": mean,
            "baseline_stdev_usd": stdev,
            "baseline_n": len(agent_baseline),
            "model": candidate.model,
        }
        if z_score is not None:
            evidence["z_score"] = round(z_score, 3)
        if cost_multiple is not None:
            evidence["cost_multiple"] = round(cost_multiple, 2)

        results.append(
            DetectorResult(
                triggered=True,
                detector=NAME,
                trace_ids=[candidate.trace_id],
                severity=severity,
                title=f"Cost spike in {candidate.agent_name}",
                summary=(
                    f"{candidate.agent_name} call cost ${candidate.cost_usd:.4f}, "
                    f"vs a baseline mean of ${mean:.4f} over {len(agent_baseline)} calls "
                    f"({comparison})."
                ),
                evidence=evidence,
                agent_name=candidate.agent_name,
            )
        )

    return results
