"""Bounded, coverage-aware live views over the shared source adapter.

Derived measurements, observation trace context and short content previews are cached.
A successful traversal describes the source query, not arrival of all delayed
telemetry or completion of a customer's business workflow.
"""
import json
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import Any, Callable, Dict, List, Optional, Tuple

from .normalization import MAX_TOKEN_COUNT, normalize_observation, utc_datetime

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
MAX_WINDOW_RECORDS = 1000
MAX_RUN_HOURS = 168
CACHE_TTL_SECONDS = 20
MAX_CACHE_ENTRIES = 64
MAX_STALE_SECONDS = 300
OUTPUT_PREVIEW_CHARS = 400


class LiveReadError(RuntimeError):
    """The source could not establish a usable result (HTTP 503, not 404)."""


class _TTLCache:
    """Bounded cache with serialized fills and limited stale-on-failure retention."""

    def __init__(self, ttl_seconds=CACHE_TTL_SECONDS, max_entries=MAX_CACHE_ENTRIES,
                 max_stale_seconds=MAX_STALE_SECONDS):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._max_stale = max_stale_seconds
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get_or_fetch(self, key: str, fetch: Callable[[], Any]) -> Tuple[Any, bool, Optional[float]]:
        # One fill at a time bounds concurrent SDK work and avoids cache stampedes.
        # The API offloads this blocking work; network requests have their own limits.
        with self._lock:
            # Expiry measures elapsed process time. UTC wall time is retained
            # separately for API evidence and must not extend TTL after a clock reset.
            now = time.monotonic()
            entry = self._entries.get(key)
            if entry and now - entry[0] < self._ttl:
                self._entries.move_to_end(key)
                return entry[1], False, entry[2]
            if entry and now - entry[0] >= self._max_stale:
                del self._entries[key]
                entry = None
            try:
                value = fetch()
            except Exception as exc:
                if entry and time.monotonic() - entry[0] < self._max_stale:
                    logger.warning("Live source refresh failed (%s); serving stale data.", type(exc).__name__)
                    return entry[1], True, entry[2]
                self._entries.pop(key, None)
                raise
            fetched = time.time()
            self._entries[key] = (time.monotonic(), value, fetched)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return value, False, fetched


def _iso(value):
    normalized = utc_datetime(value)
    return normalized.isoformat() if normalized else None


