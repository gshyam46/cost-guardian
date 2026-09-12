"""Documented v2 wire contracts, with HTTPX MockTransport and no real service."""
import base64
from datetime import datetime, timedelta, timezone
import gzip
import json
import logging

import httpx
import pytest

from guardian import langfuse_v2 as v2

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


def observation(index=0, **changes):
    row = {
        "id": f"observation-{index}", "traceId": f"trace-{index}", "type": "GENERATION",
        "projectId": "source-project", "name": "answer", "model": "test-model",
        "startTime": "2026-01-01T01:00:00Z", "endTime": "2026-01-01T01:00:00.500Z",
        "parentObservationId": None, "level": "DEFAULT", "latency": 0.5,
        "timeToFirstToken": 0.125, "usageDetails": {"input": 12, "output": 8, "total": 20},
        "inputUsage": 12, "outputUsage": 8, "totalUsage": 20,
        "costDetails": {"input": 0.006, "output": 0.004, "total": 0.01},
        "inputCost": 0.006, "outputCost": 0.004, "totalCost": 0.01,
        "traceName": "workflow", "userId": "user", "sessionId": "session", "tags": ["test"],
        "output": '{"answer":"yes","score":1.25}',
    }
    row.update(changes)
    return row


@pytest.fixture
def make_client():
    clients = []

    def make(handler, host="https://langfuse.example.invalid"):
        client = v2.ObservationsV2Client(host, "public-test", "secret-test", transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def payload(rows, cursor=None):
    return {"data": rows, "meta": {} if cursor is None else {"cursor": cursor}}


def read(make_client, response, **kwargs):
    return make_client(lambda _request: httpx.Response(200, json=response)).fetch_generations(START, until=END, **kwargs)


def test_exact_authenticated_path_fields_and_utc_bounds_preserve_host_prefix(make_client, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://ambient-proxy.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.invalid")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload([observation(traceId="trace-specific")]))

    client = make_client(handler, host="https://langfuse.example.invalid/custom/base/")
    offset = timezone(timedelta(hours=5, minutes=30))
    result = client.fetch_generations(START.astimezone(offset), until=END.astimezone(offset), trace_id="trace-specific")
    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == "/custom/base/api/public/v2/observations"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"public-test:secret-test").decode()
    assert request.headers["accept-encoding"] == "identity"
    assert dict(request.url.params) == {
        "fromStartTime": START.isoformat(), "toStartTime": END.isoformat(), "traceId": "trace-specific",
        "fields": v2.FIELDS, "type": "GENERATION", "limit": "100",
    }
    assert set(v2.FIELDS.split(",")) == {"core", "basic", "time", "model", "usage", "metrics", "trace_context", "io"}
    assert set(request.extensions["timeout"]) == {"connect", "read", "write", "pool"}
    assert all(0 < timeout <= 5 for timeout in request.extensions["timeout"].values())
    assert client._http.trust_env is False
    assert client._http.follow_redirects is False
    assert result.complete and result.api_version == "v2"
    metric = result.metrics[0]
    assert (metric.total_tokens, metric.cost_usd, metric.latency_ms, metric.time_to_first_token_ms) == (20, .01, 500, 125)
    assert metric.output_text == '{"answer":"yes","score":1.25}'


def test_wire_decimal_cost_preserves_more_than_binary_float_precision(make_client):
    body = json.dumps(payload([observation(costDetails={"total": .01})])).replace('"total": 0.01', '"total": 0.012345678901234567890123456789')
    result = make_client(lambda _request: httpx.Response(200, content=body)).fetch_generations(START, until=END)
    assert result.complete
    assert result.metrics[0].cost_usd_decimal == "0.012345678901234567890123456789"
    assert result.metrics[0].output_text == '{"answer":"yes","score":1.25}'


def test_empty_detail_maps_cannot_turn_default_aggregate_zeros_into_measurements(make_client):
    result = read(make_client, payload([observation(
        usageDetails={}, inputUsage=0, outputUsage=0, totalUsage=0,
        costDetails={}, inputCost=None, outputCost=None, totalCost=0,
    )]))
    assert result.complete
    metric = result.metrics[0]
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens, metric.cost_usd) == (None, None, None, None)
    assert result.issues["missing_cost"] == result.issues["missing_tokens"] == 1


