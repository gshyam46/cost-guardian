"""Pure staged policy evaluation. Durable stage tokens live on the observation.

Immediate rules never depend on baseline availability. Relative work remains
pending when its bounded baseline cannot be read; an absolute finding suppresses
only the corresponding relative condition, under the same pinned policy.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import math

from . import cost_anomaly, reliability_anomaly
from .base import DetectorResult, observation_identity

NAMES = frozenset({cost_anomaly.NAME, reliability_anomaly.NAME})


@dataclass
class Evaluation:
    results: list
    completed: list
    done: bool
    blocked: bool = False


def version(detector, policy):
    base = getattr(detector, "RULE_VERSION", "1")
    return base if policy["revision"] == 0 else f"{base}:policy:{policy['revision']}"


def token(detector, policy):
    return detector.NAME + ":" + version(detector, policy)


def is_complete(detector, policy, completed):
    if token(detector, policy) in completed:
        return True
    # Cost v2 adds free-history materiality. Already completed v1 decisions stay
    # completed; a policy save must not rescore partially processed legacy rows.
    return (policy["revision"] == 0 and detector.NAME == cost_anomaly.NAME
            and "cost_anomaly:1" in completed)


def _cost_text(candidate, value):
    return candidate.cost_usd_decimal if candidate.cost_usd_decimal is not None else str(value)


def _latency(candidate):
    value = candidate.latency_ms
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    # Native intake computes latency from these canonical timestamps. Recover
    # their exact duration here without changing already persisted fingerprints:
    # total_seconds()*1000 can move an integer-ms boundary by one float ULP.
    start, end = candidate.timestamp, candidate.ended_at
    if (candidate.source == "guardian_direct" and isinstance(start, datetime) and isinstance(end, datetime)
            and start.utcoffset() is not None and end.utcoffset() is not None):
        delta = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
        value = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds / 1000
        return value if value >= 0 else None
    return value


def _absolute(detector, candidate, policy, metric, observed, threshold, reason, kind):
    label = "cost" if metric == "cost_usd" else "duration"
    unit = "USD" if metric == "cost_usd" else "ms"
    evidence = {"policy_revision": policy["revision"], "policy_kind": "absolute", "metric": metric,
                "observed_value": observed, "threshold_value": threshold, "comparison": "gt",
                "reason": reason, "model": candidate.model}
    return DetectorResult(triggered=True, detector=detector.NAME, trace_ids=[candidate.trace_id],
        severity="high" if metric == "cost_usd" else "medium", agent_name=candidate.agent_name,
        title=f"Call {label} limit exceeded in {candidate.agent_name}",
        summary=f"Observed {label} {observed} {unit} exceeds the saved limit of {threshold} {unit} (policy revision {policy['revision']}).",
        evidence=evidence, **observation_identity(candidate, kind, version(detector, policy)))


def evaluate(detector, baseline, candidate, policy, completed, *, baseline_available=True):
    """Evaluate one supported detector without conflating blocked with no finding."""
    if is_complete(detector, policy, completed):
        return Evaluation([], list(completed), True)
    whole = token(detector, policy)
    immediate, relative = whole + ":immediate", whole + ":relative"
    completed = list(completed)
    results = []
    rules = policy["rules"]
    absolute = False
    cost = cost_anomaly.known_cost(candidate)
    latency = _latency(candidate)
    if detector.NAME == cost_anomaly.NAME:
        limit = rules["max_call_cost_usd"]
        absolute = cost is not None and limit is not None and cost > Decimal(limit)
        relative_needed = candidate.cost_usd is not None and cost is not None
        if immediate not in completed:
            if absolute:
                results.append(_absolute(detector, candidate, policy, "cost_usd", _cost_text(candidate, cost),
                    limit, "cost_limit_exceeded", "cost_limit"))
            completed.append(immediate)
    elif detector.NAME == reliability_anomaly.NAME:
        limit = rules["max_call_latency_ms"]
        absolute = latency is not None and limit is not None and latency > limit
        relative_needed = candidate.status == "success" and latency is not None
        if immediate not in completed:
            if rules["alert_on_errors"] and candidate.status == "error":
                failure = reliability_anomaly.evaluate([], [candidate])[0]
                evidence = {**failure.evidence, "policy_revision": policy["revision"], "policy_kind": "reported_error",
                    "metric": "status", "observed_value": "error", "threshold_value": "error", "comparison": "eq",
                    "reason": "reported_call_error"}
                results.append(replace(failure, rule_version=version(detector, policy), evidence=evidence))
            if absolute:
                results.append(_absolute(detector, candidate, policy, "latency_ms", latency, limit,
                    "latency_limit_exceeded", "latency_limit"))
            completed.append(immediate)
    else:
        raise ValueError("unsupported_policy_detector")
    if relative not in completed:
        if absolute or not relative_needed:
            completed.append(relative)
        elif baseline_available:
            for finding in detector.evaluate(baseline, [candidate]):
                evidence = {**finding.evidence, "policy_revision": policy["revision"], "policy_kind": "relative",
                    "reason": finding.evidence.get("reason", "relative_cost_outlier" if detector.NAME == cost_anomaly.NAME
                                                   else "relative_latency_outlier")}
                results.append(replace(finding, rule_version=version(detector, policy), evidence=evidence))
            completed.append(relative)
    done = immediate in completed and relative in completed
    if done and whole not in completed:
        completed.append(whole)
    return Evaluation(results, completed, done, not done)
