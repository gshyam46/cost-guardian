"""Cost/token anomaly detector.

Deterministic, statistical: flags a candidate trace whose cost is a z-score outlier
against that same agent's own recent baseline. A known zero-cost history uses a
one-cent materiality floor because division by that history is undefined.
Customer-configured absolute limits are evaluated separately.
"""
import statistics
import math
from decimal import Decimal, InvalidOperation
from typing import List

from ..models import TraceMetric
from .base import DetectorResult, observation_identity

NAME = "cost_anomaly"
RULE_VERSION = "2"
ZERO_BASELINE_MATERIALITY_USD = Decimal("0.01")

MIN_BASELINE_SAMPLES = 5
Z_SCORE_THRESHOLD = 3.0
HIGH_SEVERITY_Z_SCORE = 4.5
NO_VARIANCE_MULTIPLIER = 3.0  # fallback when baseline stdev is 0


def known_cost(candidate):
    """Return an exact known nonnegative cost, preserving unknown measurements."""
    raw = candidate.cost_usd_decimal
    if raw is None:
        raw = candidate.cost_usd
        if type(raw) not in (int, float) or not math.isfinite(raw):
            return None
    elif not isinstance(raw, str):
        return None
    try:
        value = Decimal(str(raw))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def evaluate(baseline: List[TraceMetric], candidates: List[TraceMetric]) -> List[DetectorResult]:
    results: List[DetectorResult] = []

    baseline_by_agent: dict[str, list[TraceMetric]] = {}
    for trace in baseline:
        if trace.cost_usd is not None:
            baseline_by_agent.setdefault(trace.agent_name, []).append(trace)

    for candidate in candidates:
        if candidate.cost_usd is None:
            continue
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
        if cost_multiple is not None and not math.isfinite(cost_multiple):
            cost_multiple = None
        zero_transition = (mean == 0 and all(known_cost(trace) == 0 for trace in agent_baseline)
                           and known_cost(candidate) is not None
                           and known_cost(candidate) >= ZERO_BASELINE_MATERIALITY_USD)
        if stdev == 0:
            triggered = zero_transition or mean > 0 and candidate.cost_usd > mean * NO_VARIANCE_MULTIPLIER
            z_score = None
            severity = "high"  # a flat baseline broken this hard is not a subtle signal
            comparison = (
                f"{cost_multiple:.1f}x the baseline mean (baseline had no variance, "
                f"so a z-score is undefined)" if cost_multiple else
                "a material transition from known zero-cost calls" if zero_transition else "above the baseline"
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
        if zero_transition:
            evidence.update(reason="zero_cost_transition", materiality_floor_usd="0.01",
                            cost_usd_decimal=str(known_cost(candidate)))

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
                **observation_identity(candidate, "cost_spike", RULE_VERSION),
            )
        )

    return results
