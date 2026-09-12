"""Read-only, bounded Langfuse Observations API v2 transport.

Completion describes traversal of the accessible source window, not settlement of
late observations. Cursors are opaque, internal continuation hints, never durable
ingestion checkpoints. No legacy request or exporter SDK is used on this path.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import logging
import math
import time
from typing import Any

import httpx

from .models import NormalizationResult, SourcePageResult, SourceReadResult, SourceRowDisposition
from .normalization import _fingerprint, _number, normalize_observation, utc_datetime
from .source_errors import SourceReadError

PAGE_SIZE = 100
MAX_READ_RECORDS = 5000
READ_BUDGET_SECONDS = 15.0
PAGE_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CURSOR_LENGTH = 8192
COST_RELATIVE_TOLERANCE = Decimal("1e-12")
FIELDS = "core,basic,time,model,usage,metrics,trace_context,io"
NORMALIZATION_VERSION = "langfuse-v2-1"
MAX_ID_LENGTH = 512


class _HideObservationQuery(logging.Filter):
    """HTTPX's INFO request record must not expose the internal cursor or host."""

    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 4:
            url = record.args[1]
            if isinstance(url, httpx.URL) and url.path.endswith("/api/public/v2/observations"):
                # HTTP version and reason phrase also originate upstream. Keep
                # only this reader's fixed GET method and a numeric status.
                status = record.args[3] if type(record.args[3]) is int else 0
                record.msg = "HTTP Request: GET /api/public/v2/observations status=%d"
                record.args = (status,)
        return True


# Filter only this endpoint's request URL; retain HTTPX diagnostics for all other
# traffic and retain method/status for v2. Install once per module import.
logging.getLogger("httpx").addFilter(_HideObservationQuery())


def _sum(numbers: list[Decimal]) -> Decimal:
    """Preserve supplied decimal precision while adding bounded measurements."""
    # Zero's exponent carries no precision; hostile 0E-999999999 must not request
    # a giant decimal context when combined with an ordinary measurement.
    numbers = [number for number in numbers if number != 0]
    if not numbers:
        return Decimal(0)
    with localcontext() as context:
        context.prec = max(len(n.as_tuple().digits) for n in numbers) + max(
            n.adjusted() for n in numbers
        ) - min(n.adjusted() for n in numbers) + len(str(len(numbers))) + 2
        return sum(numbers, Decimal(0))


def _cost_totals_agree(reported: Decimal, summed: Decimal) -> bool:
    """Allow source float summation noise without treating positive spend as free.

    Langfuse reduces costs using JavaScript numbers. A 1e-12 relative tolerance
    admits ordinary accumulation roundoff, with no absolute-dollar allowance.
    Zero versus any positive value is always contradictory. This is a source
    consistency check; contradictory totals become unknown, never repriced.
    """
    if reported == 0 or summed == 0:
        return reported == summed
    with localcontext() as context:
        context.prec = max(len(reported.as_tuple().digits), len(summed.as_tuple().digits)) + abs(reported.adjusted() - summed.adjusted()) + 16
        return abs(reported - summed) <= max(reported, summed) * COST_RELATIVE_TOLERANCE


