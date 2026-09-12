"""Bounded pagination and actual installed SDK serialization, with no network."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from langfuse import Langfuse
import pytest

from guardian.langfuse_client import LangfuseTraceSource, SourceReadError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


def observation(index=0, **overrides):
    row = {
        "id": f"observation-{index}", "traceId": f"workflow-{index}", "type": "GENERATION",
        "name": "answer", "model": "model", "startTime": "2026-01-01T01:00:00Z",
        "level": "DEFAULT", "latency": 0.5, "usage": {"total": 20}, "calculatedTotalCost": 0.01,
    }
    row.update(overrides)
    return row


class PaginatedSDK:
    def __init__(self, rows, metadata=True, error_page=None):
        self.rows = rows
        self.metadata = metadata
        self.error_page = error_page
        self.calls = []

    def fetch_observations(self, **kwargs):
        self.calls.append(kwargs)
        page, size = kwargs["page"], kwargs["limit"]
        if page == self.error_page:
            raise ConnectionError("private-provider-token must not appear in diagnostics")
        offset = (page - 1) * size
        response = SimpleNamespace(data=self.rows[offset:offset + size])
        if self.metadata:
            response.meta = SimpleNamespace(page=page, limit=size, total_items=len(self.rows), total_pages=(len(self.rows) + size - 1) // size)
        return response


def source(client):
    # Avoid constructor/background SDK tracing; fixture must never load real keys.
    result = LangfuseTraceSource.__new__(LangfuseTraceSource)
    result._api_version = "v1"
    result._client = client
    return result


def read(client, **kwargs):
    return source(client).fetch_generations(START, until=END, **kwargs)


def test_250_rows_traverse_distinct_fixed_size_pages_without_offset_drift():
    sdk = PaginatedSDK([observation(index) for index in range(250)])
    result = read(sdk, limit=250)
    assert result.complete
    assert result.pages_fetched == 3
    assert result.records_read == 250
    assert [call["limit"] for call in sdk.calls] == [100, 100, 100]
    assert [call["page"] for call in sdk.calls] == [1, 2, 3]
    assert [metric.observation_id for metric in result.metrics] == [f"observation-{index}" for index in range(250)]
    assert all(call["from_start_time"] == START and call["to_start_time"] == END for call in sdk.calls)


def test_final_page_trimming_is_partial_with_current_page_resume_hint():
    sdk = PaginatedSDK([observation(index) for index in range(300)])
    result = read(sdk, limit=250)
    assert result.status == "partial"
    assert result.error_code == "limit_reached"
    assert len(result.metrics) == 250
    assert result.records_read == 300
    assert result.next_page == 3  # Last 50 rows from page 3 have not been consumed.
    assert {metric.observation_id for metric in result.metrics} == {f"observation-{index}" for index in range(250)}


@pytest.mark.parametrize("metadata,expected", [(True, "complete"), (False, "partial")])
def test_exact_cap_requires_exhaustion_evidence(metadata, expected):
    result = read(PaginatedSDK([observation(index) for index in range(100)], metadata=metadata), limit=100)
    assert result.status == expected
    assert result.error_code == (None if metadata else "limit_reached")


def test_unknown_metadata_short_terminal_page_proves_query_exhaustion():
    result = read(PaginatedSDK([observation()], metadata=False))
    assert result.complete
    assert result.pages_fetched == 1


@pytest.mark.parametrize("pages", [0, 1])
def test_empty_query_accepts_both_empty_metadata_page_conventions(pages):
    class Empty:
        def fetch_observations(self, **kwargs):
            return SimpleNamespace(data=[], meta=SimpleNamespace(page=1, limit=kwargs["limit"], total_items=0, total_pages=pages))
    result = read(Empty())
    assert result.complete
    assert result.metrics == []


@pytest.mark.parametrize("failed_page,status,count", [(1, "failed", 0), (2, "partial", 100)])
def test_read_failure_never_becomes_complete_empty(failed_page, status, count, caplog):
    result = read(PaginatedSDK([observation(index) for index in range(150)], error_page=failed_page))
    assert result.status == status
    assert len(result.metrics) == count
    assert result.error_code == "upstream_error"
    assert result.next_page == failed_page
    assert "private-provider-token" not in caplog.text
    assert "private-provider-token" not in repr(result)


def test_missing_credentials_are_failed_without_sdk_call():
    result = read(None)
    assert result.status == "failed"
    assert result.error_code == "not_configured"


def test_invalid_response_shape_is_failed():
    class Malformed:
        def fetch_observations(self, **kwargs):
            return {"data": None}
    result = read(Malformed())
    assert result.status == "failed"
    assert result.error_code == "invalid_response"


def test_invalid_identity_row_is_disposed_and_read_marked_partial():
    result = read(PaginatedSDK([observation(0), observation(1, id=None)]))
    assert result.status == "partial"
    assert result.invalid_count == 1
    assert result.issues["missing_observation_id"] == 1
    assert result.error_code == "invalid_observation"
    assert len(result.metrics) == 1


def test_unknown_optional_values_retain_observation_and_coverage_counts():
    result = read(PaginatedSDK([observation(usage=None, latency=None, calculatedTotalCost=None)]))
    assert result.complete
    assert result.invalid_count == 0
    assert result.issues["missing_cost"] == 1
    assert result.metrics[0].cost_usd is None


def test_contradictory_measurements_do_not_claim_complete_trust():
    result = read(PaginatedSDK([observation(usage={"input": 10, "output": 20, "total": 0})]))
    assert result.status == "partial"
    assert result.error_code == "inconsistent_measurement"
    assert result.issues["inconsistent_token_total"] == 1
    assert result.metrics[0].total_tokens == 0


@pytest.mark.parametrize("changed,error", [(False, "duplicate_observation"), (True, "conflicting_revision")])
def test_repeated_identity_is_deduplicated_and_partial(changed, error):
    second = observation(0, calculatedTotalCost=0.02) if changed else observation(0)
    result = read(PaginatedSDK([observation(0), second]))
    assert result.status == "partial"
    assert result.duplicate_count == 1
    assert result.error_code == error
    assert len(result.metrics) == 1


def test_read_enforces_fixed_trace_scope_and_excludes_outside_window():
    sdk = PaginatedSDK([observation(0), observation(1)])
    result = read(sdk, trace_id="workflow-0")
    assert result.status == "partial"
    assert result.invalid_count == 1
    assert result.metrics[0].trace_id == "workflow-0"
    assert sdk.calls[0]["trace_id"] == "workflow-0"


def test_changed_page_totals_are_not_claimed_as_a_consistent_traversal():
    class Changing(PaginatedSDK):
        def fetch_observations(self, **kwargs):
            response = super().fetch_observations(**kwargs)
            if kwargs["page"] == 2:
                response.meta.total_items += 1
            return response
    result = read(Changing([observation(index) for index in range(150)]))
    assert result.status == "partial"
    assert result.issues["pagination_changed"] == 1


def test_budget_exhaustion_after_page_cannot_report_complete(monkeypatch):
    clock = iter([0.0, 0.0, 16.0])
    monkeypatch.setattr("guardian.langfuse_client.time.monotonic", lambda: next(clock))
    result = read(PaginatedSDK([observation()]))
    assert result.status == "partial"
    assert result.error_code == "read_timeout"


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 5001}, {"limit": True}, {"timeout_seconds": 0}])
def test_invalid_limits_fail_before_source_call(kwargs):
    sdk = PaginatedSDK([])
    result = read(sdk, **kwargs)
    assert result.status == "failed"
    assert result.error_code == "invalid_query"
    assert sdk.calls == []


def test_invalid_query_time_is_never_replaced_with_now():
    sdk = PaginatedSDK([])
    result = source(sdk).fetch_generations(datetime(2026, 1, 1))
    assert result.status == "failed"
    assert result.error_code == "invalid_window"
    assert sdk.calls == []


def test_actual_sdk2_generated_observations_request_has_explicit_timeouts_and_parses_response():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "data": [observation()],
            "meta": {"page": 1, "limit": 100, "totalItems": 1, "totalPages": 1},
        })

    transport = httpx.Client(transport=httpx.MockTransport(respond))
    sdk = Langfuse(public_key="pk-lf-offline", secret_key="sk-lf-offline", host="https://fixture.invalid", httpx_client=transport, enabled=False)
    try:
        result = read(sdk)
    finally:
        sdk.shutdown()
        transport.close()
    assert result.complete
    assert len(result.metrics) == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/api/public/observations"
    assert request.url.params["type"] == "GENERATION"
    assert request.url.params["fromStartTime"].startswith("2026-01-01T00:00:00")
    assert request.url.params["toStartTime"].startswith("2026-01-02T00:00:00")
    assert all(0 < value <= 5 for value in request.extensions["timeout"].values())


def test_actual_sdk2_upstream_error_is_not_retried_or_leaked(caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={"error": "private-provider-token"})

    transport = httpx.Client(transport=httpx.MockTransport(respond))
    sdk = Langfuse(public_key="pk-lf-offline", secret_key="sk-lf-offline", host="https://fixture.invalid", httpx_client=transport, enabled=False)
    try:
        result = read(sdk)
    finally:
        sdk.shutdown()
        transport.close()
    assert result.status == "failed"
    assert result.error_code == "upstream_error"
    assert len(requests) == 1
    assert "private-provider-token" not in caplog.text + repr(result)


def test_shared_sdk_trace_operations_propagate_request_budget_and_disable_retries():
    calls = []

    def receive(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[])

    sdk = SimpleNamespace(client=SimpleNamespace(trace=SimpleNamespace(list=receive, get=receive)))
    adapter = source(sdk)
    adapter.read_sdk("traces", timeout_seconds=2, limit=8)
    adapter.read_sdk("trace", timeout_seconds=3, trace_id="workflow")
    assert calls[0]["request_options"] == {"timeout_in_seconds": 2, "max_retries": 0}
    assert calls[1]["request_options"] == {"timeout_in_seconds": 3, "max_retries": 0}
    assert calls[1]["trace_id"] == "workflow"


def test_confirmed_sdk_trace_404_remains_distinct_from_unavailable():
    from langfuse.api.core.api_error import ApiError

    def missing(**kwargs):
        raise ApiError(status_code=404, body="private-response-body")

    sdk = SimpleNamespace(client=SimpleNamespace(trace=SimpleNamespace(get=missing)))
    with pytest.raises(SourceReadError) as failure:
        source(sdk).read_sdk("trace", trace_id="missing-workflow")
    assert failure.value.code == "not_found"
    assert str(failure.value) == "not_found"