@pytest.mark.parametrize("total", [0, 12])
def test_partial_detail_map_does_not_accept_synthetic_or_inconsistent_scalar_total(make_client, total):
    result = read(make_client, payload([observation(
        usageDetails={"input": 12}, inputUsage=12, outputUsage=0, totalUsage=total,
        costDetails={"input": .01}, inputCost=.01, outputCost=None, totalCost=total,
    )]))
    metric = result.metrics[0]
    assert metric.input_tokens == 12
    assert metric.output_tokens is None and metric.total_tokens is None and metric.cost_usd is None


def test_explicit_zero_detail_totals_are_measured_even_without_splits(make_client):
    result = read(make_client, payload([observation(usageDetails={"total": 0}, costDetails={"total": 0})]))
    metric = result.metrics[0]
    assert metric.total_tokens == 0 and metric.cost_usd == 0 and metric.cost_usd_decimal == "0"
    assert metric.input_tokens is None and metric.output_tokens is None
    assert "missing_tokens" not in result.issues and "missing_cost" not in result.issues


@pytest.mark.parametrize("costs", [
    {"input": .25, "output": .75, "total": 0},
    {"input": 0, "output": 0, "total": .01},
    {"input": .25, "output": .75, "total": .5},
    {"input": 1e-200, "output": 0, "total": 0},
    {"input": .1, "output": .2, "custom": .3, "total": .3},
])
def test_contradictory_complete_cost_buckets_block_ingestion_and_clear_trusted_cost(make_client, costs):
    result = read(make_client, payload([observation(costDetails=costs)]))
    assert result.status == "partial" and result.error_code == "inconsistent_measurement"
    assert result.issues["inconsistent_cost_total"] == 1
    assert result.metrics[0].cost_usd is None and result.metrics[0].cost_usd_decimal is None
    assert result.issues["missing_cost"] == 1
    assert result.metrics[0].revision_fingerprint == v2._fingerprint(result.metrics[0])
    assert "inconsistent_cost_total" in result.metrics[0].normalization_issues


@pytest.mark.parametrize("costs", [
    {"input": .1, "output": .2, "total": .30000000000000004},
    {"input": .1, "output": .2, "total": .3},
    {"input": 0, "output": 0, "total": 0},
    {"input": .1, "output": .2, "custom": .3, "total": .6000000000000001},
])
def test_cost_consistency_accepts_float_roundoff_and_explicit_all_zero_buckets(make_client, costs):
    result = read(make_client, payload([observation(costDetails=costs)]))
    assert result.complete and "inconsistent_cost_total" not in result.issues
    assert result.metrics[0].cost_usd == costs["total"]


def test_positive_cost_tolerance_is_relative_without_an_absolute_dollar_floor(make_client):
    result = read(make_client, payload([observation(costDetails={"input": 1e-200, "output": 1e-200, "total": 3e-200})]))
    assert result.error_code == "inconsistent_measurement"


@pytest.mark.parametrize("costs", [
    {"input": .25, "total": 1},
    {"input": .25, "output": None, "total": 1},
    {"input": .25, "output": .75, "custom": "invalid", "total": 1},
])
def test_incomplete_cost_buckets_do_not_invent_a_conflicting_complete_sum(make_client, costs):
    result = read(make_client, payload([observation(costDetails=costs)]))
    assert result.complete and "inconsistent_cost_total" not in result.issues
    assert result.metrics[0].cost_usd == 1


def test_valid_top_level_nonzero_measurement_fallback_requires_absent_detail_map(make_client):
    row = observation(inputUsage=3, outputUsage=4, totalUsage=7, totalCost=.3)
    row.pop("usageDetails")
    row.pop("costDetails")
    metric = read(make_client, payload([row])).metrics[0]
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens, metric.cost_usd) == (3, 4, 7, .3)


