"""Hourly aggregate rollups of trace metrics.

Deliberately aggregates ONLY -- call counts, summed cost/tokens, summed latency, error
counts, per agent per hour. No prompts, no outputs, no per-call rows. Guardian does not
keep a copy of trace data; that stays in Langfuse (see docs/DECISIONS.md). These rollups
exist purely so the dashboard can draw cost/latency trend lines without round-tripping
to the Langfuse API on every page load.

Double-counting caveat: rollups are incremented from the worker's *candidates* (traces
newer than the last cursor), which the cursor already guarantees are seen once. If a
poll cycle dies after recording rollups but before advancing the cursor, that window
gets counted twice. Accepted for the MVP -- these numbers drive trend lines, not
billing. Incidents, which matter more, are deduped properly by (detector, trace_id).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import TraceMetric


def hour_bucket(moment: datetime) -> str:
    """The ISO-formatted hour a timestamp belongs to."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.replace(minute=0, second=0, microsecond=0).isoformat()


def rollup_id(hour: str, agent_name: str) -> str:
    return f"{hour}|{agent_name}"


def to_public_dict(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a stored rollup for API responses, computing derived averages."""
    call_count = doc.get("call_count", 0) or 0
    sum_latency = doc.get("sum_latency_ms", 0.0) or 0.0
    return {
        "hour": doc.get("hour", ""),
        "agent_name": doc.get("agent_name", "unknown"),
        "call_count": call_count,
        "error_count": doc.get("error_count", 0) or 0,
        "total_cost_usd": round(doc.get("total_cost_usd", 0.0) or 0.0, 6),
        "total_tokens": doc.get("total_tokens", 0) or 0,
        "avg_latency_ms": round(sum_latency / call_count, 2) if call_count else 0.0,
    }


class MongoMetricsStore:
    """Hourly rollups in the `guardian_metrics` collection."""

    def __init__(self, db) -> None:
        self._collection = db.guardian_metrics

    async def record(self, metrics: List[TraceMetric]) -> None:
        for metric in metrics:
            hour = hour_bucket(metric.timestamp)
            await self._collection.update_one(
                {"_id": rollup_id(hour, metric.agent_name)},
                {
                    "$inc": {
                        "call_count": 1,
                        "error_count": 0 if metric.status == "success" else 1,
                        "total_cost_usd": metric.cost_usd,
                        "total_tokens": metric.total_tokens,
                        "sum_latency_ms": metric.latency_ms,
                    },
                    "$set": {"hour": hour, "agent_name": metric.agent_name},
                },
                upsert=True,
            )

    async def since(self, moment: datetime) -> List[Dict[str, Any]]:
        """Rollups for every hour bucket at/after `moment`, oldest first."""
        cursor = self._collection.find({"hour": {"$gte": hour_bucket(moment)}})
        docs = await cursor.to_list(5000)
        return sorted(
            (to_public_dict(doc) for doc in docs),
            key=lambda d: (d["hour"], d["agent_name"]),
        )
