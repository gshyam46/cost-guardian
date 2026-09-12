"""Shared mapping acceptance cases: identities, missingness and safe revisions."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from langfuse.api.resources.commons.types.observation_level import ObservationLevel
from langfuse.api.resources.commons.types.observations_view import ObservationsView

from guardian.normalization import normalize_observation


def observation(**overrides):
    result = {
        "id": "observation-1", "traceId": "workflow-1", "type": "GENERATION",
        "name": "answer", "model": "model", "startTime": "2026-01-01T10:00:00+05:30",
        "endTime": "2026-01-01T10:00:01+05:30", "level": "DEFAULT",
        "usage": {"input": 12, "output": 8}, "calculatedTotalCost": "0.012345678901234567890123456789",
    }
    result.update(overrides)
    return result


def test_sdk_view_object_and_wire_dictionary_share_normalization():
    wire = observation(calculatedTotalCost=0.002)
    parsed = ObservationsView.parse_obj(wire)
    first, second = normalize_observation(wire).metric, normalize_observation(parsed).metric
    assert first == second
    assert first.observation_id == "observation-1"
    assert first.timestamp == datetime(2026, 1, 1, 4, 30, tzinfo=timezone.utc)
    assert first.ended_at == datetime(2026, 1, 1, 4, 30, 1, tzinfo=timezone.utc)
    assert (first.input_tokens, first.output_tokens, first.total_tokens) == (12, 8, 20)
    assert first.latency_ms == 1000


@pytest.mark.parametrize("field,value,issue", [
    ("id", None, "missing_observation_id"), ("id", " ", "missing_observation_id"),
    ("traceId", "", "missing_trace_id"), ("startTime", None, "invalid_start_time"),
    ("startTime", "garbage", "invalid_start_time"),
    ("startTime", "2026-01-01T10:00:00", "invalid_start_time"),
    ("startTime", datetime(2026, 1, 1), "invalid_start_time"),
    ("type", "SPAN", "unsupported_observation_kind"),
])
def test_missing_identity_or_ambiguous_timestamp_is_explicitly_invalid(field, value, issue):
    result = normalize_observation(observation(**{field: value}))
    assert result.disposition == "invalid"
    assert result.metric is None
    assert issue in result.issues


def test_missing_measurements_and_unfinished_calls_do_not_become_zero_or_success():
    result = normalize_observation(observation(usage=None, calculatedTotalCost=None, endTime=None))
    metric = result.metric
    assert result.disposition == "valid"
    assert (metric.cost_usd, metric.total_tokens, metric.latency_ms) == (None, None, None)
    assert metric.cost_usd_decimal is None
    assert metric.status == "unknown"
    assert metric.completion_state == "in_progress"
    assert {"missing_cost", "missing_tokens", "missing_latency"} <= set(result.issues)


def test_reported_zero_survives_modern_and_legacy_fallbacks():
    metric = normalize_observation(observation(
        usageDetails={"total": 0, "input": 0, "output": 0}, usage={"total": 50},
        calculatedTotalCost=0, costDetails={"total": 5}, latency=0,
    )).metric
    assert (metric.cost_usd, metric.total_tokens, metric.latency_ms) == (0, 0, 0)
    assert metric.cost_usd_decimal == "0"


def test_empty_modern_usage_falls_back_to_populated_legacy():
    metric = normalize_observation(observation(usageDetails={}, usage_details={})).metric
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens) == (12, 8, 20)


def test_complete_modern_token_split_precedes_stale_legacy_total():
    metric = normalize_observation(observation(
        usageDetails={"input": 100, "output": 50}, usage={"input": 12, "output": 8, "total": 20},
    )).metric
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens) == (100, 50, 150)


def test_explicit_modern_total_zero_is_preserved_but_contradiction_is_visible():
    result = normalize_observation(observation(usageDetails={"input": 10, "output": 20, "total": 0}))
    assert result.metric.total_tokens == 0
    assert "inconsistent_token_total" in result.issues


def test_partial_usage_does_not_invent_missing_component():
    metric = normalize_observation(observation(usage={"input": 12})).metric
    assert metric.input_tokens == 12
    assert metric.output_tokens is None
    assert metric.total_tokens is None


def test_non_token_units_are_not_labelled_as_tokens():
    result = normalize_observation(observation(usage={"input": 12, "output": 8, "unit": "CHARACTERS"}))
    assert result.metric.total_tokens is None
    assert "non_token_usage" in result.issues


@pytest.mark.parametrize("invalid", [True, False, "bad", -1, float("nan"), float("inf"), "1e-9999"])
def test_invalid_cost_values_stay_unknown(invalid):
    result = normalize_observation(observation(calculatedTotalCost=invalid))
    assert result.disposition == "valid"
    assert result.metric.cost_usd is None
    assert "invalid_cost" in result.issues


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "2.1", float("inf"), 1 << 63])
def test_invalid_whole_token_counts_stay_unknown(invalid):
    result = normalize_observation(observation(usage={"total": invalid}))
    assert result.metric.total_tokens is None
    assert "invalid_total_tokens" in result.issues


def test_invalid_modern_measurement_can_use_valid_legacy_with_issue():
    result = normalize_observation(observation(
        usageDetails={"input": "bad", "output": "bad", "total": "bad"},
        calculatedTotalCost="bad", costDetails={"total": 0.125},
        latency="bad",
    ))
    assert (result.metric.total_tokens, result.metric.cost_usd, result.metric.latency_ms) == (20, 0.125, 1000)
    assert {"invalid_total_tokens", "invalid_cost", "invalid_latency"} <= set(result.issues)


def test_sdk_enum_error_is_a_failure_without_a_latency_or_end():
    metric = normalize_observation(observation(level=ObservationLevel.ERROR, endTime=None)).metric
    assert metric.status == "error"
    assert metric.completion_state == "complete"
    assert metric.latency_ms is None


def test_decimal_fingerprint_preserves_exact_string_and_excludes_content():
    original = observation(output="private output", statusMessage="private provider error")
    first = normalize_observation(original).metric
    second = normalize_observation(original | {"output": "different content", "statusMessage": "different error"}).metric
    changed = normalize_observation(original | {"calculatedTotalCost": "0.012345678901234567890123456788"}).metric
    assert first.cost_usd_decimal == "0.012345678901234567890123456789"
    assert first.revision_fingerprint == second.revision_fingerprint
    assert first.revision_fingerprint != changed.revision_fingerprint
    assert len(first.revision_fingerprint) == 64
    assert first.revision == first.revision_fingerprint


def test_equivalent_decimal_representations_have_identical_revisions():
    first = normalize_observation(observation(calculatedTotalCost="2.00")).metric
    second = normalize_observation(observation(calculatedTotalCost=Decimal("2"))).metric
    assert first.revision_fingerprint == second.revision_fingerprint


def test_timing_and_attribution_fields_are_retained_without_security_inference():
    metric = normalize_observation(observation(
        updatedAt="2026-01-01T05:00:00Z", projectId="source-project", environment="test",
        parentObservationId="parent", version="release-1", timeToFirstToken=0.15,
    )).metric
    assert metric.updated_at == datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    assert (metric.project_id, metric.environment, metric.parent_observation_id, metric.version) == ("source-project", "test", "parent", "release-1")
    assert metric.time_to_first_token_ms == 150


def test_optional_bad_timestamps_do_not_overwrite_valid_start():
    result = normalize_observation(observation(endTime="2025-12-31T00:00:00Z", updatedAt="invalid"))
    assert result.metric.timestamp == datetime(2026, 1, 1, 4, 30, tzinfo=timezone.utc)
    assert result.metric.ended_at is None
    assert result.metric.updated_at is None
    assert result.metric.latency_ms is None
    assert {"invalid_end_time", "invalid_updated_time"} <= set(result.issues)


def test_diagnostics_never_stringify_malformed_sdk_objects():
    class Hostile:
        @property
        def id(self):
            raise RuntimeError("private-provider-token")

    result = normalize_observation(Hostile())
    assert result.issues == ("malformed_observation",)
    assert "private" not in str(result)