def _measurement_projection(raw: dict) -> tuple[dict, list[str], bool]:
    """Remove v2's synthetic aggregate zeros before common normalization.

    Langfuse's v2 converter defaults absent detail totals to zero, and uses
    exclusive usage buckets: input excludes input_cached_tokens, for example.
    A generated zero cannot prove a measurement. Explicit detail zeros can.
    Reference: shared/server/repositories/observations_converters.ts and the
    official Token & Cost Tracking documentation.
    """
    projected = dict(raw)
    issues: list[str] = []
    # No legacy alias may override the source-specific evidence rules below.
    for name in (
        "usage", "usage_details", "usageDetails", "input_tokens", "inputTokens",
        "prompt_tokens", "promptTokens", "input_usage", "output_tokens",
        "outputTokens", "completion_tokens", "completionTokens", "output_usage",
        "total_tokens", "totalTokens", "inputUsage", "outputUsage", "totalUsage",
        "cost_details", "costDetails",
        "calculated_total_cost", "calculatedTotalCost", "total_cost", "totalCost", "cost",
    ):
        projected.pop(name, None)

    def parse(value: Any, label: str, *, integer=False):
        if value is None:
            return None
        number = _number(value, integer=integer)
        if number is None:
            issues.append("invalid_" + label)
        return number

    def detail_map(name: str, label: str, *, integer=False):
        value = raw.get(name)
        if value is None:
            return {}, False
        if not isinstance(value, dict):
            issues.append("invalid_" + label + "_details")
            return {}, True  # Malformed supplied evidence cannot authorize an aggregate fallback.
        parsed = {}
        for key, number in value.items():
            parsed[key] = parse(number, label, integer=integer)
        return parsed, True

    usage, usage_supplied = detail_map("usageDetails", "tokens", integer=True)
    canonical_usage = {}
    for side in ("input", "output"):
        group = [number for key, number in usage.items() if side in key and key != "total"]
        if group and all(number is not None for number in group):
            canonical_usage[side] = _sum(group)
        elif not usage_supplied:
            aggregate = parse(raw.get(side + "Usage"), side + "_tokens", integer=True)
            # A zero aggregate without a corresponding bucket is a converter default.
            if aggregate is not None and aggregate != 0:
                canonical_usage[side] = aggregate
    total = usage.get("total")
    if total is None and not usage_supplied:
        aggregate = parse(raw.get("totalUsage"), "total_tokens", integer=True)
        if aggregate is not None and aggregate != 0:
            total = aggregate
    buckets = [number for key, number in usage.items() if key != "total"]
    complete_buckets = bool(buckets) and all(number is not None for number in buckets)
    # Derive only with both sides evidenced. A lone input bucket does not prove
    # an absent output was zero. Additional exclusive buckets participate in total.
    if total is None and complete_buckets and all(side in canonical_usage for side in ("input", "output")):
        total = _sum(buckets)
    elif total is None and not usage_supplied and all(side in canonical_usage for side in ("input", "output")):
        total = _sum([canonical_usage["input"], canonical_usage["output"]])
    if total is not None:
        canonical_usage["total"] = total
    projected["usage_details"] = canonical_usage

    # Custom buckets may be neither input nor output. The shared normalizer's
    # simple split equality is waived only when the complete detail map reconciles.
    custom_reconciles = (
        complete_buckets and total is not None and _sum(buckets) == total
        and any("input" not in key and "output" not in key and key != "total" for key in usage)
        and all(not ("input" in key and "output" in key) for key in usage)
    )

    costs, costs_supplied = detail_map("costDetails", "cost")
    cost = costs.get("total")
    if cost is None and not costs_supplied:
        aggregate = parse(raw.get("totalCost"), "cost")
        if aggregate is not None and aggregate != 0:
            cost = aggregate
    cost_buckets = [number for key, number in costs.items() if key != "total"]
    complete_cost_buckets = (
        bool(cost_buckets) and all(number is not None for number in cost_buckets)
        and any("input" in key for key in costs) and any("output" in key for key in costs)
    )
    if complete_cost_buckets:
        # V2 costs are mutually exclusive detail buckets, including custom ones.
        # Only known input AND output permit a derived overall total here.
        summed_cost = _sum(cost_buckets)
        if cost is None:
            cost = summed_cost
        elif not _cost_totals_agree(cost, summed_cost):
            issues.append("inconsistent_cost_total")
    if cost is not None:
        projected["total_cost"] = cost
    return projected, list(dict.fromkeys(issues)), custom_reconciles


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid_json_number")


def _valid_cursor(value):
    return (
        isinstance(value, str) and 0 < len(value) <= MAX_CURSOR_LENGTH
        and value.isascii() and all(32 < ord(char) < 127 for char in value)
    )


