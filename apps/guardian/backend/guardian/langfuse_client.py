"""Versioned Langfuse reads with explicit completeness and shared normalization.

The legacy offset API is not a consistent snapshot. Fixed time bounds/page sizes
and repeated-ID detection expose bounded traversal evidence, not lossless ingestion.
See docs/TELEMETRY.md for checkpoint and remaining replay/late-arrival boundaries.
"""
from collections import Counter
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any, List, Optional
from urllib.parse import quote, urlsplit

import httpx

from config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_READ_API
from .models import SourcePageResult, SourceReadResult, TraceMetric
from .source_errors import SourceReadError
from .normalization import (
    _get, _stringify, extract_cost, extract_latency_ms, extract_tokens,
    normalize_observation, utc_datetime,
)

logger = logging.getLogger(__name__)
MAX_PAGE_SIZE = 100
MAX_READ_RECORDS = 5000
READ_BUDGET_SECONDS = 15.0
PAGE_TIMEOUT_SECONDS = 5.0


# Explicit compatibility helpers; every mapper delegates to shared normalization.
def _extract_tokens(obs: Any) -> Optional[int]:
    return extract_tokens(obs)["total"]


def _extract_cost(obs: Any) -> Optional[float]:
    value = extract_cost(obs)
    return float(value) if value is not None else None


def _extract_latency_ms(obs: Any) -> Optional[float]:
    return extract_latency_ms(obs)


def _observation_to_trace_metric(obs: Any) -> Optional[TraceMetric]:
    return normalize_observation(obs).metric


def _error_code(error: Exception) -> str:
    if isinstance(error, SourceReadError):
        return error.code
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "read_timeout"
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        return "authentication_failed"
    if status == 429:
        return "rate_limited"
    if status == 404:
        return "not_found"
    return "upstream_error"


def _integer(value: Any) -> Optional[int]:
    return value if type(value) is int and value >= 0 else None