def _readable_output(raw):
    if not raw:
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    inner = parsed.get("content", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(inner, str):
        return json.dumps(inner, indent=2, ensure_ascii=False)
    try:
        return json.dumps(json.loads(inner), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return inner


def _metric_to_call(metric):
    output = _readable_output(metric.output_text)
    return {
        "id": metric.observation_id,
        "trace_id": metric.trace_id,
        "agent_name": metric.agent_name,
        "model": metric.model,
        "status": metric.status,
        "completion_state": metric.completion_state,
        "status_message": metric.status_message[:OUTPUT_PREVIEW_CHARS] if metric.status_message else None,
        "status_message_truncated": bool(metric.status_message and len(metric.status_message) > OUTPUT_PREVIEW_CHARS),
        "started_at": _iso(metric.timestamp),
        "latency_ms": metric.latency_ms,
        "time_to_first_token_ms": metric.time_to_first_token_ms,
        "input_tokens": metric.input_tokens,
        "output_tokens": metric.output_tokens,
        "total_tokens": metric.total_tokens,
        "cost_usd": metric.cost_usd,
        "cost_usd_decimal": metric.cost_usd_decimal,
        "normalization_issues": list(metric.normalization_issues),
        "output_preview": (output or "")[:OUTPUT_PREVIEW_CHARS],
        "output_truncated": bool(output and len(output) > OUTPUT_PREVIEW_CHARS),
    }


def _observation_to_call(obs):
    """Compatibility entry point; all field normalization remains shared."""
    result = normalize_observation(obs)
    return _metric_to_call(result.metric) if result.metric is not None else None


def _coverage(result, scope="window_generations"):
    return {
        "scope": scope,
        "status": result.status,
        "window_start": _iso(result.window_start),
        "window_end": _iso(result.window_end),
        "fetched_at": _iso(result.fetched_at),
        "observed_count": len(result.metrics),
        "records_read": result.records_read,
        "invalid_count": result.invalid_count,
        "duplicate_count": result.duplicate_count,
        "pages_fetched": result.pages_fetched,
        "max_records": MAX_WINDOW_RECORDS,
        "max_pages": math.ceil(MAX_WINDOW_RECORDS / MAX_PAGE_SIZE),
        "truncated": result.error_code in {"limit_reached", "page_limit_reached"},
        "reason": result.error_code,
        "issues": dict(result.issues),
        "next_page": result.next_page,
        "has_more": bool(getattr(result, "next_cursor", None) or result.next_page),
    }


def _summary(calls):
    priced = [c for c in calls if c["cost_usd"] is not None]
    tokenized = [c for c in calls if c["total_tokens"] is not None]
    timed = [c["latency_ms"] for c in calls if c["latency_ms"] is not None]
    with localcontext() as context:
        context.prec = 1024
        known_cost = sum(
            (Decimal(c.get("cost_usd_decimal") or str(c["cost_usd"])) for c in priced),
            Decimal(0),
        )
        mean = float(sum((Decimal(str(v)) for v in timed), Decimal(0)) / len(timed)) if timed else None
    cost_value = float(known_cost)
    aggregate_issues = []
    if not math.isfinite(cost_value):
        cost_value = None
        aggregate_issues.append("cost_total_out_of_range")
    known_tokens = sum(c["total_tokens"] for c in tokenized)
    if known_tokens > MAX_TOKEN_COUNT:
        known_tokens = None
        aggregate_issues.append("tokens_total_out_of_range")
    return {
        "call_count": len(calls),
        "error_count": sum(c["status"] == "error" for c in calls),
        "unknown_status_count": sum(c["status"] not in ("success", "error") for c in calls),
        "total_cost_usd": cost_value if len(priced) == len(calls) else None,
        "known_cost_usd": cost_value,
        "known_cost_usd_decimal": format(known_cost, "f"),
        "aggregate_issues": aggregate_issues,
        "cost_known_count": len(priced),
        "cost_unknown_count": len(calls) - len(priced),
        "total_tokens": known_tokens if len(tokenized) == len(calls) else None,
        "known_total_tokens": known_tokens,
        "tokens_known_count": len(tokenized),
        "tokens_unknown_count": len(calls) - len(tokenized),
        "latency_known_count": len(timed),
        "latency_unknown_count": len(calls) - len(timed),
        "avg_latency_ms": round(mean, 1) if mean is not None else None,
        "p95_latency_ms": sorted(timed)[math.ceil(len(timed) * .95) - 1] if timed else None,
    }


def _stats_from(calls, hours):
    stats = _summary(calls)
    stats["window_hours"] = hours
    stats["last_call_at"] = max((c["started_at"] for c in calls), default=None)
    for field, output in (("agent_name", "by_agent"), ("model", "by_model")):
        buckets = {}
        for call in calls:
            buckets.setdefault(call[field], []).append(call)
        rows = []
        for name, values in buckets.items():
            row = _summary(values)
            rows.append({
                **row, "name": name, "calls": row["call_count"], "errors": row["error_count"],
                "cost_usd": row["total_cost_usd"], "tokens": row["total_tokens"],
            })
        stats[output] = sorted(rows, key=lambda r: (r["known_cost_usd"] is not None, r["known_cost_usd"] or 0), reverse=True)
    return stats


def _empty_stats(hours):
    return _stats_from([], hours)


def _trace_context(metrics):
    """Only explicit context is eligible; conflicting child context stays unknown."""
    context, issues = {}, []
    for field in ("trace_name", "user_id", "session_id", "trace_tags"):
        values = {getattr(metric, field) for metric in metrics if getattr(metric, field)}
        if len(values) > 1:
            issues.append("conflicting_" + field)
        context[field] = next(iter(values)) if len(values) == 1 else None
    return context, issues


def _run_from(trace_id, calls, trace_url, coverage, metrics):
    summary = _summary(calls)
    context, context_issues = _trace_context(metrics)
    state = "observed" if calls else "not_observed" if coverage["status"] == "complete" else "undetermined"
    if not calls:
        # Absence in a bounded query is not evidence of free or zero-token activity.
        for field in ("total_cost_usd", "known_cost_usd", "known_cost_usd_decimal", "total_tokens", "known_total_tokens"):
            summary[field] = None
    return {
        **summary,
        "id": trace_id,
        "name": context["trace_name"] or "Trace " + trace_id,
        "started_at": min((c["started_at"] for c in calls), default=None),
        "latency_ms": None,  # Child measurements do not establish workflow duration.
        "cost_usd": summary["total_cost_usd"] if calls else None,
        "known_cost_usd": summary["known_cost_usd"] if calls else None,
        "status": "error" if summary["error_count"] else "unknown",
        "workflow_status": "unknown",
        "user_id": context["user_id"],
        "session_id": context["session_id"],
        "tags": list(context["trace_tags"] or ()),
        "trace_context_issues": context_issues,
        "metadata_basis": "observations",
        "observation_state": state,
        "langfuse_url": trace_url(trace_id),
        "agents": list(dict.fromkeys(c["agent_name"] for c in calls)),
        "coverage": coverage,
    }


def _runs_from(metrics, calls, trace_url, coverage):
    by_trace = {}
    for call in calls:
        by_trace.setdefault(call["trace_id"], []).append(call)
    metrics_by_trace = {}
    for metric in metrics:
        metrics_by_trace.setdefault(metric.trace_id, []).append(metric)
    runs = [
        _run_from(trace_id, rows, trace_url, coverage, metrics_by_trace.get(trace_id, []))
        for trace_id, rows in by_trace.items()
    ]
    return sorted(runs, key=lambda r: r["started_at"] or "", reverse=True)


class LiveTraceReader:
    """All headlines use the bounded source traversal; feed limits only affect rows."""

    def __init__(self, source, ttl_seconds=CACHE_TTL_SECONDS):
        self._source = source
        self._cache = _TTLCache(ttl_seconds)

    @property
    def available(self):
        return self._source.available

    def _generations(self, since, until, trace_id=None):
        result = self._source.fetch_generations(
            since, until=until, limit=MAX_WINDOW_RECORDS, trace_id=trace_id,
        )
        if result.status == "failed":
            raise LiveReadError(result.error_code or "source_unavailable")
        return result

    def _fetch_snapshot(self, hours):
        until = datetime.now(timezone.utc)
        since = until - timedelta(hours=hours)
        result = self._generations(since, until)
        calls = sorted((_metric_to_call(m) for m in result.metrics),
                       key=lambda c: c["started_at"], reverse=True)
        coverage = _coverage(result)
        return {
            "available": True, "degraded": False,
            "coverage": coverage,
            "stats": _stats_from(calls, hours),
            "calls": calls,
            "runs": _runs_from(result.metrics, calls, self._source.trace_url, coverage),
            "metadata_basis": "observations",
        }

    def snapshot(self, hours=24, run_limit=8, call_limit=60):
        if not self.available:
            return {"available": False, "reason": "Langfuse credentials are not configured for Guardian."}
        # Keep direct callers bounded too; the HTTP API validates these parameters.
        if not 1 <= hours <= 168 or not 1 <= run_limit <= 100 or not 1 <= call_limit <= 100:
            raise ValueError("Live query exceeds supported bounds")
        try:
            payload, stale, fetched_at = self._cache.get_or_fetch(
                "window:%d" % hours, lambda: self._fetch_snapshot(hours))
        except Exception as exc:
            logger.warning("Live read unavailable (%s).", type(exc).__name__)
            return {
                "available": True, "degraded": True, "stale": False, "fetched_at": None,
                "reason": "Guardian could not read telemetry. Refresh to try again.",
                "coverage": {"scope": "window_generations", "status": "failed",
                             "reason": str(exc) if isinstance(exc, LiveReadError) else "source_unavailable",
                             "max_records": MAX_WINDOW_RECORDS},
                "stats": None, "calls": [], "runs": [],
            }
        return {
            **payload,
            "stale": stale,
            "fetched_at": payload["coverage"]["fetched_at"] or datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(),
            "calls": payload["calls"][:call_limit],
            "runs": payload["runs"][:run_limit],
            "feed": {"returned": min(call_limit, len(payload["calls"])), "limit": call_limit,
                     "limited": len(payload["calls"]) > call_limit},
        }

    def _fetch_run(self, trace_id, hours):
        until = datetime.now(timezone.utc)
        result = self._generations(until - timedelta(hours=hours), until, trace_id=trace_id)
        calls = sorted((_metric_to_call(m) for m in result.metrics),
                       key=lambda c: c["started_at"])
        coverage = _coverage(result, "trace_generations")
        return {**_run_from(trace_id, calls, self._source.trace_url, coverage, result.metrics),
                "window_hours": hours, "calls": calls}

    def run_detail(self, trace_id, hours=MAX_RUN_HOURS):
        if type(hours) is not int or not 1 <= hours <= MAX_RUN_HOURS:
            raise ValueError("Run query exceeds supported bounds")
        if not self.available:
            raise LiveReadError("not_configured")
        try:
            payload, stale, fetched_at = self._cache.get_or_fetch(
                "trace:%d:%s" % (hours, trace_id), lambda: self._fetch_run(trace_id, hours))
        except LiveReadError:
            raise
        except Exception:
            raise LiveReadError("trace_unavailable") from None
        return {**payload, "stale": stale,
                "fetched_at": payload["coverage"]["fetched_at"] or datetime.fromtimestamp(fetched_at, timezone.utc).isoformat()}
