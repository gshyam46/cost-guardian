"""One source mapping for detectors and live views. No network or persistence.

Unknown measurements stay absent; zero is a measurement. Invalid required identity
or ambiguous time rejects a row. Optional malformed values are reported by safe
codes and may fall back to a valid documented alternative. Raw content never enters
revision fingerprints or issue codes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
from typing import Any, Optional

from .models import NormalizationResult, TraceMetric

MAX_TOKEN_COUNT = (1 << 63) - 1


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return None


def utc_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _text(value: Any) -> Optional[str]:
    value = getattr(value, "value", value)
    return value if isinstance(value, str) and value.strip() else None


def _trace_tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(tag for tag in value if isinstance(tag, str) and tag.strip()))


def _number(value: Any, *, integer=False) -> Optional[Decimal]:
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        if len(str(value)) > 256:
            return None
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or not math.isfinite(float(number)):
            return None
        if number != 0 and float(number) == 0:
            return None  # An underflowed unknown must not become a reported zero.
        if integer and (number != number.to_integral_value() or number > MAX_TOKEN_COUNT):
            return None
        return number
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None


def _pick_numeric(values, field: str, issues: list[str], *, integer=False):
    for value in values:
        if value is None:
            continue
        parsed = _number(value, integer=integer)
        if parsed is not None:
            return parsed
        issues.append("invalid_" + field)
    return None


def extract_tokens(obs: Any, issues: Optional[list[str]] = None) -> dict[str, Optional[int]]:
    issues = [] if issues is None else issues
    sources = []
    # Try each container independently; {} must not hide useful legacy fields.
    for name in ("usage_details", "usageDetails", "usage"):
        container = _get(obs, name)
        if container is None:
            continue
        unit = _text(_get(container, "unit"))
        if unit and unit.upper() != "TOKENS":
            issues.append("non_token_usage")
            continue
        sources.append(container)
    aliases = {
        "input": ("input", "input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
        "output": ("output", "output_tokens", "outputTokens", "completion_tokens", "completionTokens"),
        "total": ("total", "total_tokens", "totalTokens"),
    }
    top_aliases = {
        "input": ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "input_usage"),
        "output": ("output_tokens", "outputTokens", "completion_tokens", "completionTokens", "output_usage"),
        "total": ("total_tokens", "totalTokens"),
    }
    values = {}
    for key in aliases:
        possibilities = []
        for container in sources:
            possibilities.extend(_get(container, name) for name in aliases[key])
            if key == "total":
                # A complete modern split is authoritative before a stale legacy
                # total. An explicit modern total, including 0, still comes first.
                inp = _pick_numeric([_get(container, name) for name in aliases["input"]], "input_tokens", issues, integer=True)
                out = _pick_numeric([_get(container, name) for name in aliases["output"]], "output_tokens", issues, integer=True)
                if inp is not None and out is not None:
                    possibilities.append(inp + out)
        possibilities.extend(_get(obs, name) for name in top_aliases[key])
        result = _pick_numeric(possibilities, key + "_tokens", issues, integer=True)
        values[key] = int(result) if result is not None else None
    if values["total"] is None and values["input"] is not None and values["output"] is not None:
        summed = values["input"] + values["output"]
        if summed <= MAX_TOKEN_COUNT:
            values["total"] = summed
        else:
            issues.append("invalid_total_tokens")
    if all(values[key] is not None for key in ("input", "output", "total")):
        if values["total"] != values["input"] + values["output"]:
            issues.append("inconsistent_token_total")
    return values


def extract_cost(obs: Any, issues: Optional[list[str]] = None) -> Optional[Decimal]:
    issues = [] if issues is None else issues
    choices = [
        _get(obs, name) for name in (
            "calculated_total_cost", "calculatedTotalCost", "total_cost", "totalCost", "cost"
        )
    ]
    for name in ("cost_details", "costDetails", "usage"):
        container = _get(obs, name)
        choices.append(_get(container, "total", "total_cost", "totalCost") if name != "usage" else _get(container, "total_cost", "totalCost"))
    result = _pick_numeric(choices, "cost", issues)
    if result is not None:
        return result
    # Only sum explicitly supplied cost components, never infer a missing side as 0.
    for name in ("cost_details", "costDetails", "usage"):
        container = _get(obs, name)
        if name == "usage":
            inp = _get(container, "input_cost", "inputCost")
            out = _get(container, "output_cost", "outputCost")
        else:
            inp, out = _get(container, "input"), _get(container, "output")
        first = _pick_numeric([inp], "cost", issues)
        second = _pick_numeric([out], "cost", issues)
        if first is not None and second is not None:
            with localcontext() as context:
                context.prec = max(len(first.as_tuple().digits), len(second.as_tuple().digits)) + abs(first.adjusted() - second.adjusted()) + 2
                summed = first + second
            if math.isfinite(float(summed)):
                return summed
            issues.append("invalid_cost")
    return None


def extract_latency_ms(obs: Any, issues: Optional[list[str]] = None) -> Optional[float]:
    issues = [] if issues is None else issues
    seconds = _pick_numeric([_get(obs, "latency")], "latency", issues)
    if seconds is not None:
        millis = float(seconds * 1000)
        if math.isfinite(millis):
            return millis
        issues.append("invalid_latency")
    started = utc_datetime(_get(obs, "start_time", "startTime"))
    ended = utc_datetime(_get(obs, "end_time", "endTime"))
    if started is not None and ended is not None:
        if ended >= started:
            return (ended - started).total_seconds() * 1000
        issues.append("invalid_latency")
    return None


def _decimal_text(number: Optional[Decimal]) -> Optional[str]:
    if number is None:
        return None
    if number == 0:
        return "0"
    # Avoid Decimal.normalize's ambient precision rounding of supplied strings.
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fingerprint(metric: TraceMetric) -> str:
    fields = (
        "observation_id", "trace_id", "source", "observation_kind", "project_id",
        "environment", "version", "parent_observation_id", "agent_name", "model",
        "cost_usd_decimal", "total_tokens", "input_tokens", "output_tokens",
        "latency_ms", "time_to_first_token_ms", "status", "completion_state",
        "timestamp", "ended_at", "updated_at",
    )
    safe = {}
    for name in fields:
        value = getattr(metric, name)
        safe[name] = value.isoformat() if isinstance(value, datetime) else value
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_observation(obs: Any) -> NormalizationResult:
    issues: list[str] = []
    try:
        observation_id = _text(_get(obs, "id", "observation_id", "observationId"))
        trace_id = _text(_get(obs, "trace_id", "traceId"))
        started = utc_datetime(_get(obs, "start_time", "startTime"))
        if observation_id is None:
            issues.append("missing_observation_id")
        if trace_id is None:
            issues.append("missing_trace_id")
        if started is None:
            issues.append("invalid_start_time")
        if issues:
            return NormalizationResult(None, "invalid", tuple(issues))
        kind = _text(_get(obs, "type", "observation_kind")) or "GENERATION"
        kind = kind.upper()
        if kind != "GENERATION":
            return NormalizationResult(None, "invalid", ("unsupported_observation_kind",))

        tokens = extract_tokens(obs, issues)
        cost = extract_cost(obs, issues)
        latency = extract_latency_ms(obs, issues)
        raw_end = _get(obs, "end_time", "endTime")
        ended = utc_datetime(raw_end)
        if raw_end is not None and (ended is None or ended < started):
            issues.append("invalid_end_time")
            ended = None
        raw_updated = _get(obs, "updated_at", "updatedAt", "updated_time", "updatedTime")
        updated = utc_datetime(raw_updated)
        if raw_updated is not None and updated is None:
            issues.append("invalid_updated_time")
        level = (_text(_get(obs, "level")) or "UNKNOWN").upper()
        if level == "ERROR":
            status, completion = "error", "complete"
        elif ended is not None or latency is not None:
            status = "success" if level in {"DEFAULT", "DEBUG", "WARNING"} else "unknown"
            completion = "complete"
        else:
            status, completion = "unknown", "in_progress" if level in {"DEFAULT", "DEBUG", "WARNING"} else "unknown"
        ttft = _pick_numeric([_get(obs, "time_to_first_token", "timeToFirstToken")], "time_to_first_token", issues)
        ttft_ms = float(ttft * 1000) if ttft is not None else None
        if ttft_ms is not None and not math.isfinite(ttft_ms):
            issues.append("invalid_time_to_first_token")
            ttft_ms = None
        for missing, label in ((cost, "cost"), (tokens["total"], "tokens"), (latency, "latency")):
            if missing is None:
                issues.append("missing_" + label)
        metadata = _get(obs, "metadata")
        metric = TraceMetric(
            trace_id=trace_id, observation_id=observation_id, observation_kind=kind,
            agent_name=_text(_get(obs, "name")) or "unknown",
            model=_text(_get(obs, "model")) or "unknown",
            cost_usd=float(cost) if cost is not None else None, cost_usd_decimal=_decimal_text(cost),
            total_tokens=tokens["total"], input_tokens=tokens["input"], output_tokens=tokens["output"],
            latency_ms=latency, timestamp=started, ended_at=ended, updated_at=updated,
            status=status, completion_state=completion,
            project_id=_text(_get(obs, "project_id", "projectId")),
            environment=_text(_get(obs, "environment")) or _text(_get(metadata, "environment")),
            version=_text(_get(obs, "version")),
            parent_observation_id=_text(_get(obs, "parent_observation_id", "parentObservationId")),
            output_text=_stringify(_get(obs, "output")),
            status_message=_stringify(_get(obs, "status_message", "statusMessage")),
            time_to_first_token_ms=ttft_ms,
            trace_name=_text(_get(obs, "trace_name", "traceName")),
            user_id=_text(_get(obs, "user_id", "userId")),
            session_id=_text(_get(obs, "session_id", "sessionId")),
            trace_tags=_trace_tags(_get(obs, "tags")),
            normalization_issues=tuple(dict.fromkeys(issues)),
        )
        metric.revision_fingerprint = _fingerprint(metric)
        return NormalizationResult(metric, "valid", metric.normalization_issues)
    except Exception:
        # Do not stringify SDK objects/errors: they can contain payloads or secrets.
        return NormalizationResult(None, "invalid", ("malformed_observation",))