def _normalize_v2_row(raw: Any) -> NormalizationResult:
    """One scalar mapping shared by bounded views and durable page ingestion."""
    if not isinstance(raw, dict) or raw.get("type") != "GENERATION":
        issue = "unsupported_observation_kind" if isinstance(raw, dict) else "malformed_observation"
        return NormalizationResult(None, "invalid", (issue,))
    projected, projection_issues, custom_reconciles = _measurement_projection(raw)
    normalized = normalize_observation(projected)
    normalization_issues = list(normalized.issues)
    if custom_reconciles:
        normalization_issues = [item for item in normalization_issues if item != "inconsistent_token_total"]
    row_issues = tuple(dict.fromkeys(projection_issues + normalization_issues))
    metric = normalized.metric
    if metric is None:
        return NormalizationResult(None, "invalid", row_issues)
    # Generic split fallback cannot discard a v2 custom/invalid usage bucket.
    total = _number(projected["usage_details"].get("total"), integer=True)
    authoritative_total = int(total) if total is not None else None
    if "inconsistent_token_total" in row_issues:
        authoritative_total = None
    changed = False
    if metric.total_tokens != authoritative_total:
        metric.total_tokens = authoritative_total
        changed = True
        if authoritative_total is None and "missing_tokens" not in row_issues:
            row_issues += ("missing_tokens",)
    if "inconsistent_cost_total" in row_issues:
        metric.cost_usd = None
        metric.cost_usd_decimal = None
        changed = True
        if "missing_cost" not in row_issues:
            row_issues += ("missing_cost",)
    if changed:
        metric.revision_fingerprint = _fingerprint(metric)
    metric.normalization_issues = row_issues
    return NormalizationResult(metric, "valid", row_issues)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= MAX_ID_LENGTH else None


def _row_fingerprint(raw: Any, metric, issues: tuple[str, ...]) -> str:
    """Content-free scalar evidence, independent of receipt and updatedAt noise.

    Identity is scoped by the worker's stable connection; this record hash is not
    an authorization token or a globally unique identity for malformed rows.
    """
    if metric is not None:
        fields = (
            "source", "project_id", "trace_id", "observation_id", "observation_kind",
            "agent_name", "model", "environment", "version", "parent_observation_id",
            "timestamp", "ended_at", "completion_state", "status", "cost_usd_decimal",
            "total_tokens", "input_tokens", "output_tokens", "latency_ms",
            "time_to_first_token_ms",
        )
        safe = {}
        for name in fields:
            value = getattr(metric, name)
            safe[name] = value.isoformat() if isinstance(value, datetime) else value
    else:
        row = raw if isinstance(raw, dict) else {}
        # Retain only bounded identity/attribution and validated UTC times. Never
        # hash or retain output, input, statusMessage, metadata, or invalid values.
        safe = {name: _bounded_text(row.get(wire)) for name, wire in (
            ("observation_id", "id"), ("trace_id", "traceId"), ("project_id", "projectId"),
            ("agent_name", "name"), ("model", "model"), ("environment", "environment"),
            ("version", "version"), ("parent_observation_id", "parentObservationId"),
        )}
        for name, wire in (("timestamp", "startTime"), ("ended_at", "endTime")):
            parsed = utc_datetime(row.get(wire))
            safe[name] = parsed.isoformat() if parsed is not None else None
        safe["observation_kind"] = row.get("type") if row.get("type") in ("GENERATION", "SPAN", "EVENT", "EMBEDDING") else None
        safe["status"] = row.get("level") if row.get("level") in ("DEFAULT", "DEBUG", "WARNING", "ERROR") else None
        safe["row_shape"] = "object" if isinstance(raw, dict) else type(raw).__name__
        projected, projection_issues, _ = _measurement_projection(row)

        def numeric_text(value, *, integer=False):
            number = _number(value, integer=integer)
            if number is None:
                return None
            if integer:
                return int(number)
            return "0" if number == 0 else format(number, "f")

        safe["cost_usd_decimal"] = None if "inconsistent_cost_total" in projection_issues else numeric_text(projected.get("total_cost"))
        for side in ("input", "output", "total"):
            safe[side + "_tokens"] = None if side == "total" and "inconsistent_token_total" in issues else numeric_text(projected["usage_details"].get(side), integer=True)
        safe["latency_seconds"] = numeric_text(row.get("latency"))
        safe["time_to_first_token_seconds"] = numeric_text(row.get("timeToFirstToken"))
    safe["normalization_issues"] = sorted(set(issues))
    safe["normalization_version"] = NORMALIZATION_VERSION
    return _canonical_hash(safe)