def test_full_positive_aggregate_split_can_derive_total_when_detail_map_is_absent(make_client):
    row = observation(inputUsage=3, outputUsage=4, totalUsage=None)
    row.pop("usageDetails")
    metric = read(make_client, payload([row])).metrics[0]
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens) == (3, 4, 7)


@pytest.mark.parametrize("details", [[], "malformed", 0, False])
def test_malformed_present_detail_maps_cannot_authorize_positive_aggregate_fallback(make_client, details):
    result = read(make_client, payload([observation(usageDetails=details, costDetails=details)]))
    metric = result.metrics[0]
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens, metric.cost_usd) == (None, None, None, None)
    assert result.issues["invalid_tokens_details"] == result.issues["invalid_cost_details"] == 1


def test_exclusive_cached_reasoning_buckets_reconcile_to_total(make_client):
    result = read(make_client, payload([observation(
        usageDetails={"input": 86, "input_cached_tokens": 17817, "output": 100, "output_reasoning_tokens": 88, "total": 18091},
        inputUsage=17903, outputUsage=188, totalUsage=18091,
    )]))
    assert result.complete
    assert (result.metrics[0].input_tokens, result.metrics[0].output_tokens, result.metrics[0].total_tokens) == (17903, 188, 18091)
    assert "inconsistent_token_total" not in result.issues


@pytest.mark.parametrize("total,expected", [(27, "complete"), (26, "partial")])
def test_custom_exclusive_bucket_only_waives_split_equality_when_exactly_reconciled(make_client, total, expected):
    result = read(make_client, payload([observation(
        usageDetails={"input": 10, "output": 5, "cache_read_input_tokens": 2, "some_other_token_count": 10, "total": total},
    )]))
    assert result.status == expected
    assert result.metrics[0].total_tokens == (total if expected == "complete" else None)
    if expected == "partial":
        assert result.error_code == "inconsistent_measurement"
        assert result.issues["missing_tokens"] == 1
        assert (result.metrics[0].input_tokens, result.metrics[0].output_tokens) == (12, 5)
        assert result.metrics[0].revision_fingerprint == v2._fingerprint(result.metrics[0])


def test_full_exclusive_detail_buckets_can_derive_a_missing_total(make_client):
    result = read(make_client, payload([observation(
        usageDetails={"input": 10, "output": 5, "custom": 2}, totalUsage=0,
        costDetails={"input": .1, "output": .2, "custom": .3}, totalCost=0,
    )]))
    assert result.complete
    assert result.metrics[0].total_tokens == 17
    assert result.metrics[0].cost_usd_decimal == "0.6"


@pytest.mark.parametrize("extra", [None, "bad", (1 << 63) - 1])
def test_invalid_or_overflowing_custom_bucket_cannot_be_silently_dropped_from_total(make_client, extra):
    result = read(make_client, payload([observation(
        usageDetails={"input": 10, "output": 5, "reasoning": extra}, totalUsage=0,
    )]))
    metric = result.metrics[0]
    assert (metric.input_tokens, metric.output_tokens, metric.total_tokens) == (10, 5, None)
    assert result.issues["missing_tokens"] == 1
    assert "missing_tokens" in metric.normalization_issues
    # Fingerprint must describe the returned nullable value, not mapper fallback15.
    assert metric.revision_fingerprint == v2._fingerprint(metric)


@pytest.mark.parametrize("bad", [True, -1, "nan", "Infinity", 1.5, 2 ** 63])
def test_invalid_token_bucket_is_diagnosed_and_never_zero_filled(make_client, bad):
    result = read(make_client, payload([observation(usageDetails={"input": bad}, inputUsage=0, outputUsage=0, totalUsage=0)]))
    assert result.metrics[0].total_tokens is None
    assert result.metrics[0].input_tokens is None
    assert result.issues["invalid_tokens"] == 1


