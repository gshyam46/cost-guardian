"""One-page ingestion contracts: durable dispositions without raw quarantine data."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import logging

import httpx
import pytest

from guardian import langfuse_v2 as v2
from guardian.langfuse_client import LangfuseTraceSource

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


def observation(index=0, **changes):
    row = {
        "id": f"observation-{index}", "traceId": f"trace-{index}", "projectId": "project",
        "type": "GENERATION", "name": "answer", "model": "model",
        "startTime": "2026-01-01T01:00:00Z", "endTime": "2026-01-01T01:00:01Z",
        "level": "DEFAULT", "usageDetails": {"input": 3, "output": 2, "total": 5},
        "costDetails": {"input": .003, "output": .002, "total": .005},
    }
    row.update(changes)
    return row


def envelope(rows, cursor=None):
    return {"data": rows, "meta": {} if cursor is None else {"cursor": cursor}}


@pytest.fixture
def make_source():
    sources = []

    def make(handler, **kwargs):
        options = {
            "api_version": "v2", "host": "https://source.invalid/custom/base/",
            "public_key": "public-test", "secret_key": "secret-test",
        }
        options.update(kwargs)
        source = LangfuseTraceSource(transport=httpx.MockTransport(handler), **options)
        sources.append(source)
        return source

    yield make
    for source in sources:
        source.close()


def page(make_source, body, **kwargs):
    return make_source(lambda _request: httpx.Response(200, json=body)).fetch_generation_page(START, END, **kwargs)


def test_valid_page_can_commit_accepted_and_quarantined_rows_without_losing_positions(make_source):
    result = page(make_source, envelope([
        observation(), observation(1, id=None), observation(2, startTime="invalid"),
        observation(3, costDetails={"input": .25, "output": .75, "total": 0}),
        observation(4, usageDetails={}, costDetails={}),
    ], "next-cursor"))
    assert result.status == "ok" and result.committable and result.has_more
    assert result.exhausted is False and result.records_read == 5
    assert [row.ordinal for row in result.rows] == [0, 1, 2, 3, 4]
    assert [row.disposition for row in result.rows] == ["accepted", "quarantined", "quarantined", "quarantined", "accepted"]
    assert result.rows[0].metric.total_tokens == 5
    assert result.rows[1].metric is None and result.rows[1].observation_id is None
    assert result.rows[3].metric is None and "inconsistent_cost_total" in result.rows[3].issues
    assert result.rows[4].metric.total_tokens is None and result.rows[4].metric.cost_usd is None
    assert result.error_code is None
    assert result.api_version == "v2" and result.normalization_version == v2.NORMALIZATION_VERSION
    assert result.issues["missing_observation_id"] == 1


@pytest.mark.parametrize("bad", [None, [], "bad row", 7, False, {"type": "SPAN"}])
def test_each_poison_row_has_a_content_free_durable_disposition(make_source, bad):
    result = page(make_source, envelope([observation(), bad]))
    assert result.committable and result.exhausted and result.records_read == 2
    rejected = result.rows[1]
    assert rejected.disposition == "quarantined" and rejected.metric is None
    assert len(rejected.record_fingerprint) == 64 and rejected.issues
    assert set(asdict(rejected)) == {"ordinal", "disposition", "record_fingerprint", "metric", "observation_id", "trace_id", "source_project_id", "issues"}


def test_duplicate_and_conflicting_rows_are_all_visible_to_the_ledger(make_source):
    result = page(make_source, envelope([
        observation(), observation(), observation(costDetails={"total": .25}),
    ]))
    assert result.committable and len(result.rows) == 3
    assert all(row.disposition == "accepted" for row in result.rows)
    assert result.rows[0].record_fingerprint == result.rows[1].record_fingerprint
    assert result.rows[0].record_fingerprint != result.rows[2].record_fingerprint
    assert result.rows[0].observation_id == result.rows[2].observation_id


def test_one_call_returns_one_full_untrimmed_page_without_following_cursor(make_source):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope([observation(index) for index in range(100)], "next"))

    result = make_source(handler).fetch_generation_page(START, END)
    assert result.committable and result.has_more and len(result.rows) == 100
    assert len(calls) == 1
    assert calls[0].url.path == "/custom/base/api/public/v2/observations"
    assert calls[0].url.params["limit"] == "100"


def test_opaque_cursor_resumes_after_a_fresh_source_instance_with_same_query(make_source):
    requests = []
    cursor = "private-opaque+/="

    def first(request):
        requests.append(request)
        return httpx.Response(200, json=envelope([observation()], cursor))

    def second(request):
        requests.append(request)
        return httpx.Response(200, json=envelope([observation(1)]))

    initial = make_source(first).fetch_generation_page(START, END)
    resumed = make_source(second).fetch_generation_page(
        START, END, cursor=initial.next_cursor, expected_query_fingerprint=initial.query_fingerprint,
    )
    assert resumed.committable and resumed.exhausted and not resumed.has_more
    assert resumed.query_fingerprint == initial.query_fingerprint
    assert resumed.request_cursor == cursor and resumed.next_cursor is None
    assert requests[0].url.params.get("cursor") is None
    assert requests[1].url.params["cursor"] == cursor
    assert dict(requests[0].url.params) == {key: value for key, value in requests[1].url.params.items() if key != "cursor"}


@pytest.mark.parametrize("changes", [
    {"since": START + timedelta(seconds=1)}, {"until": END + timedelta(seconds=1)},
    {"page_size": 50}, {"trace_id": "another-trace"},
])
def test_cursor_query_binding_rejects_changed_bounds_or_filters_before_http(make_source, changes):
    first = page(make_source, envelope([observation()], "next"))

    def fail(_request):
        pytest.fail("mismatched query must not access HTTP")

    kwargs = {"since": START, "until": END, "cursor": "next", "expected_query_fingerprint": first.query_fingerprint}
    kwargs.update(changes)
    result = make_source(fail).fetch_generation_page(**kwargs)
    assert result.status == "failed" and result.error_code == "query_mismatch"
    assert not result.rows and result.exhausted is None and not result.committable


@pytest.mark.parametrize("changes", [{"host": "https://source.invalid/other"}, {"public_key": "other-project-key"}])
def test_cursor_query_binding_rejects_a_different_endpoint_or_credential_scope(make_source, changes):
    first = page(make_source, envelope([observation()], "next"))

    def fail(_request):
        pytest.fail("mismatched source scope must not access HTTP")

    result = make_source(fail, **changes).fetch_generation_page(START, END, cursor="next", expected_query_fingerprint=first.query_fingerprint)
    assert result.error_code == "query_mismatch" and not result.committable


def test_secret_rotation_and_equivalent_utc_offsets_do_not_change_query_fingerprint(make_source):
    first = page(make_source, envelope([observation()], "next"))
    offset = timezone(timedelta(hours=5, minutes=30))
    resumed = make_source(lambda _request: httpx.Response(200, json=envelope([])), secret_key="rotated-secret").fetch_generation_page(
        START.astimezone(offset), END.astimezone(offset), cursor="next", expected_query_fingerprint=first.query_fingerprint,
    )
    assert resumed.committable and resumed.query_fingerprint == first.query_fingerprint


def test_resumption_requires_saved_query_binding(make_source):
    def fail(_request):
        pytest.fail("unbound cursor must not access HTTP")

    result = make_source(fail).fetch_generation_page(START, END, cursor="cursor")
    assert result.error_code == "query_mismatch" and not result.committable


def test_normalization_contract_change_invalidates_a_saved_traversal(make_source, monkeypatch):
    initial = page(make_source, envelope([observation()], "next"))
    monkeypatch.setattr(v2, "NORMALIZATION_VERSION", "langfuse-v2-future")

    def fail(_request):
        pytest.fail("changed normalization must require traversal reconciliation")

    result = make_source(fail).fetch_generation_page(START, END, cursor="next", expected_query_fingerprint=initial.query_fingerprint)
    assert result.error_code == "query_mismatch"


@pytest.mark.parametrize("changes,code", [
    ({"since": START.replace(tzinfo=None)}, "invalid_window"),
    ({"until": None}, "invalid_window"), ({"until": START}, "invalid_window"),
    ({"page_size": 0}, "invalid_query"), ({"page_size": True}, "invalid_query"),
    ({"page_size": 101}, "invalid_query"), ({"trace_id": " "}, "invalid_query"),
    ({"cursor": ""}, "invalid_query"), ({"cursor": "bad cursor"}, "invalid_query"),
    ({"timeout_seconds": 0}, "invalid_query"), ({"timeout_seconds": float("inf")}, "invalid_query"),
])
def test_invalid_page_request_performs_no_http(make_source, changes, code):
    def fail(_request):
        pytest.fail("invalid page request must not access HTTP")

    kwargs = {"since": START, "until": END}
    kwargs.update(changes)
    result = make_source(fail).fetch_generation_page(**kwargs)
    assert result.error_code == code and not result.committable and not result.rows


@pytest.mark.parametrize("body", [
    {"data": [observation()]}, {"data": [observation()], "meta": []},
    {"data": [observation()], "meta": {"cursor": ""}},
    {"data": [], "meta": {"cursor": "next"}},
    {"data": [observation()], "meta": {"cursor": {"invalid": "cursor"}}},
    {"data": [observation(index) for index in range(101)], "meta": {}},
    {"data": {}, "meta": {}}, [],
])
def test_malformed_envelope_never_returns_committable_rows(make_source, body):
    result = page(make_source, body)
    assert result.status == "failed" and result.error_code == "invalid_response"
    assert result.rows == [] and result.exhausted is None and result.next_cursor is None
    assert not result.committable


def test_same_cursor_response_is_a_failed_page_before_any_dispositions_commit(make_source):
    initial = page(make_source, envelope([observation()], "same"))
    result = make_source(lambda _request: httpx.Response(200, json=envelope([observation(1)], "same"))).fetch_generation_page(
        START, END, cursor="same", expected_query_fingerprint=initial.query_fingerprint,
    )
    assert result.error_code == "pagination_cycle" and not result.rows and not result.committable


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (404, "unsupported_api"), (429, "rate_limited"), (503, "upstream_error")])
def test_read_failure_retains_input_cursor_without_any_committable_rows(make_source, status, code):
    initial = page(make_source, envelope([observation()], "private-next"))
    result = make_source(lambda _request: httpx.Response(status, text="private-provider-body")).fetch_generation_page(
        START, END, cursor="private-next", expected_query_fingerprint=initial.query_fingerprint,
    )
    assert result.status == "failed" and result.error_code == code
    assert result.request_cursor == "private-next" and result.next_cursor is None
    assert not result.rows and not result.committable
    assert "private" not in repr(result)


def test_deadline_during_normalization_discards_the_whole_page(make_source, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(v2.time, "monotonic", lambda: clock[0])
    original = v2._normalize_v2_row

    def slow(raw):
        clock[0] += 3
        return original(raw)

    monkeypatch.setattr(v2, "_normalize_v2_row", slow)
    result = page(make_source, envelope([observation(), observation(1)]), timeout_seconds=5)
    assert result.error_code == "read_timeout" and not result.rows and not result.committable


@pytest.mark.parametrize("changes", [
    {"startTime": END.isoformat()}, {"traceId": "outside-trace"},
    {"id": "x" * 513}, {"traceId": "x" * 513}, {"projectId": None}, {"projectId": "x" * 513},
])
def test_scope_or_identity_failure_is_quarantined_with_valid_page_progress(make_source, changes):
    row = observation(traceId="expected")
    row.update(changes)
    result = page(make_source, envelope([row]), trace_id="expected")
    assert result.committable and result.exhausted
    assert result.rows[0].disposition == "quarantined" and result.rows[0].metric is None


def test_content_context_and_updated_at_noise_do_not_change_scalar_fingerprint(make_source):
    first = observation(output="first private output", statusMessage="first private status", updatedAt="2026-01-01T02:00:00Z")
    second = observation(
        output="different private output", input="private request", statusMessage="different private status",
        updatedAt="2026-01-02T00:00:00Z", metadata={"private": "metadata"},
        userId="user", sessionId="session", tags=["tag"], traceName="context-name",
    )
    rows = page(make_source, envelope([first, second])).rows
    assert rows[0].record_fingerprint == rows[1].record_fingerprint
    assert rows[0].metric.output_text != rows[1].metric.output_text  # transient PII evaluation remains possible
    assert "private" not in repr(rows)


@pytest.mark.parametrize("changes", [
    {"name": "changed-agent"}, {"model": "changed-model"}, {"level": "ERROR"},
    {"endTime": "2026-01-01T01:00:02Z"}, {"costDetails": {"total": .006}},
    {"usageDetails": {"total": 6}}, {"usageDetails": {"total": 5, "custom": "invalid"}},
])
def test_accounting_attribution_timing_status_and_issue_changes_affect_fingerprint(make_source, changes):
    rows = page(make_source, envelope([observation(), observation(**changes)])).rows
    assert rows[0].record_fingerprint != rows[1].record_fingerprint


def test_quarantine_and_diagnostics_never_retain_raw_content_or_cursor(make_source, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    marker = "sensitive-content-marker"
    initial = page(make_source, envelope([observation()], "private-cursor"))
    bad = observation(id=None, output=marker, input=marker, statusMessage=marker, metadata={"key": marker})
    result = make_source(lambda _request: httpx.Response(200, json=envelope([bad]))).fetch_generation_page(
        START, END, cursor=initial.next_cursor, expected_query_fingerprint=initial.query_fingerprint,
    )
    row = result.rows[0]
    assert row.disposition == "quarantined" and row.metric is None
    assert marker not in json.dumps(asdict(row)) + repr(result) + caplog.text
    assert "private-cursor" not in repr(result) + caplog.text
    other = observation(id=None, output="different", input="different", statusMessage="different", metadata={"other": "changed"})
    assert page(make_source, envelope([other])).rows[0].record_fingerprint == row.record_fingerprint


def test_quarantine_fingerprint_still_distinguishes_valid_scalar_evidence(make_source):
    result = page(make_source, envelope([
        observation(id=None, costDetails={"total": .1}),
        observation(id=None, costDetails={"total": .2}),
    ]))
    assert all(row.disposition == "quarantined" for row in result.rows)
    assert result.rows[0].record_fingerprint != result.rows[1].record_fingerprint


def test_legacy_page_api_is_explicitly_unsupported_without_touching_sdk():
    source = LangfuseTraceSource.__new__(LangfuseTraceSource)
    source._api_version = "v1"
    result = source.fetch_generation_page(START, END)
    assert result.error_code == "unsupported_resumable_source" and result.api_version == "v1"
    assert not result.rows and not result.committable


def test_unconfigured_v2_page_is_failed_without_network(make_source):
    def fail(_request):
        pytest.fail("unconfigured source must not access HTTP")

    result = make_source(fail, public_key="", secret_key="").fetch_generation_page(START, END)
    assert result.error_code == "not_configured" and result.api_version == "v2"
    assert not result.committable