class ObservationsV2Client:
    def __init__(self, host: str, public_key: str, secret_key: str, transport=None):
        # Host syntax/security validation belongs to the public source facade.
        self._url = host.rstrip("/") + "/api/public/v2/observations"
        self._credential_scope_hash = hashlib.sha256(public_key.encode("utf-8")).hexdigest()
        self._http = httpx.Client(
            auth=httpx.BasicAuth(public_key, secret_key), transport=transport,
            timeout=PAGE_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False,
            headers={"Accept-Encoding": "identity"},
        )

    def close(self):
        self._http.close()

    def _page(self, params: dict, deadline: float):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceReadError("read_timeout")
        try:
            with self._http.stream(
                "GET", self._url, params=params,
                timeout=min(PAGE_TIMEOUT_SECONDS, remaining),
            ) as response:
                status = response.status_code
                if status != 200:
                    code = {
                        400: "invalid_query", 401: "authentication_failed",
                        403: "authentication_failed", 404: "unsupported_api",
                        429: "rate_limited",
                    }.get(status, "upstream_error")
                    raise SourceReadError(code)
                # Automatic decompression could allocate an arbitrarily large
                # chunk before a byte limit can inspect it. Require the identity
                # representation requested above and fail visibly otherwise.
                if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                    raise SourceReadError("invalid_response")
                body = bytearray()
                # Do not request accumulated fixed-size chunks: a trickling
                # server could otherwise hide many reads before the deadline
                # check. Inspect every identity-encoded transport chunk instead.
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise SourceReadError("read_timeout")
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise SourceReadError("response_too_large")
                    body.extend(chunk)
                if time.monotonic() >= deadline:
                    raise SourceReadError("read_timeout")
                # Decimal preserves cost precision from the wire. V2 IO is raw
                # text, so parsing numeric measurements cannot change previews.
                return json.loads(
                    body.decode("utf-8"), parse_float=Decimal,
                    parse_constant=_reject_constant, object_pairs_hook=_unique_object,
                )
        except SourceReadError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise SourceReadError("read_timeout") from None
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            raise SourceReadError("invalid_response") from None
        except Exception:
            raise SourceReadError("upstream_error") from None

    def fetch_generation_page(
        self, since: datetime, until: datetime, *, cursor: str | None = None,
        expected_query_fingerprint: str | None = None, page_size: int = PAGE_SIZE,
        trace_id: str | None = None, timeout_seconds: float = PAGE_TIMEOUT_SECONDS,
    ) -> SourcePageResult:
        """Read exactly one untrimmed page for a pinned, resumable traversal.

        Resumption requires the initial page's query fingerprint. This prevents
        reusing a valid opaque cursor with a different query or source scope.
        The worker owns cross-page cycle detection and durable dispositions.
        """
        started, ended = utc_datetime(since), utc_datetime(until)
        result = SourcePageResult(
            [], "failed", window_start=started, window_end=ended,
            request_cursor=cursor, normalization_version=NORMALIZATION_VERSION,
        )

        def fail(code):
            result.rows = []
            result.status = "failed"
            result.error_code = code
            result.next_cursor = None
            result.exhausted = None
            result.fetched_at = datetime.now(timezone.utc)
            return result

        if started is None or ended is None or ended <= started:
            return fail("invalid_window")
        if type(page_size) is not int or not 1 <= page_size <= PAGE_SIZE:
            return fail("invalid_query")
        if trace_id is not None and _bounded_text(trace_id) is None:
            return fail("invalid_query")
        if (
            not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            return fail("invalid_query")
        if cursor is not None and not _valid_cursor(cursor):
            return fail("invalid_query")
        params = {
            "type": "GENERATION", "fromStartTime": started.isoformat(),
            "toStartTime": ended.isoformat(), "limit": page_size, "fields": FIELDS,
        }
        if trace_id is not None:
            params["traceId"] = trace_id
        result.query_fingerprint = _canonical_hash({
            "endpoint": self._url, "credential_scope": self._credential_scope_hash,
            "api_version": "v2", "normalization_version": NORMALIZATION_VERSION,
            "query": params,
        })
        if expected_query_fingerprint is not None and expected_query_fingerprint != result.query_fingerprint:
            return fail("query_mismatch")
        if cursor is not None:
            if expected_query_fingerprint is None:
                return fail("query_mismatch")
            params["cursor"] = cursor
        deadline = time.monotonic() + min(timeout_seconds, READ_BUDGET_SECONDS)
        try:
            response = self._page(params, deadline)
        except SourceReadError as error:
            return fail(error.code)
        # Reject a poisoned envelope before any row becomes committable. In
        # particular, neither an oversized page nor bad metadata can be skipped.
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            return fail("invalid_response")
        batch = response["data"]
        result.records_read = len(batch)
        meta = response.get("meta")
        if not isinstance(meta, dict) or len(batch) > page_size:
            return fail("invalid_response")
        next_cursor = meta.get("cursor")
        if next_cursor is not None and (not _valid_cursor(next_cursor) or not batch):
            return fail("invalid_response")
        if next_cursor is not None and next_cursor == cursor:
            return fail("pagination_cycle")
        issues: Counter = Counter()
        dispositions = []
        for ordinal, raw in enumerate(batch):
            if time.monotonic() >= deadline:
                return fail("read_timeout")
            normalized = _normalize_v2_row(raw)
            metric = normalized.metric
            row_issues = list(normalized.issues)
            row = raw if isinstance(raw, dict) else {}
            observation_id = _bounded_text(row.get("id"))
            trace = _bounded_text(row.get("traceId"))
            project = _bounded_text(row.get("projectId"))
            quarantined = metric is None
            if metric is not None:
                if observation_id is None:
                    row_issues.append("invalid_observation_id")
                    quarantined = True
                if trace is None:
                    row_issues.append("invalid_trace_id")
                    quarantined = True
                if project is None:
                    row_issues.append("invalid_project_id")
                    quarantined = True
                if not started <= metric.timestamp < ended or (trace_id is not None and metric.trace_id != trace_id):
                    row_issues.append("outside_query")
                    quarantined = True
                if "inconsistent_token_total" in row_issues or "inconsistent_cost_total" in row_issues:
                    quarantined = True
            safe_issues = tuple(dict.fromkeys(row_issues))
            issues.update(safe_issues)
            dispositions.append(SourceRowDisposition(
                ordinal=ordinal,
                disposition="quarantined" if quarantined else "accepted",
                metric=None if quarantined else metric,
                observation_id=observation_id, trace_id=trace,
                source_project_id=project, issues=safe_issues,
                record_fingerprint=_row_fingerprint(raw, None if quarantined else metric, safe_issues),
            ))
        if time.monotonic() >= deadline:
            return fail("read_timeout")
        result.rows = dispositions
        result.status = "ok"
        result.next_cursor = next_cursor
        result.exhausted = next_cursor is None
        result.issues = dict(issues)
        result.fetched_at = datetime.now(timezone.utc)
        return result

    def fetch_generations(
        self, since: datetime, until: datetime | None = None, limit: int = 500,
        trace_id: str | None = None, *, timeout_seconds: float = READ_BUDGET_SECONDS,
    ) -> SourceReadResult:
        started = utc_datetime(since)
        ended = utc_datetime(until) if until is not None else datetime.now(timezone.utc)
        result = SourceReadResult(
            [], "failed", window_start=started, window_end=ended, api_version="v2",
        )
        issues: Counter = Counter()

        def finish(error=None, next_cursor=None):
            result.fetched_at = datetime.now(timezone.utc)
            result.issues = dict(issues)
            result.next_cursor = next_cursor
            if error is None and result.invalid_count:
                error = "invalid_observation"
            if error is None and (issues["inconsistent_token_total"] or issues["inconsistent_cost_total"]):
                error = "inconsistent_measurement"
            if error is None and result.duplicate_count:
                error = "conflicting_revision" if issues["conflicting_revision"] else "duplicate_observation"
            result.error_code = error
            result.status = ("partial" if result.records_read else "failed") if error else "complete"
            return result

        if started is None or ended is None or ended <= started:
            return finish("invalid_window")
        if type(limit) is not int or not 1 <= limit <= MAX_READ_RECORDS:
            return finish("invalid_query")
        if trace_id is not None and (not isinstance(trace_id, str) or not trace_id.strip()):
            return finish("invalid_query")
        if (
            not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            return finish("invalid_query")

        deadline = time.monotonic() + min(timeout_seconds, READ_BUDGET_SECONDS)
        page_size = min(PAGE_SIZE, limit)
        max_pages = (limit + page_size - 1) // page_size
        params = {
            "type": "GENERATION", "fromStartTime": started.isoformat(),
            "toStartTime": ended.isoformat(), "limit": page_size, "fields": FIELDS,
        }
        if trace_id is not None:
            params["traceId"] = trace_id
        cursor = None
        seen_cursors = set()
        seen_observations = {}
        consumed = 0
        while consumed < limit:
            try:
                response = self._page(params, deadline)
            except SourceReadError as error:
                return finish(error.code, cursor)
            if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                return finish("invalid_response", cursor)
            batch = response["data"]
            result.pages_fetched += 1
            result.records_read += len(batch)
            accepted = batch[:min(page_size, limit - consumed)]
            consumed += len(accepted)
            for raw in accepted:
                if time.monotonic() >= deadline:
                    return finish("read_timeout", cursor)
                normalized = _normalize_v2_row(raw)
                issues.update(normalized.issues)
                metric = normalized.metric
                if metric is None:
                    result.invalid_count += 1
                    continue
                if not started <= metric.timestamp < ended or (trace_id is not None and metric.trace_id != trace_id):
                    result.invalid_count += 1
                    issues["outside_query"] += 1
                    continue
                identity = (metric.trace_id, metric.observation_id)
                previous = seen_observations.get(identity)
                if previous is not None:
                    result.duplicate_count += 1
                    issues["duplicate_observation"] += 1
                    if previous.revision_fingerprint != metric.revision_fingerprint:
                        issues["conflicting_revision"] += 1
                    continue
                seen_observations[identity] = metric
                result.metrics.append(metric)

            if time.monotonic() >= deadline:
                return finish("read_timeout", cursor)
            meta = response.get("meta")
            if not isinstance(meta, dict) or len(batch) > page_size:
                return finish("invalid_response", cursor)
            next_cursor = meta.get("cursor")
            if next_cursor is not None and not _valid_cursor(next_cursor):
                return finish("invalid_response", cursor)
            if next_cursor is not None and not batch:
                return finish("invalid_response", cursor)
            if next_cursor is not None and next_cursor in seen_cursors:
                return finish("pagination_cycle", cursor)
            # A trimmed response's next cursor would skip unconsumed records.
            # Keep its input cursor so a future replay can read the whole page.
            if len(accepted) < len(batch):
                return finish("limit_reached", cursor)
            if next_cursor is None:
                return finish()
            if consumed >= limit:
                return finish("limit_reached", next_cursor)
            if result.pages_fetched >= max_pages:
                return finish("page_limit_reached", next_cursor)
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            params["cursor"] = cursor
        return finish("limit_reached", cursor)