def test_malicious_zero_exponent_cannot_allocate_a_huge_decimal_context(make_client):
    body = json.dumps(payload([observation(usageDetails={"input": 1, "output": 0})])).replace('"output": 0}', '"output": 0e-999999999}')
    result = make_client(lambda _request: httpx.Response(200, content=body)).fetch_generations(START, until=END)
    assert result.complete and result.metrics[0].total_tokens == 1


def test_short_pages_continue_with_opaque_cursor_and_terminal_null_is_complete(make_client):
    cursors = [None, "opaque-one+/=", "opaque-two"]
    seen = []

    def handler(request):
        index = len(seen)
        seen.append(request)
        assert request.url.params.get("cursor") == cursors[index]
        return httpx.Response(200, json={"data": [observation(index)], "meta": {"cursor": cursors[index + 1] if index < 2 else None}})

    result = make_client(handler).fetch_generations(START, until=END)
    assert result.complete and result.pages_fetched == 3
    assert len(result.metrics) == 3
    assert all(request.url.params["limit"] == "100" for request in seen)
    assert all(request.url.params["fromStartTime"] == START.isoformat() and request.url.params["toStartTime"] == END.isoformat() for request in seen)


def test_short_pages_respect_advertised_page_budget_even_when_row_budget_remains(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload([observation(len(seen))], f"next-{len(seen)}"))

    result = make_client(handler).fetch_generations(START, until=END, limit=1000)
    assert result.status == "partial" and result.error_code == "page_limit_reached"
    assert result.records_read == 10 and result.pages_fetched == len(seen) == 10
    assert result.next_cursor == "next-10"


def test_exact_cap_is_complete_only_without_remaining_cursor(make_client):
    rows = [observation(index) for index in range(100)]
    complete = read(make_client, payload(rows), limit=100)
    partial = read(make_client, payload(rows, "private-next-cursor"), limit=100)
    assert complete.complete and complete.next_cursor is None
    assert partial.status == "partial" and partial.error_code == "limit_reached"
    assert partial.next_cursor == "private-next-cursor"
    assert "private-next-cursor" not in repr(partial)


def test_trimmed_page_retains_input_cursor_for_replay_without_skipping_rows(make_client):
    seen = []

    def handler(request):
        page = len(seen)
        seen.append(request)
        return httpx.Response(200, json=payload([observation(page * 100 + item) for item in range(100)], f"after-page-{page + 1}"))

    result = make_client(handler).fetch_generations(START, until=END, limit=250)
    assert result.status == "partial" and result.error_code == "limit_reached"
    assert len(result.metrics) == 250 and result.records_read == 300
    assert result.next_cursor == "after-page-2"
    assert [request.url.params["limit"] for request in seen] == ["100", "100", "100"]


def test_first_read_failure_and_later_page_failure_have_distinct_coverage(make_client, caplog):
    def failure(_request):
        return httpx.Response(503, text="secret-provider-body")

    failed = make_client(failure).fetch_generations(START, until=END)
    assert failed.status == "failed" and failed.records_read == 0
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload([observation()], "private-cursor")) if len(seen) == 1 else failure(request)

    partial = make_client(handler).fetch_generations(START, until=END)
    assert partial.status == "partial" and partial.records_read == 1
    assert partial.error_code == failed.error_code == "upstream_error"
    assert "secret-provider-body" not in repr(partial) + repr(failed) + caplog.text


@pytest.mark.parametrize("status,code", [(400, "invalid_query"), (401, "authentication_failed"), (403, "authentication_failed"), (404, "unsupported_api"), (429, "rate_limited"), (500, "upstream_error"), (302, "upstream_error")])
def test_http_failure_is_safe_and_never_retries_redirects_or_uses_legacy(make_client, status, code):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, text="sensitive body", headers={"Location": "https://untrusted.invalid/capture", "Retry-After": "60"})

    result = make_client(handler).fetch_generations(START, until=END)
    assert result.status == "failed" and result.error_code == code
    assert len(seen) == 1 and seen[0].url.path == "/api/public/v2/observations"
    assert "sensitive" not in repr(result)