class LangfuseTraceSource:
    def __init__(self, *, api_version=None, host=None, public_key=None,
                 secret_key=None, transport=None) -> None:
        self._client = None
        self._v2 = None
        self._api_version = LANGFUSE_READ_API if api_version is None else api_version
        self._host = LANGFUSE_HOST if host is None else host
        public_key = LANGFUSE_PUBLIC_KEY if public_key is None else public_key
        secret_key = LANGFUSE_SECRET_KEY if secret_key is None else secret_key
        self._configuration_error = None
        try:
            parsed = urlsplit(self._host)
            port = parsed.port  # Validates numeric syntax and the URL port range.
            valid_host = (parsed.scheme in {"http", "https"} and parsed.hostname
                          and not parsed.username and not parsed.password
                          and not parsed.query and not parsed.fragment
                          and (port is None or 1 <= port <= 65535))
            if self._api_version not in {"v1", "v2"} or not valid_host:
                raise ValueError("Unsupported source configuration")
        except (TypeError, ValueError):
            self._configuration_error = "invalid_configuration"
            return
        if public_key and secret_key:
            try:
                if self._api_version == "v2":
                    from .langfuse_v2 import ObservationsV2Client
                    self._v2 = ObservationsV2Client(self._host, public_key, secret_key, transport=transport)
                else:
                    from langfuse import Langfuse
                    self._client = Langfuse(
                        public_key=public_key, secret_key=secret_key,
                        host=self._host, timeout=5, max_retries=1,
                    )
            except Exception:
                self._configuration_error = "invalid_configuration"
                logger.error("[Guardian] Langfuse initialization failed")

    @property
    def available(self) -> bool:
        return self._v2 is not None if self.api_version == "v2" else self._client is not None

    @property
    def api_version(self) -> str:
        value = getattr(self, "_api_version", LANGFUSE_READ_API)
        return value if value in ("v1", "v2") else "invalid"

    @property
    def configuration_error(self):
        return getattr(self, "_configuration_error", None)

    def close(self):
        if getattr(self, "_v2", None) is not None:
            self._v2.close()
        elif getattr(self, "_client", None) is not None:
            shutdown = getattr(self._client, "shutdown", None)
            if callable(shutdown):
                shutdown()

    @property
    def client(self):
        return self._client

    def read_sdk(self, operation: str, *, timeout_seconds: float = PAGE_TIMEOUT_SECONDS, **kwargs):
        """One bounded generated SDK2 call, shared by observations and trace views.

        SDK2's top-level fetch_observations/fetch_traces helpers omit request_options.
        The generated client can pass timeout=None, overriding its httpx timeout.
        Explicit per-request time/retry settings here avoid that wrapper behavior.
        Installed SDK2 path is client.client.*, NOT SDK3's client.api.*.

        Injected minimal fake clients retain fetch_* fallback for existing offline
        fixtures; production Langfuse2.53.9 always takes the generated-client path.
        Network-stage timeouts are not hard wall-clock cancellation of a sync thread.
        """
        if self.api_version != "v1":
            raise SourceReadError("invalid_query")
        if not self.available:
            raise SourceReadError("not_configured")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise SourceReadError("read_timeout")
        routes = {
            "observations": ("observations", "get_many", "fetch_observations"),
            "traces": ("trace", "list", "fetch_traces"),
            "trace": ("trace", "get", "fetch_trace"),
        }
        if operation not in routes:
            raise SourceReadError("invalid_query")
        resource_name, method_name, fallback_name = routes[operation]
        try:
            generated = getattr(self._client, "client", None)
            resource = getattr(generated, resource_name, None)
            method = getattr(resource, method_name, None)
            if callable(method):
                return method(**kwargs, request_options={
                    "timeout_in_seconds": min(PAGE_TIMEOUT_SECONDS, timeout_seconds), "max_retries": 0,
                })
            return getattr(self._client, fallback_name)(**kwargs)
        except Exception as error:
            raise SourceReadError(_error_code(error)) from None

    def fetch_generation_page(
        self, since: datetime, until: datetime, *, cursor: Optional[str] = None,
        expected_query_fingerprint: Optional[str] = None, page_size: int = MAX_PAGE_SIZE,
        trace_id: Optional[str] = None, timeout_seconds: float = PAGE_TIMEOUT_SECONDS,
    ) -> SourcePageResult:
        """One durable-ingestion page; legacy offset reads are not resumable.

        V1's existing bounded whole-window reader remains available separately.
        A failed page carries no rows the worker may commit or advance past.
        """
        if self.api_version == "v2" and getattr(self, "_v2", None) is not None:
            return self._v2.fetch_generation_page(
                since, until, cursor=cursor,
                expected_query_fingerprint=expected_query_fingerprint,
                page_size=page_size, trace_id=trace_id, timeout_seconds=timeout_seconds,
            )
        code = self.configuration_error or (
            "unsupported_resumable_source" if self.api_version == "v1" else "not_configured"
        )
        if self.api_version == "invalid":
            code = "invalid_configuration"
        return SourcePageResult(
            [], "failed", api_version=self.api_version,
            normalization_version="langfuse-v2-1" if self.api_version == "v2" else "legacy-v1",
            window_start=utc_datetime(since), window_end=utc_datetime(until),
            request_cursor=cursor, error_code=code,
        )

    def fetch_generations(
        self, since: datetime, until: Optional[datetime] = None, limit: int = 500,
        trace_id: Optional[str] = None, *, timeout_seconds: float = READ_BUDGET_SECONDS,
    ) -> SourceReadResult:
        if self.api_version == "v2":
            if self._v2 is not None:
                return self._v2.fetch_generations(
                    since, until=until, limit=limit, trace_id=trace_id,
                    timeout_seconds=timeout_seconds,
                )
            return SourceReadResult(
                [], "failed", api_version="v2", window_start=utc_datetime(since),
                window_end=utc_datetime(until),
                error_code=getattr(self, "_configuration_error", None) or "not_configured",
            )
        if self.api_version != "v1":
            return SourceReadResult([], "failed", api_version="invalid", error_code="invalid_configuration")
        started = utc_datetime(since)
        ended = utc_datetime(until) if until is not None else datetime.now(timezone.utc)
        result = SourceReadResult([], "failed", window_start=started, window_end=ended)
        issues: Counter = Counter()

        def finish(error=None, next_page=None):
            result.fetched_at = datetime.now(timezone.utc)
            result.issues = dict(issues)
            result.next_page = next_page
            if error is None and result.invalid_count:
                error = "invalid_observation"
            if error is None and issues["inconsistent_token_total"]:
                error = "inconsistent_measurement"
            if error is None and result.duplicate_count:
                error = "conflicting_revision" if issues["conflicting_revision"] else "duplicate_observation"
            result.error_code = error
            if error:
                result.status = "partial" if result.records_read else "failed"
                logger.warning("[Guardian] Source read %s: %s", result.status, error)
            else:
                result.status = "complete"
            return result

        if started is None or ended is None or ended <= started:
            return finish("invalid_window")
        if type(limit) is not int or not 1 <= limit <= MAX_READ_RECORDS:
            return finish("invalid_query")
        if trace_id is not None and (not isinstance(trace_id, str) or not trace_id.strip()):
            return finish("invalid_query")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            return finish("invalid_query")
        if not self.available:
            return finish(self.configuration_error or "not_configured")

        deadline = time.monotonic() + timeout_seconds
        page_size = min(MAX_PAGE_SIZE, limit)  # FIXED for all offset-based pages.
        consumed = 0
        seen = {}
        first_total = None
        traversal_issue = None
        page = 1
        while consumed < limit:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                return finish("read_timeout", page)
            kwargs = {
                "type": "GENERATION", "from_start_time": started, "to_start_time": ended,
                "limit": page_size, "page": page,
            }
            if trace_id is not None:
                kwargs["trace_id"] = trace_id
            try:
                response = self.read_sdk("observations", timeout_seconds=remaining_time, **kwargs)
            except SourceReadError as error:
                return finish(error.code, page)
            batch = _get(response, "data")
            if not isinstance(batch, (list, tuple)):
                return finish("invalid_response", page)
            result.pages_fetched += 1
            result.records_read += len(batch)
            if len(batch) > page_size:
                traversal_issue = "invalid_response"
            accepted_batch = batch[:min(page_size, limit - consumed)]
            consumed += len(accepted_batch)
            for obs in accepted_batch:
                normalized = normalize_observation(obs)
                issues.update(normalized.issues)
                metric = normalized.metric
                if metric is None:
                    result.invalid_count += 1
                    continue
                if not started <= metric.timestamp < ended or (trace_id is not None and metric.trace_id != trace_id):
                    issues["outside_query"] += 1
                    result.invalid_count += 1
                    continue
                previous = seen.get(metric.observation_id)
                if previous is not None:
                    result.duplicate_count += 1
                    issues["duplicate_observation"] += 1
                    if previous.revision_fingerprint != metric.revision_fingerprint:
                        issues["conflicting_revision"] += 1
                    continue
                seen[metric.observation_id] = metric
                result.metrics.append(metric)

            if time.monotonic() >= deadline:
                return finish("read_timeout", page + 1)
            meta = _get(response, "meta")
            total_items = _integer(_get(meta, "total_items", "totalItems"))
            total_pages = _integer(_get(meta, "total_pages", "totalPages"))
            if meta is not None:
                meta_page = _integer(_get(meta, "page"))
                meta_limit = _integer(_get(meta, "limit"))
                if meta_page != page or meta_limit != page_size or total_items is None or total_pages is None:
                    traversal_issue = "invalid_response"
                else:
                    expected_pages = (total_items + page_size - 1) // page_size
                    empty_metadata = total_items == 0 and total_pages in (0, 1)
                    if total_pages != expected_pages and not empty_metadata:
                        traversal_issue = "invalid_response"
                    if first_total is None:
                        first_total = total_items
                    elif total_items != first_total:
                        issues["pagination_changed"] += 1
                        traversal_issue = "pagination_changed"
                    expected_count = max(0, min(page_size, total_items - (page - 1) * page_size))
                    if len(batch) != expected_count:
                        traversal_issue = "invalid_response"

            trimmed = len(accepted_batch) < len(batch)
            exhausted = len(batch) < page_size
            if total_items is not None and total_pages is not None:
                exhausted = page >= total_pages and consumed >= total_items
            if exhausted and not trimmed:
                return finish(traversal_issue)
            if consumed >= limit or trimmed:
                return finish(traversal_issue or "limit_reached", page if trimmed else page + 1)
            if not batch:
                return finish(traversal_issue or "invalid_response", page)
            page += 1
        return finish("limit_reached", page)

    def fetch_recent_generations(self, since: datetime, limit: int = 200) -> List[TraceMetric]:
        """Compatibility only: discards coverage. Worker/live use fetch_generations."""
        return self.fetch_generations(since=since, limit=limit).metrics

    def trace_url(self, trace_id: str) -> Optional[str]:
        if not trace_id:
            return None
        return f"{getattr(self, '_host', LANGFUSE_HOST).rstrip('/')}/trace/{quote(trace_id, safe='')}"
