"""Live read contracts: real shared adapter, fake SDK boundaries, no external I/O."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import threading

import pytest

from guardian.langfuse_client import LangfuseTraceSource
from guardian.models import SourceReadResult
from guardian.normalization import normalize_observation
from guardian.traces import LiveReadError, LiveTraceReader, _TTLCache, _observation_to_call

START = datetime.now(timezone.utc) - timedelta(minutes=5)


def observation(index=0, **overrides):
    return {
        "id": f"observation-{index}", "trace_id": "trace-1", "type": "GENERATION",
        "name": "rag-answer", "model": "test-model",
        "start_time": START + timedelta(milliseconds=index),
        "end_time": START + timedelta(seconds=1, milliseconds=index),
        "calculated_total_cost": 2.0, "usage": {"input": 12, "output": 8, "total": 20},
        "level": "DEFAULT", **overrides,
    }


class SDK:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.requests = []
        self.metadata_requests = []
        self.failure_page = None
        self.client = SimpleNamespace(observations=self, trace=self)

    def get_many(self, **kwargs):
        self.requests.append(kwargs)
        if self.failure_page == kwargs["page"]:
            raise TimeoutError("synthetic timeout")
        rows = [row for row in self.rows
                if not kwargs.get("trace_id") or row.get("trace_id") == kwargs["trace_id"]]
        size, page = kwargs["limit"], kwargs["page"]
        return SimpleNamespace(
            data=rows[(page - 1) * size:page * size],
            meta=SimpleNamespace(page=page, limit=size, total_items=len(rows),
                                 total_pages=(len(rows) + size - 1) // size),
        )

    def list(self, **kwargs):
        self.metadata_requests.append(("list", kwargs))
        raise AssertionError("Legacy trace-list endpoint must not be called")

    def get(self, **kwargs):
        self.metadata_requests.append(("get", kwargs))
        raise AssertionError("Legacy trace-get endpoint must not be called")


def reader(rows=(), ttl=20):
    sdk = SDK(rows)
    source = LangfuseTraceSource.__new__(LangfuseTraceSource)
    source._client = sdk
    source._api_version = "v1"
    return LiveTraceReader(source, ttl_seconds=ttl), sdk


def test_full_250_row_window_is_aggregated_before_feed_limit():
    live, sdk = reader([observation(i) for i in range(250)])
    body = live.snapshot(call_limit=60)
    assert body["coverage"]["status"] == "complete"
    assert body["coverage"]["observed_count"] == 250
    assert body["stats"]["call_count"] == 250
    assert body["stats"]["total_cost_usd"] == 500
    assert body["stats"]["total_tokens"] == 5000
    assert len(body["calls"]) == 60
    assert body["feed"] == {"returned": 60, "limit": 60, "limited": True}
    assert [request["page"] for request in sdk.requests] == [1, 2, 3]
    assert all(request["limit"] == 100 for request in sdk.requests)
    assert sdk.metadata_requests == []
    assert body["runs"][0]["name"] == "Trace trace-1"
    assert body["runs"][0]["call_count"] == 250


def test_langfuse_parent_references_survive_live_and_run_views_without_inventing_calls():
    live, sdk = reader([
        observation(0, parent_observation_id="framework-parent"),
        observation(1, parent_observation_id="observation-0"),
        observation(2),
    ])
    expected = {"observation-0": "framework-parent", "observation-1": "observation-0", "observation-2": None}
    snapshot = live.snapshot()
    assert {call["id"]: call["parent_observation_id"] for call in snapshot["calls"]} == expected
    assert snapshot["stats"]["call_count"] == 3
    run = live.run_detail("trace-1")
    assert {call["id"]: call["parent_observation_id"] for call in run["calls"]} == expected
    assert run["call_count"] == 3
    assert run["workflow_status"] == "unknown" and run["latency_ms"] is None
    assert sdk.metadata_requests == []


def test_1000_row_budget_is_explicit_partial_coverage_not_a_complete_total():
    live, sdk = reader([observation(i) for i in range(1200)])
    body = live.snapshot()
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["truncated"] is True
    assert body["coverage"]["reason"] == "limit_reached"
    assert body["coverage"]["max_records"] == 1000
    assert body["coverage"]["max_pages"] == 10
    assert len(sdk.requests) == 10
    assert body["stats"]["call_count"] == 1000


def test_known_zero_is_distinct_from_missing_cost_tokens_and_duration():
    live, _ = reader([
        observation(0, calculated_total_cost=0, usage={"input": 0, "output": 0}, latency=0),
        observation(1, calculated_total_cost=None, usage=None, end_time=None),
    ])
    stats = live.snapshot()["stats"]
    assert stats["total_cost_usd"] is None
    assert stats["known_cost_usd"] == 0
    assert (stats["cost_known_count"], stats["cost_unknown_count"]) == (1, 1)
    assert stats["total_tokens"] is None
    assert (stats["tokens_known_count"], stats["tokens_unknown_count"]) == (1, 1)
    assert stats["avg_latency_ms"] == 0
    assert stats["latency_known_count"] == 1


def test_rejected_observations_are_visible_even_when_no_valid_rows_remain():
    live, _ = reader([observation(id=None)])
    body = live.snapshot()
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["invalid_count"] == 1
    assert body["stats"]["call_count"] == 0


def test_later_page_failure_exposes_partial_rows_and_reason():
    live, sdk = reader([observation(i) for i in range(250)])
    sdk.failure_page = 2
    body = live.snapshot()
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["reason"] == "read_timeout"
    assert body["stats"]["call_count"] == 100


def test_cold_source_failure_has_no_synthetic_zero_totals():
    live, sdk = reader()
    sdk.failure_page = 1
    body = live.snapshot()
    assert body["stats"] is None
    assert body["coverage"]["status"] == "failed"
    assert body["coverage"]["reason"] == "read_timeout"
    assert body["degraded"] is True


def test_failed_refresh_preserves_values_and_original_time_until_stale_expiry(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr("guardian.traces.time.time", lambda: clock["now"])
    monkeypatch.setattr("guardian.traces.time.monotonic", lambda: clock["now"])
    live, sdk = reader([observation()], ttl=1)
    first = live.snapshot()
    clock["now"] = 102
    sdk.failure_page = 1
    cached = live.snapshot()
    assert cached["stale"] is True
    assert cached["stats"] == first["stats"]
    assert cached["fetched_at"] == first["fetched_at"]
    clock["now"] = 401
    expired = live.snapshot()
    assert expired["degraded"] is True
    assert expired["stats"] is None


def test_wall_clock_rollback_cannot_extend_cache_health_or_stale_retention(monkeypatch):
    clock = {"wall": 1_700_000_000.0, "elapsed": 100.0}
    monkeypatch.setattr("guardian.traces.time.time", lambda: clock["wall"])
    monkeypatch.setattr("guardian.traces.time.monotonic", lambda: clock["elapsed"])
    cache = _TTLCache(ttl_seconds=10, max_stale_seconds=30)
    original = cache.get_or_fetch("window", lambda: {"source": "original"})
    attempts = []

    def unavailable():
        attempts.append(True)
        raise LiveReadError("source_unavailable")

    # The clock moves back an hour while eleven real seconds elapse. Refresh must
    # happen and fail; a negative wall-clock age must not turn this into a fresh hit.
    clock.update(wall=1_699_996_400.0, elapsed=111.0)
    stale = cache.get_or_fetch("window", unavailable)
    assert stale[0] == original[0]
    assert stale[1] is True
    assert stale[2] == original[2] == 1_700_000_000.0
    assert len(attempts) == 1

    # Thirty-one real seconds have elapsed, despite another wall-clock rollback.
    # Expired source evidence cannot be served, and its original UTC stamp was
    # never replaced by the rollback clock value.
    clock.update(wall=1_699_992_800.0, elapsed=131.0)
    with pytest.raises(LiveReadError):
        cache.get_or_fetch("window", unavailable)
    assert len(attempts) == 2
    assert "window" not in cache._entries


def test_cache_entry_expiring_during_failed_refresh_is_not_retained(monkeypatch):
    clock = {"elapsed": 0.0}
    monkeypatch.setattr("guardian.traces.time.monotonic", lambda: clock["elapsed"])
    cache = _TTLCache(ttl_seconds=1, max_stale_seconds=10)
    cache.get_or_fetch("window", lambda: "data")
    clock["elapsed"] = 2.0

    def slow_failure():
        clock["elapsed"] = 11.0
        raise LiveReadError("source_unavailable")

    with pytest.raises(LiveReadError):
        cache.get_or_fetch("window", slow_failure)
    assert "window" not in cache._entries


def test_cache_entry_limit_evicts_least_recently_used_value():
    cache = _TTLCache(max_entries=2)
    cache.get_or_fetch("a", lambda: "a")
    cache.get_or_fetch("b", lambda: "b")
    cache.get_or_fetch("a", lambda: "unexpected")
    cache.get_or_fetch("c", lambda: "c")
    assert list(cache._entries) == ["a", "c"]


def test_concurrent_cache_misses_share_one_fill():
    cache = _TTLCache()
    entered, release = threading.Event(), threading.Event()
    fetched = []

    def fetch():
        fetched.append(True)
        entered.set()
        assert release.wait(timeout=2)
        return "data"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_fetch, "same-key", fetch)
        assert entered.wait(timeout=2)
        second = pool.submit(cache.get_or_fetch, "same-key", fetch)
        release.set()
        assert first.result(timeout=2)[0] == second.result(timeout=2)[0] == "data"
    assert len(fetched) == 1


def test_run_detail_uses_shared_generation_read_and_does_not_infer_workflow_success():
    live, sdk = reader([observation(i) for i in range(250)])
    body = live.run_detail("trace-1")
    assert body["call_count"] == 250
    assert body["cost_usd"] == 500
    assert body["workflow_status"] == "unknown"
    assert body["status"] == "unknown"
    assert body["coverage"]["scope"] == "trace_generations"
    assert all(request["trace_id"] == "trace-1" for request in sdk.requests)
    assert sdk.metadata_requests == []
    assert body["window_hours"] == 168
    assert body["observation_state"] == "observed"
    assert body["latency_ms"] is None
    assert body["started_at"] == START.isoformat()
    bounds = body["coverage"]
    assert datetime.fromisoformat(bounds["window_end"]) - datetime.fromisoformat(bounds["window_start"]) == timedelta(hours=168)
    assert len({request["from_start_time"] for request in sdk.requests}) == 1
    assert len({request["to_start_time"] for request in sdk.requests}) == 1


def test_run_not_observed_and_source_unavailable_are_distinct():
    live, sdk = reader([observation(trace_id="other-trace")])
    body = live.run_detail("unseen-trace")
    assert body["observation_state"] == "not_observed"
    assert body["coverage"]["status"] == "complete"
    assert body["calls"] == []
    for field in ("cost_usd", "known_cost_usd", "total_tokens", "known_total_tokens", "latency_ms"):
        assert body[field] is None
    sdk.failure_page = 1
    with pytest.raises(LiveReadError):
        live.run_detail("unavailable")


def test_rejected_only_run_is_undetermined_not_absent_or_free():
    live, _ = reader([observation(id=None)])
    body = live.run_detail("trace-1")
    assert body["observation_state"] == "undetermined"
    assert body["coverage"]["status"] == "partial"
    assert body["coverage"]["invalid_count"] == 1
    assert body["cost_usd"] is None


def test_run_window_bounds_are_validated_and_cached_separately():
    live, sdk = reader([observation()])
    for hours in (0, 169, True, 1.5):
        with pytest.raises(ValueError):
            live.run_detail("trace-1", hours)
    first = live.run_detail("trace-1", 1)
    second = live.run_detail("trace-1", 168)
    assert (first["window_hours"], second["window_hours"]) == (1, 168)
    assert len(sdk.requests) == 2


def test_run_cache_preserves_staleness_on_source_failure(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr("guardian.traces.time.time", lambda: clock["now"])
    monkeypatch.setattr("guardian.traces.time.monotonic", lambda: clock["now"])
    live, sdk = reader([observation()], ttl=1)
    first = live.run_detail("trace-1")
    clock["now"] = 102
    sdk.failure_page = 1
    stale = live.run_detail("trace-1")
    assert stale["stale"] is True
    assert stale["cost_usd"] == first["cost_usd"]
    assert stale["fetched_at"] == first["fetched_at"]


def test_complete_empty_refresh_replaces_previous_run_without_claiming_deletion(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr("guardian.traces.time.monotonic", lambda: clock["now"])
    live, sdk = reader([observation()], ttl=1)
    assert live.run_detail("trace-1")["cost_usd"] == 2
    clock["now"] = 102
    sdk.rows = []
    body = live.run_detail("trace-1")
    assert body["observation_state"] == "not_observed"
    assert body["stale"] is False
    assert body["cost_usd"] is None
    assert body["calls"] == []


def test_live_call_uses_shared_normalizer_for_usage_fallback_and_utc():
    call = _observation_to_call(observation(usageDetails={}, start_time="2026-01-01T05:30:00+05:30"))
    assert (call["input_tokens"], call["output_tokens"], call["total_tokens"]) == (12, 8, 20)
    assert call["started_at"] == "2026-01-01T00:00:00+00:00"


def test_large_finite_costs_cannot_create_non_json_aggregate_infinity():
    live, _ = reader([observation(i, calculated_total_cost="1e308", latency=1e305) for i in range(2)])
    body = live.snapshot()
    assert body["stats"]["total_cost_usd"] is None
    assert body["stats"]["known_cost_usd"] is None
    assert "cost_total_out_of_range" in body["stats"]["aggregate_issues"]
    assert body["stats"]["avg_latency_ms"] == pytest.approx(1e308)
    json.dumps(body, allow_nan=False)


def test_token_aggregate_outside_supported_range_is_explicit():
    live, _ = reader([observation(i, usage={"total": (1 << 63) - 1}) for i in range(2)])
    stats = live.snapshot()["stats"]
    assert stats["total_tokens"] is None
    assert stats["known_total_tokens"] is None
    assert "tokens_total_out_of_range" in stats["aggregate_issues"]


def test_child_durations_never_become_reported_workflow_duration():
    live, _ = reader([observation(0, latency=1e305), observation(1, latency=1e305)])
    body = live.run_detail("trace-1")
    assert body["latency_ms"] is None
    json.dumps(body, allow_nan=False)


def test_verified_trace_context_is_normalized_without_legacy_enrichment():
    live, sdk = reader([observation(traceName="RAG workflow", userId="user-1", sessionId="session-1",
                                     tags=["rag", "rag", "prod", 1, None, " "])])
    body = live.run_detail("trace-1")
    assert (body["name"], body["user_id"], body["session_id"], body["tags"]) == (
        "RAG workflow", "user-1", "session-1", ["rag", "prod"])
    assert body["metadata_basis"] == "observations"
    assert sdk.metadata_requests == []


def test_invalid_or_conflicting_context_does_not_invent_workflow_attribution():
    normalized = normalize_observation(observation(traceName={"name": "not-a-string"}, userId=1,
        sessionId=["not-a-string"], tags="not-a-list")).metric
    assert (normalized.trace_name, normalized.user_id, normalized.session_id, normalized.trace_tags) == (None, None, None, ())
    live, _ = reader([observation(0, traceName="First", userId="user-1"),
                       observation(1, traceName="Second", userId="user-2")])
    body = live.run_detail("trace-1")
    assert body["name"] == "Trace trace-1"
    assert body["user_id"] is None
    assert set(body["trace_context_issues"]) == {"conflicting_trace_name", "conflicting_user_id"}


@pytest.mark.parametrize("reason", ["limit_reached", "page_limit_reached"])
def test_live_coverage_reports_either_budget_without_exposing_opaque_source_cursor(reason):
    metric = normalize_observation(observation()).metric
    result = SourceReadResult([metric], "partial", window_start=START, window_end=START + timedelta(hours=1),
                              pages_fetched=1, records_read=1, error_code=reason)
    result.next_cursor = "synthetic-sensitive-cursor"
    source = SimpleNamespace(available=True, fetch_generations=lambda *args, **kwargs: result,
                             trace_url=lambda trace_id: None)
    for body in (LiveTraceReader(source).snapshot(), LiveTraceReader(source).run_detail("trace-1")):
        assert body["coverage"]["has_more"] is True
        assert body["coverage"]["truncated"] is True
        assert "synthetic-sensitive-cursor" not in json.dumps(body)
        assert "next_cursor" not in body["coverage"]


def test_cached_call_content_is_limited_to_explicit_previews():
    live, _ = reader([observation(status_message="x" * 1000, output="y" * 1000)])
    body = live.snapshot()
    call = body["calls"][0]
    assert len(call["status_message"]) == 400
    assert len(call["output_preview"]) == 400
    assert call["status_message_truncated"] is True
    assert call["output_truncated"] is True
