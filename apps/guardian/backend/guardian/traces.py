"""Live read model for runs and LLM calls, served straight from Langfuse.

Guardian deliberately stores no raw traces -- it owns incidents and hourly rollups,
and Langfuse remains the system of record for the calls themselves (see
docs/ARCHITECTURE.md). That decision is what keeps Guardian pointable at any Langfuse
project, but it left the dashboard with nothing to show between "an incident fired"
and "go read Langfuse": no call list, no latency per agent, no sense of whether the
app is even doing anything right now.

This module fills that gap without breaking the decision behind it. Nothing here is
persisted; every response is assembled on demand from Langfuse and thrown away. If
Guardian's database were wiped, these views would be unaffected -- which is the test
for whether we are caching Langfuse's data or merely reading it.

One Langfuse quirk worth knowing: the *analytics* tables behind Langfuse's own UI lag
by roughly 15 minutes ("New data in ~15 min" in their table headers), but the trace
and observation APIs used here return a run within seconds of it finishing. A run that
has not yet surfaced in Langfuse's dashboard is already visible in this one.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .langfuse_client import _get, _stringify

logger = logging.getLogger(__name__)

# Langfuse rejects a larger page size with a 400.
MAX_PAGE_SIZE = 100

# Langfuse Cloud allows 15 requests/minute on the public API and answers 429 past that.
# That budget is shared with the worker's own polling, so the dashboard cannot simply
# call through on every refresh: at a 10s refresh over two endpoints it would spend the
# entire allowance by itself and starve the detector loop.
#
# Hence a short TTL cache. This is not a retreat from "Guardian stores no traces" --
# nothing is written to Guardian's database and the entries evaporate with the process.
# It only means several dashboard refreshes (or several open tabs) inside one window
# share a single upstream read.
CACHE_TTL_SECONDS = 20


class _TTLCache:
    """Tiny in-memory cache whose real job is surviving a 429.

    On an upstream failure it returns the last good value marked stale rather than an
    empty one. That distinction is the whole point: an empty result renders as "your
    app made no calls", which is a factual claim about the user's system, and it must
    never be produced by Guardian failing to read its own telemetry source.
    """

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_fetch(self, key: str, fetch: Callable[[], Any]) -> Tuple[Any, bool, Optional[float]]:
        """Return (value, stale, fetched_at_epoch)."""
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
        if entry and now - entry[0] < self._ttl:
            return entry[1], False, entry[0]

        try:
            value = fetch()
        except Exception as e:
            if entry:
                logger.warning(f"[Guardian] Langfuse read failed ({e}); serving cached data.")
                return entry[1], True, entry[0]
            raise

        with self._lock:
            self._entries[key] = (now, value)
        return value, False, now

# Enough of a model's reply to see what it actually said, without shipping a 10KB JSON
# document per call into a table the user is scanning.
OUTPUT_PREVIEW_CHARS = 400


def _level_to_status(obs: Any) -> str:
    level = _get(obs, "level", default="DEFAULT")
    level = getattr(level, "value", level)
    return "error" if str(level).upper() == "ERROR" else "success"


def _tokens(obs: Any) -> Dict[str, int]:
    """Token counts split in/out. Langfuse exposes these three different ways
    depending on SDK version and how the call was instrumented, so try each."""
    details = _get(obs, "usageDetails", "usage_details")
    if isinstance(details, dict):
        return {
            "input": int(details.get("input") or 0),
            "output": int(details.get("output") or 0),
            "total": int(details.get("total") or 0),
        }

    usage = _get(obs, "usage")
    if usage is not None:
        inp = _get(usage, "input", "prompt_tokens", default=0) or 0
        out = _get(usage, "output", "completion_tokens", default=0) or 0
        total = _get(usage, "total", default=None)
        try:
            inp, out = int(inp), int(out)
            return {"input": inp, "output": out, "total": int(total) if total else inp + out}
        except (TypeError, ValueError):
            pass

    inp = int(_get(obs, "promptTokens", "prompt_tokens", default=0) or 0)
    out = int(_get(obs, "completionTokens", "completion_tokens", default=0) or 0)
    return {"input": inp, "output": out, "total": inp + out}


def _cost(obs: Any) -> float:
    cost = _get(obs, "calculated_total_cost", "total_cost", "totalCost")
    if cost is None:
        details = _get(obs, "costDetails", "cost_details")
        if isinstance(details, dict):
            cost = details.get("total")
    try:
        return float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _seconds_to_ms(value: Any) -> float:
    try:
        return round(float(value) * 1000, 1)
    except (TypeError, ValueError):
        return 0.0


def _readable_output(raw: Optional[str]) -> Optional[str]:
    """Unwrap a model response into something a human can skim.

    Langfuse stores the output as a JSON envelope, and these agents answer in JSON
    mode, so the raw value arrives double-encoded: a JSON string holding escaped JSON.
    Rendered verbatim it is a wall of backslash-n and backslash-u escapes.

    This must happen before the preview is truncated -- doing it in the browser (the
    first attempt) could never work, because a 400-character slice of a JSON document
    is not parseable JSON, so every unwrap failed and fell back to the raw text.

    Falls back to the original string at every step: an unreadable rendering of what
    the model actually said beats a tidy rendering of something it did not.
    """
    if not raw:
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw

    inner = parsed.get("content", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(inner, str):
        try:
            return json.dumps(inner, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return raw

    try:
        return json.dumps(json.loads(inner), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return inner


def _observation_to_call(obs: Any) -> Optional[Dict[str, Any]]:
    """One LLM call, flattened for the dashboard."""
    try:
        tokens = _tokens(obs)
        status = _level_to_status(obs)
        output = _readable_output(_stringify(_get(obs, "output")))
        return {
            "id": str(_get(obs, "id", default="")),
            "trace_id": str(_get(obs, "trace_id", "traceId", default="")),
            "agent_name": str(_get(obs, "name", default="unknown")),
            "model": str(_get(obs, "model", default="unknown")),
            "status": status,
            # Langfuse only populates status_message on failures; it carries the
            # provider's actual error text, which is the single most useful field on
            # this whole screen when something breaks.
            "status_message": _stringify(_get(obs, "status_message", "statusMessage")),
            "started_at": _iso(_get(obs, "start_time", "startTime")),
            "latency_ms": _seconds_to_ms(_get(obs, "latency")),
            "time_to_first_token_ms": _seconds_to_ms(
                _get(obs, "time_to_first_token", "timeToFirstToken")
            ),
            "input_tokens": tokens["input"],
            "output_tokens": tokens["output"],
            "total_tokens": tokens["total"],
            "cost_usd": _cost(obs),
            "output_preview": (output or "")[:OUTPUT_PREVIEW_CHARS],
            "output_truncated": bool(output and len(output) > OUTPUT_PREVIEW_CHARS),
        }
    except Exception as e:
        logger.warning(f"[Guardian] Skipping unparseable observation for traces view: {e}")
        return None


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None

class LiveTraceReader:
    """Read-only views over Langfuse, behind a short TTL cache.

    Every dashboard view is derived from at most two upstream reads -- one page of
    GENERATION observations and one page of traces -- rather than one read per widget.
    That is a rate-limit requirement, not an optimisation: Langfuse Cloud allows 15
    requests/minute across the whole project, and Guardian's worker spends from the
    same budget.
    """

    def __init__(self, source, ttl_seconds: int = CACHE_TTL_SECONDS):
        # Takes the existing LangfuseTraceSource so credential handling and the
        # "no credentials configured" degradation live in exactly one place.
        self._source = source
        self._cache = _TTLCache(ttl_seconds)

    @property
    def available(self) -> bool:
        return self._source.available

    def _client(self):
        return self._source.client

    # --- upstream reads (the only methods here that touch the network) ------------

    def _fetch_calls(self, hours: int) -> List[Dict[str, Any]]:
        response = self._client().fetch_observations(
            type="GENERATION",
            from_start_time=datetime.now(timezone.utc) - timedelta(hours=hours),
            limit=MAX_PAGE_SIZE,
        )
        calls = [c for c in (_observation_to_call(o) for o in response.data) if c]
        calls.sort(key=lambda c: c["started_at"] or "", reverse=True)
        return calls

    def _fetch_traces(self, limit: int) -> List[Any]:
        return self._client().fetch_traces(limit=min(limit, MAX_PAGE_SIZE)).data

    # --- derived views -----------------------------------------------------------

    def snapshot(self, hours: int = 24, run_limit: int = 8, call_limit: int = 60) -> Dict[str, Any]:
        """Everything the live dashboard needs, from one cached pair of reads."""
        if not self.available:
            return {
                "available": False,
                "reason": "Langfuse credentials are not configured for Guardian.",
            }

        try:
            calls, calls_stale, fetched_at = self._cache.get_or_fetch(
                "calls:%d" % hours, lambda: self._fetch_calls(hours)
            )
        except Exception as e:
            # Nothing cached to fall back on. Say that Guardian could not read, rather
            # than reporting zero calls -- zero is a claim about the user's system.
            logger.error("[Guardian] Could not read calls from Langfuse: %s", e)
            return {
                "available": True,
                "degraded": True,
                "reason": (
                    "Guardian could not read from Langfuse (it may be rate-limited). "
                    "Numbers return on the next refresh."
                ),
                "stale": False,
                "fetched_at": None,
                "stats": _empty_stats(hours),
                "calls": [],
                "runs": [],
            }

        try:
            raw_traces, traces_stale, _ = self._cache.get_or_fetch(
                "traces:%d" % run_limit, lambda: self._fetch_traces(run_limit)
            )
        except Exception:
            raw_traces, traces_stale = [], True

        return {
            "available": True,
            "degraded": False,
            "stale": bool(calls_stale or traces_stale),
            "fetched_at": (
                datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat()
                if fetched_at
                else None
            ),
            "stats": _stats_from(calls, hours),
            "calls": calls[:call_limit],
            "runs": _runs_from(raw_traces, calls, self._source.trace_url),
        }

    def run_detail(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """One run with every call beneath it, oldest first so it reads as a timeline."""
        if not self.available:
            return None
        try:
            trace, _, _ = self._cache.get_or_fetch(
                "trace:%s" % trace_id, lambda: self._client().fetch_trace(trace_id).data
            )
        except Exception as e:
            logger.error("[Guardian] fetch_trace(%s) failed: %s", trace_id, e)
            return None

        calls = [
            c
            for c in (_observation_to_call(o) for o in (_get(trace, "observations") or []))
            if c
        ]
        calls.sort(key=lambda c: c["started_at"] or "")
        errors = [c for c in calls if c["status"] == "error"]

        return {
            "id": str(_get(trace, "id", default=trace_id)),
            "name": str(_get(trace, "name", default="run")),
            "started_at": _iso(_get(trace, "timestamp")),
            "latency_ms": _seconds_to_ms(_get(trace, "latency")),
            "cost_usd": float(_get(trace, "total_cost", "totalCost", default=0) or 0),
            "total_tokens": sum(c["total_tokens"] for c in calls),
            "call_count": len(calls),
            "error_count": len(errors),
            "status": "error" if errors else "success",
            "user_id": _get(trace, "user_id", "userId"),
            "session_id": _get(trace, "session_id", "sessionId"),
            "tags": list(_get(trace, "tags", default=[]) or []),
            "langfuse_url": self._source.trace_url(trace_id),
            "calls": calls,
        }


def _empty_stats(hours: int) -> Dict[str, Any]:
    return {
        "window_hours": hours,
        "call_count": 0,
        "error_count": 0,
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "avg_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "by_agent": [],
        "by_model": [],
        "last_call_at": None,
    }


def _stats_from(calls: List[Dict[str, Any]], hours: int) -> Dict[str, Any]:
    """Headline numbers over exactly the call list the feed renders, so the totals and
    the rows beneath them can never disagree."""
    if not calls:
        return _empty_stats(hours)

    latencies = sorted(c["latency_ms"] for c in calls)
    errors = [c for c in calls if c["status"] == "error"]

    by_agent: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    for call in calls:
        for bucket, key in ((by_agent, call["agent_name"]), (by_model, call["model"])):
            row = bucket.setdefault(
                key,
                {
                    "name": key,
                    "calls": 0,
                    "errors": 0,
                    "cost_usd": 0.0,
                    "tokens": 0,
                    "_latency_sum": 0.0,
                },
            )
            row["calls"] += 1
            row["errors"] += 1 if call["status"] == "error" else 0
            row["cost_usd"] += call["cost_usd"]
            row["tokens"] += call["total_tokens"]
            row["_latency_sum"] += call["latency_ms"]

    def finish(bucket):
        rows = []
        for row in bucket.values():
            latency_sum = row.pop("_latency_sum")
            row["avg_latency_ms"] = round(latency_sum / row["calls"], 1) if row["calls"] else 0.0
            row["cost_usd"] = round(row["cost_usd"], 6)
            rows.append(row)
        return sorted(rows, key=lambda r: r["cost_usd"], reverse=True)

    return {
        "window_hours": hours,
        "call_count": len(calls),
        "error_count": len(errors),
        "total_cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
        "total_tokens": sum(c["total_tokens"] for c in calls),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        # Index rather than interpolate: at the call volumes this dashboard sees (tens,
        # not thousands) an interpolated p95 implies precision that is not there.
        "p95_latency_ms": latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)],
        "by_agent": finish(by_agent),
        "by_model": finish(by_model),
        "last_call_at": calls[0]["started_at"],
    }


def _runs_from(raw_traces, calls, trace_url) -> List[Dict[str, Any]]:
    """Join run rows to the calls already fetched, in memory.

    Asking Langfuse for each run's children separately would be another request per
    row to render one table -- which is exactly what put this dashboard over the rate
    limit the first time it was built.
    """
    calls_by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for call in calls:
        calls_by_trace.setdefault(call["trace_id"], []).append(call)

    runs = []
    for trace in raw_traces:
        trace_id = str(_get(trace, "id", default=""))
        trace_calls = calls_by_trace.get(trace_id, [])
        errors = [c for c in trace_calls if c["status"] == "error"]
        runs.append(
            {
                "id": trace_id,
                "name": str(_get(trace, "name", default="run")),
                "started_at": _iso(_get(trace, "timestamp")),
                "latency_ms": _seconds_to_ms(_get(trace, "latency")),
                # Prefer the run-level cost Langfuse computes; fall back to summing the
                # children when the window did not include all of them.
                "cost_usd": float(_get(trace, "total_cost", "totalCost", default=0) or 0)
                or sum(c["cost_usd"] for c in trace_calls),
                "total_tokens": sum(c["total_tokens"] for c in trace_calls),
                "call_count": len(trace_calls),
                "error_count": len(errors),
                "status": "error" if errors else "success",
                "user_id": _get(trace, "user_id", "userId"),
                "session_id": _get(trace, "session_id", "sessionId"),
                "agents": sorted({c["agent_name"] for c in trace_calls}),
                "models": sorted({c["model"] for c in trace_calls if c["model"] != "unknown"}),
                "langfuse_url": trace_url(trace_id),
            }
        )
    return runs
