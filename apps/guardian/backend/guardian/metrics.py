"""Ledger-derived hourly accounting with explicit measurement coverage.

Unknown cost/usage/duration must not become free calls or zero-duration samples.
Historical rows lack coverage evidence and are labelled legacy. This writer
uses observation identity and transactional ledger reconciliation.
"""
from datetime import datetime, timezone
import math
from typing import Any, Dict, List

from .models import TraceMetric

MAX_METRIC_BUCKETS = 5000


class MetricsReadLimitError(Exception):
    """The legacy list endpoint cannot truthfully return this entire window."""


def hour_bucket(moment: datetime) -> str:
    """The ISO-formatted hour a timestamp belongs to."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


def rollup_id(hour: str, agent_name: str) -> str:
    return f"{hour}|{agent_name}"


def to_public_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a stored rollup for API responses, computing derived averages."""
    call_count = doc.get("call_count", 0) or 0
    sum_latency = doc.get("sum_latency_ms", 0.0) or 0.0

    def counts(name):
        known = doc.get(name + "_known_count")
        unknown = doc.get(name + "_unknown_count")
        if type(known) is int and type(unknown) is int and min(known, unknown) >= 0 and known + unknown == call_count:
            return known, unknown
        # Do not infer missing historical coverage from a stored zero or amount.
        return None, None

    cost_known, cost_unknown = counts("cost")
    tokens_known, tokens_unknown = counts("tokens")
    latency_known, latency_unknown = counts("latency")
    issues = []

    def finite_nonnegative(value):
        try:
            return type(value) in (int, float) and value >= 0 and math.isfinite(value)
        except (TypeError, ValueError, OverflowError):
            return False

    raw_cost = doc.get("total_cost_usd", 0.0)
    known_cost = round(raw_cost, 6) if cost_known is not None and finite_nonnegative(raw_cost) else None
    if cost_known is not None and known_cost is None:
        issues.append("cost_total_out_of_range")
    raw_tokens = doc.get("total_tokens", 0)
    # Mongo can promote an overflowing int64 sum to a double. Do not cast that
    # rounded result back to int and advertise it as an exact token count.
    known_tokens = raw_tokens if tokens_known is not None and type(raw_tokens) is int and 0 <= raw_tokens <= (1 << 63) - 1 else None
    if tokens_known is not None and known_tokens is None:
        issues.append("tokens_total_out_of_range")
    average_latency = round(sum_latency / latency_known, 2) if latency_known and finite_nonnegative(sum_latency) else None
    if latency_known and average_latency is None:
        issues.append("latency_total_out_of_range")
    return {
        "hour": doc.get("hour", ""),
        "agent_name": doc.get("agent_name", "unknown"),
        "call_count": call_count,
        "error_count": doc.get("error_count", 0) or 0,
        "total_cost_usd": known_cost if cost_unknown == 0 and not doc.get("conflict_count") else None,
        "known_cost_usd": known_cost,
        "cost_known_count": cost_known,
        "cost_unknown_count": cost_unknown,
        "total_tokens": known_tokens if tokens_unknown == 0 and not doc.get("conflict_count") else None,
        "known_total_tokens": known_tokens,
        "tokens_known_count": tokens_known,
        "tokens_unknown_count": tokens_unknown,
        "avg_latency_ms": average_latency,
        "latency_known_count": latency_known,
        "latency_unknown_count": latency_unknown,
        "unknown_status_count": doc.get("unknown_status_count"),
        "coverage_status": "known" if all(value is not None for value in (cost_known, tokens_known, latency_known)) else "legacy",
        "accounting_status": doc.get("accounting_status", "provisional_incremental"),
        "conflict_count": doc.get("conflict_count", 0),
        "aggregate_issues": issues,
    }


class MongoMetricsStore:
    """Hourly rollups in the `guardian_metrics` collection."""

    def __init__(self, db) -> None:
        self._db = db
        self._collection = db.guardian_metrics

    async def record(self, metrics: List[TraceMetric]) -> None:
        from config import GUARDIAN_CONNECTION_ID
        from .ledger import LedgerError, ObservationLedger, identity
        from .detectors import pii
        from dataclasses import asdict
        ledger = ObservationLedger(self._db, GUARDIAN_CONNECTION_ID)
        lease = await ledger.acquire()
        if lease is None:
            raise LedgerError("worker_lease_busy")
        try:
            prepared = {identity(metric, ledger.connection_id): [asdict(result) for result in pii.evaluate([], [metric])] for metric in metrics}
            await ledger.ingest_metrics(metrics, lease, prepared)
            await ledger.rebuild(lease)
        finally:
            await ledger.release(lease)

    async def since(self, moment: datetime) -> List[Dict[str, Any]]:
        """Rollups for every hour bucket at/after `moment`, oldest first."""
        cursor = self._collection.find({"hour": {"$gte": hour_bucket(moment)}})
        docs = await cursor.to_list(MAX_METRIC_BUCKETS + 1)
        if len(docs) > MAX_METRIC_BUCKETS:
            raise MetricsReadLimitError("metric_window_too_large")
        return sorted(
            (to_public_dict(doc) for doc in docs),
            key=lambda d: (d["hour"], d["agent_name"]),
        )