@pytest.mark.parametrize("body", [b"not-json", b'{"data":[],"meta":{},"meta":{}}', b'{"data":NaN,"meta":{}}', b'\xff', b'{"data":[],"meta":[]}', b'{"data":[]}', b'[]'])
def test_malformed_wire_response_is_failed_not_complete_empty(make_client, body):
    result = make_client(lambda _request: httpx.Response(200, content=body)).fetch_generations(START, until=END)
    assert result.status == "failed" and result.error_code == "invalid_response"


@pytest.mark.parametrize("cursor", ["", 2, False, {}, [], "white space", "nonascii-\u03bb", "x" * 8193])
def test_malformed_cursor_stops_read_after_valid_rows(make_client, cursor):
    result = read(make_client, {"data": [observation()], "meta": {"cursor": cursor}})
    assert result.status == "partial" and result.error_code == "invalid_response"
    assert result.records_read == 1


def test_empty_page_with_cursor_cannot_make_progress(make_client):
    result = read(make_client, payload([], "next"))
    assert result.status == "failed" and result.error_code == "invalid_response"


def test_repeated_cursor_stops_bounded_traversal(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload([observation(len(seen))], "same-cursor"))

    result = make_client(handler).fetch_generations(START, until=END)
    assert result.status == "partial" and result.error_code == "pagination_cycle"
    assert len(seen) == 2


def test_distinct_trace_span_pairs_are_distinct_but_same_pair_duplicates_are_partial(make_client):
    result = read(make_client, payload([observation(), observation(traceId="another-trace"), observation()]))
    assert len(result.metrics) == 2 and result.duplicate_count == 1
    assert result.status == "partial" and result.error_code == "duplicate_observation"


def test_conflicting_same_identity_is_exposed_and_first_metric_is_not_overwritten(make_client):
    result = read(make_client, payload([observation(), observation(costDetails={"total": 5})]))
    assert len(result.metrics) == 1 and result.metrics[0].cost_usd == .01
    assert result.error_code == "conflicting_revision"


@pytest.mark.parametrize("changes", [{"startTime": "2025-12-31T23:59:59Z"}, {"startTime": END.isoformat()}, {"traceId": "wrong-trace"}, {"type": "SPAN"}, {"type": None}, {"id": None}, {"startTime": None}])
def test_rows_outside_scope_or_missing_identity_cannot_be_complete(make_client, changes):
    row = observation(traceId="expected")
    row.update(changes)
    result = read(make_client, payload([row]), trace_id="expected")
    assert result.status == "partial" and result.invalid_count == 1
    assert not result.metrics and result.error_code == "invalid_observation"


def test_oversized_page_is_partial_and_never_processes_over_requested_budget(make_client):
    result = read(make_client, payload([observation(index) for index in range(101)]))
    assert result.status == "partial" and result.error_code == "invalid_response"
    assert result.records_read == 101 and len(result.metrics) == 100


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": True}, {"limit": 5001}, {"trace_id": " "}, {"timeout_seconds": True}, {"timeout_seconds": float("nan")}, {"timeout_seconds": 0}])
def test_invalid_query_performs_no_http_request(make_client, kwargs):
    def handler(_request):
        pytest.fail("invalid query must not access transport")

    result = make_client(handler).fetch_generations(START, until=END, **kwargs)
    assert result.status == "failed" and result.error_code == "invalid_query"


@pytest.mark.parametrize("since,until", [(START.replace(tzinfo=None), END), (START, START), (END, START), ("bad", END)])
def test_invalid_time_window_performs_no_http_request(make_client, since, until):
    def handler(_request):
        pytest.fail("invalid window must not access transport")

    result = make_client(handler).fetch_generations(since, until=until)
    assert result.status == "failed" and result.error_code == "invalid_window"


class ByteStream(httpx.SyncByteStream):
    def __init__(self, chunks, clock=None):
        self.chunks = chunks
        self.clock = clock
        self.closed = False
        self.read_chunks = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.read_chunks += 1
            if self.clock is not None:
                self.clock[0] += 2
            yield chunk

    def close(self):
        self.closed = True


