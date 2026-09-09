"""Thin wrapper around the Langfuse API: pulls recent LLM-call observations and
converts them into Guardian's internal TraceMetric shape.

This is the only file in guardian/ that talks to the network. Detectors and the
incident engine never import Langfuse directly -- see docs/ARCHITECTURE.md.

NOTE: Langfuse's observations API has been evolving (a v2 endpoint with richer field
groups shipped in 2026); field extraction below is written defensively (multiple
fallback field names, per-item try/except) specifically because this has not been
exercised against a live Langfuse project in this environment -- see the "Open
blockers" note in docs/PROGRESS.md. If a field name is wrong for your Langfuse
version, a single observation is skipped and logged, not a hard crash.
"""
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

from .models import TraceMetric

logger = logging.getLogger(__name__)

# Langfuse's API rejects a larger page size with a 400.
MAX_PAGE_SIZE = 100


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first present attribute or dict key among `names`."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return default


def _extract_tokens(obs: Any) -> int:
    usage = _get(obs, "usage", "usage_details", "usageDetails")
    if usage is not None:
        total = _get(usage, "total", "total_tokens", "totalTokens")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                pass
    prompt = _get(obs, "prompt_tokens", "promptTokens", "input_usage", default=0) or 0
    completion = _get(obs, "completion_tokens", "completionTokens", "output_usage", default=0) or 0
    try:
        return int(prompt) + int(completion)
    except (TypeError, ValueError):
        return 0


def _extract_cost(obs: Any) -> float:
    cost = _get(obs, "calculated_total_cost", "total_cost", "totalCost", "cost")
    if cost is not None:
        try:
            return float(cost)
        except (TypeError, ValueError):
            pass
    cost_details = _get(obs, "cost_details", "costDetails")
    if cost_details is not None:
        total = _get(cost_details, "total")
        if total is not None:
            try:
                return float(total)
            except (TypeError, ValueError):
                pass
    return 0.0


def _extract_latency_ms(obs: Any) -> float:
    latency = _get(obs, "latency")
    if latency is not None:
        try:
            # Langfuse reports latency in seconds.
            return float(latency) * 1000
        except (TypeError, ValueError):
            pass
    start = _get(obs, "start_time", "startTime")
    end = _get(obs, "end_time", "endTime")
    if start is not None and end is not None:
        try:
            return (end - start).total_seconds() * 1000
        except (TypeError, AttributeError):
            pass
    return 0.0


def _observation_to_trace_metric(obs: Any) -> Optional[TraceMetric]:
    try:
        trace_id = _get(obs, "trace_id", "traceId")
        if not trace_id:
            return None

        level = (_get(obs, "level", default="DEFAULT") or "DEFAULT").upper()
        status = "error" if level == "ERROR" else "success"

        timestamp = _get(obs, "start_time", "startTime")
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)

        return TraceMetric(
            trace_id=str(trace_id),
            agent_name=str(_get(obs, "name", default="unknown")),
            model=str(_get(obs, "model", default="unknown")),
            cost_usd=_extract_cost(obs),
            total_tokens=_extract_tokens(obs),
            latency_ms=_extract_latency_ms(obs),
            status=status,
            timestamp=timestamp,
            output_text=_stringify(_get(obs, "output")),
        )
    except Exception as e:
        logger.warning(f"[Guardian] Skipping unparseable observation: {e}")
        return None


def _stringify(output: Any) -> Optional[str]:
    if output is None:
        return None
    if isinstance(output, str):
        return output
    try:
        import json

        return json.dumps(output)
    except (TypeError, ValueError):
        return str(output)


class LangfuseTraceSource:
    """Pulls recent GENERATION-type observations from Langfuse.

    Returns [] (not an exception) when credentials are missing or the API call fails
    -- the worker must keep running even when Langfuse is unreachable.
    """

    def __init__(self) -> None:
        self._client = None
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=LANGFUSE_PUBLIC_KEY,
                    secret_key=LANGFUSE_SECRET_KEY,
                    host=LANGFUSE_HOST,
                )
            except Exception as e:
                logger.error(f"[Guardian] Failed to initialize Langfuse client: {e}")
        else:
            logger.warning(
                "[Guardian] LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set - the "
                "worker has nothing to poll."
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def fetch_recent_generations(
        self, since: datetime, limit: int = 200
    ) -> List[TraceMetric]:
        """Fetch GENERATION observations that started at/after `since`.

        Pages through the API rather than asking for everything at once: Langfuse
        rejects limit > 100 with a 400 ("Too big: expected number to be <=100"), and
        the worker's 24h baseline window routinely holds more than that.
        """
        if not self._client:
            return []

        raw_observations: List[Any] = []
        page = 1
        while len(raw_observations) < limit:
            page_size = min(MAX_PAGE_SIZE, limit - len(raw_observations))
            try:
                # langfuse 2.x exposes fetch_observations() directly on the client
                # (all keyword-only). The v3 SDK's
                # `client.api.observations.get_many(...)` path does not exist here --
                # verified against langfuse==2.53.9 with a live project on 2026-09-09.
                response = self._client.fetch_observations(
                    type="GENERATION",
                    from_start_time=since,
                    limit=page_size,
                    page=page,
                )
            except Exception as e:
                logger.error(f"[Guardian] Langfuse fetch failed (page {page}): {e}")
                break

            batch = getattr(response, "data", response) or []
            raw_observations.extend(batch)
            if len(batch) < page_size:
                break  # last page
            page += 1

        # Never hand back more than asked for, even if a page over-delivers.
        metrics = [_observation_to_trace_metric(obs) for obs in raw_observations[:limit]]
        return [m for m in metrics if m is not None]

    def trace_url(self, trace_id: str) -> Optional[str]:
        """Deep link to this trace in the Langfuse UI, or None if unavailable.

        Built directly rather than via the SDK: langfuse 2.x's get_trace_url() takes
        no arguments and only returns a URL for the SDK's *current* trace context,
        which is useless here -- the worker builds links for arbitrary historical
        trace ids it pulled from the API. This host-relative form redirects to the
        project-scoped URL; both were confirmed to return 200 against the live
        project on 2026-09-09.
        """
        if not trace_id:
            return None
        return f"{LANGFUSE_HOST.rstrip('/')}/trace/{trace_id}"
