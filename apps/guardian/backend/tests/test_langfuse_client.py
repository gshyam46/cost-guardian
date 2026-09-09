"""Unit tests for guardian/langfuse_client.py's field-extraction logic.

This is the one file in guardian/ that has never been exercised against a real
Langfuse API response (see docs/PROGRESS.md blockers). These tests can't cover that --
only a live run can -- but they do cover the thing that's actually within reach right
now: given the field shapes Langfuse's docs say a GENERATION observation has, does the
extraction logic produce the right TraceMetric, and does it fail safely (skip, not
crash) on missing/malformed data. Both dict-shaped and attribute-object-shaped inputs
are tested because the code was written defensively for either, not knowing in advance
which the installed SDK version returns.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from guardian.langfuse_client import (
    LangfuseTraceSource,
    _extract_cost,
    _extract_latency_ms,
    _extract_tokens,
    _get,
    _observation_to_trace_metric,
    _stringify,
)


# --- _get -------------------------------------------------------------------

def test_get_reads_attribute():
    obj = SimpleNamespace(trace_id="abc")
    assert _get(obj, "trace_id") == "abc"


def test_get_reads_dict_key():
    obj = {"trace_id": "abc"}
    assert _get(obj, "trace_id") == "abc"


def test_get_falls_back_through_alternate_names():
    obj = {"traceId": "abc"}  # camelCase, as some Langfuse SDK versions return
    assert _get(obj, "trace_id", "traceId") == "abc"


def test_get_returns_default_when_absent():
    assert _get({}, "missing", default="fallback") == "fallback"


def test_get_skips_none_values_and_keeps_looking():
    obj = {"trace_id": None, "traceId": "real-id"}
    assert _get(obj, "trace_id", "traceId") == "real-id"


# --- _extract_tokens ----------------------------------------------------------

def test_extract_tokens_from_usage_total():
    obs = {"usage": {"total": 150}}
    assert _extract_tokens(obs) == 150


def test_extract_tokens_from_usage_object_attribute():
    obs = SimpleNamespace(usage=SimpleNamespace(total=200))
    assert _extract_tokens(obs) == 200


def test_extract_tokens_falls_back_to_prompt_plus_completion():
    obs = {"prompt_tokens": 100, "completion_tokens": 50}
    assert _extract_tokens(obs) == 150


def test_extract_tokens_defaults_to_zero_when_absent():
    assert _extract_tokens({}) == 0


# --- _extract_cost --------------------------------------------------------

def test_extract_cost_from_calculated_total_cost():
    assert _extract_cost({"calculated_total_cost": 0.0042}) == 0.0042


def test_extract_cost_from_cost_details_total():
    obs = {"cost_details": {"total": 0.01}}
    assert _extract_cost(obs) == 0.01


def test_extract_cost_defaults_to_zero_when_absent():
    assert _extract_cost({}) == 0.0


# --- _extract_latency_ms ----------------------------------------------------

def test_extract_latency_from_seconds_field():
    # Langfuse reports `latency` in seconds.
    assert _extract_latency_ms({"latency": 1.5}) == 1500.0


def test_extract_latency_from_start_end_time_when_no_latency_field():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 12, 0, 2, tzinfo=timezone.utc)
    obs = {"start_time": start, "end_time": end}
    assert _extract_latency_ms(obs) == 2000.0


def test_extract_latency_defaults_to_zero_when_absent():
    assert _extract_latency_ms({}) == 0.0


# --- _stringify --------------------------------------------------------------

def test_stringify_passes_through_plain_string():
    assert _stringify("hello") == "hello"


def test_stringify_json_encodes_dict_output():
    assert _stringify({"answer": "42"}) == '{"answer": "42"}'


def test_stringify_none_stays_none():
    assert _stringify(None) is None


# --- _observation_to_trace_metric --------------------------------------------

def _base_observation(**overrides):
    data = {
        "trace_id": "trace-1",
        "name": "profile_analyst",
        "model": "groq/llama-3.3-70b-versatile",
        "start_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "usage": {"total": 500},
        "calculated_total_cost": 0.002,
        "latency": 0.8,
        "level": "DEFAULT",
        "output": "The founder shows strong technical execution skills.",
    }
    data.update(overrides)
    return data


def test_observation_to_trace_metric_maps_all_fields():
    metric = _observation_to_trace_metric(_base_observation())

    assert metric is not None
    assert metric.trace_id == "trace-1"
    assert metric.agent_name == "profile_analyst"
    assert metric.model == "groq/llama-3.3-70b-versatile"
    assert metric.total_tokens == 500
    assert metric.cost_usd == 0.002
    assert metric.latency_ms == 800.0
    assert metric.status == "success"
    assert "technical execution" in metric.output_text


def test_observation_to_trace_metric_maps_error_level_to_error_status():
    metric = _observation_to_trace_metric(_base_observation(level="ERROR"))
    assert metric.status == "error"


def test_observation_to_trace_metric_returns_none_without_trace_id():
    metric = _observation_to_trace_metric({"name": "profile_analyst"})
    assert metric is None


def test_observation_to_trace_metric_survives_completely_malformed_input():
    """A malformed observation is skipped, not a crash that takes down the worker."""
    metric = _observation_to_trace_metric(object())
    assert metric is None


def test_observation_to_trace_metric_works_with_attribute_style_object():
    obs = SimpleNamespace(
        trace_id="trace-2",
        name="market_hunter",
        model="groq/llama-3.3-70b-versatile",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        usage=SimpleNamespace(total=300),
        calculated_total_cost=0.001,
        latency=0.5,
        level="DEFAULT",
        output="Candidate niches identified.",
    )
    metric = _observation_to_trace_metric(obs)

    assert metric is not None
    assert metric.trace_id == "trace-2"
    assert metric.agent_name == "market_hunter"
    assert metric.total_tokens == 300


# --- LangfuseTraceSource without credentials --------------------------------

def test_trace_source_unavailable_without_credentials(monkeypatch):
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_SECRET_KEY", "")

    source = LangfuseTraceSource()

    assert source.available is False
    assert source.fetch_recent_generations(since=datetime.now(timezone.utc)) == []


# --- trace_url ----------------------------------------------------------------
# Regression tests for a real bug found against the live API: this used to call the
# SDK's get_trace_url(trace_id=...), but langfuse 2.x's get_trace_url() takes no
# arguments and only describes the SDK's *current* trace context -- so every deep
# link came back None. It's now built directly from the host + trace id.

def test_trace_url_is_built_from_host_and_trace_id(monkeypatch):
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_HOST", "https://cloud.langfuse.com")
    source = LangfuseTraceSource()

    assert source.trace_url("abc-123") == "https://cloud.langfuse.com/trace/abc-123"


def test_trace_url_does_not_require_credentials(monkeypatch):
    """Building a URL is string work -- it must not depend on an authenticated client."""
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_HOST", "https://cloud.langfuse.com")

    source = LangfuseTraceSource()

    assert source.available is False
    assert source.trace_url("abc-123") == "https://cloud.langfuse.com/trace/abc-123"


def test_trace_url_tolerates_trailing_slash_on_host(monkeypatch):
    monkeypatch.setattr("guardian.langfuse_client.LANGFUSE_HOST", "https://cloud.langfuse.com/")
    source = LangfuseTraceSource()

    assert source.trace_url("abc-123") == "https://cloud.langfuse.com/trace/abc-123"


def test_trace_url_returns_none_for_empty_trace_id():
    assert LangfuseTraceSource().trace_url("") is None


# --- fetch_recent_generations SDK path ----------------------------------------
# Regression test for the other live-API bug: the code called
# `client.api.observations.get_many(...)` (the v3 SDK path), which raises
# AttributeError on langfuse 2.x. The correct call is `client.fetch_observations()`.

class _FakeObservationsResponse:
    def __init__(self, data):
        self.data = data


class _FakeLangfuseClient:
    """Mimics langfuse 2.x: has fetch_observations(), deliberately has no `.api`.

    Honours the requested page size like the real API does, so pagination tests
    exercise realistic behaviour.
    """

    def __init__(self, observations):
        self._observations = observations
        self.calls = []

    def fetch_observations(self, **kwargs):
        self.calls.append(kwargs)
        page_size = kwargs.get("limit", len(self._observations))
        return _FakeObservationsResponse(self._observations[:page_size])


def test_fetch_recent_generations_uses_fetch_observations_api():
    source = LangfuseTraceSource()
    fake = _FakeLangfuseClient([_base_observation()])
    source._client = fake

    metrics = source.fetch_recent_generations(
        since=datetime(2026, 1, 1, tzinfo=timezone.utc), limit=25
    )

    assert len(metrics) == 1
    assert metrics[0].agent_name == "profile_analyst"
    # Called with the keyword-only args langfuse 2.x actually expects.
    assert fake.calls[0]["type"] == "GENERATION"
    assert fake.calls[0]["limit"] == 25
    assert "from_start_time" in fake.calls[0]


def test_fetch_never_requests_more_than_the_api_page_cap():
    """Regression: Langfuse 400s on limit > 100 ("Too big: expected number to be <=100").
    Asking for 500 in one shot broke every worker poll against the live API."""
    source = LangfuseTraceSource()
    fake = _FakeLangfuseClient([_base_observation() for _ in range(100)])
    source._client = fake

    source.fetch_recent_generations(since=datetime(2026, 1, 1, tzinfo=timezone.utc), limit=500)

    assert fake.calls, "expected at least one API call"
    assert all(call["limit"] <= 100 for call in fake.calls)


def test_fetch_pages_through_results_beyond_one_page():
    source = LangfuseTraceSource()
    fake = _FakeLangfuseClient([_base_observation() for _ in range(100)])
    source._client = fake

    metrics = source.fetch_recent_generations(
        since=datetime(2026, 1, 1, tzinfo=timezone.utc), limit=250
    )

    # Full pages keep paging; page numbers must advance.
    assert [call["page"] for call in fake.calls][:3] == [1, 2, 3]
    assert len(metrics) == 250


def test_fetch_stops_paging_on_a_short_page():
    """A page smaller than requested means we've reached the end -- stop, don't loop."""
    source = LangfuseTraceSource()
    fake = _FakeLangfuseClient([_base_observation() for _ in range(3)])
    source._client = fake

    metrics = source.fetch_recent_generations(
        since=datetime(2026, 1, 1, tzinfo=timezone.utc), limit=500
    )

    assert len(fake.calls) == 1
    assert len(metrics) == 3


def test_fetch_recent_generations_returns_empty_on_sdk_error():
    class _Exploding:
        def fetch_observations(self, **kwargs):
            raise AttributeError("'Langfuse' object has no attribute 'api'")

    source = LangfuseTraceSource()
    source._client = _Exploding()

    # Must degrade to [] rather than taking the worker down.
    assert source.fetch_recent_generations(since=datetime.now(timezone.utc)) == []