def test_response_cap_bounds_identity_representation_and_closes_stream(make_client, monkeypatch):
    monkeypatch.setattr(v2, "MAX_RESPONSE_BYTES", 1024)
    body = json.dumps(payload([observation(output="x" * 4096)])).encode()
    stream = ByteStream([body])
    result = make_client(lambda _request: httpx.Response(200, stream=stream)).fetch_generations(START, until=END)
    assert result.status == "failed" and result.error_code == "response_too_large"
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "br", "gzip, identity", "unknown"])
def test_nonidentity_encoding_is_rejected_before_decompression_or_stream_read(make_client, encoding):
    stream = ByteStream([gzip.compress(b" " * 100000)])
    result = make_client(lambda _request: httpx.Response(200, stream=stream, headers={"Content-Encoding": encoding})).fetch_generations(START, until=END)
    assert result.status == "failed" and result.error_code == "invalid_response"
    assert stream.read_chunks == 0 and stream.closed


def test_deadline_is_checked_while_streaming_and_closes_response(make_client, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(v2.time, "monotonic", lambda: clock[0])
    stream = ByteStream([b" " * 65536, b" " * 65536], clock)
    result = make_client(lambda _request: httpx.Response(200, stream=stream)).fetch_generations(START, until=END, timeout_seconds=3)
    assert result.status == "failed" and result.error_code == "read_timeout"
    assert stream.closed


def test_small_trickling_chunks_cannot_defer_deadline_until_a_fixed_buffer_fills(make_client, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(v2.time, "monotonic", lambda: clock[0])
    stream = ByteStream([b" "] * 20, clock)
    result = make_client(lambda _request: httpx.Response(200, stream=stream)).fetch_generations(START, until=END, timeout_seconds=3)
    assert result.error_code == "read_timeout"
    assert stream.read_chunks == 2 and stream.closed


def test_network_timeout_is_safe_and_never_retried(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret upstream details", request=request)

    result = make_client(handler).fetch_generations(START, until=END)
    assert result.error_code == "read_timeout" and result.status == "failed"
    assert len(calls) == 1 and "secret upstream" not in repr(result)


def test_remaining_budget_caps_each_followup_request_timeout(make_client, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(v2.time, "monotonic", lambda: clock[0])
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            clock[0] = 2.0
            return httpx.Response(200, json=payload([observation()], "next"))
        return httpx.Response(200, json=payload([observation(1)]))

    result = make_client(handler).fetch_generations(START, until=END, timeout_seconds=3)
    assert result.complete
    assert seen[0].extensions["timeout"]["read"] == 3
    assert seen[1].extensions["timeout"]["read"] == 1


def test_httpx_info_diagnostics_hide_cursor_host_trace_id_and_preserve_other_requests(make_client, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    seen = []
    cursor = "private-cursor+/="

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload([observation(len(seen), traceId="private-trace")], cursor if len(seen) == 1 else None))

    result = make_client(handler, host="https://private-host.invalid/private-base").fetch_generations(START, until=END, trace_id="private-trace")
    assert result.complete
    assert "HTTP Request: GET /api/public/v2/observations" in caplog.text
    for private in ("private-cursor", "private-host", "private-base", "private-trace", "secret-test", "public-test"):
        assert private not in caplog.text
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as unrelated:
        unrelated.get("https://unrelated.invalid/health")
    assert "https://unrelated.invalid/health" in caplog.text


def test_httpx_diagnostics_cannot_log_provider_reason_phrase_or_protocol(make_client, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    private = "provider-echo-private-cursor"
    result = make_client(lambda _request: httpx.Response(
        200, json=payload([]), extensions={
            "reason_phrase": private.encode(), "http_version": b"private-protocol",
        },
    )).fetch_generations(START, until=END)
    assert result.complete
    assert "HTTP Request: GET /api/public/v2/observations status=200" in caplog.text
    assert private not in caplog.text and "private-protocol" not in caplog.text
