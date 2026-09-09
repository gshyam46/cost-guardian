from datetime import datetime, timezone

from guardian.detectors import pii
from guardian.models import TraceMetric


def _trace(trace_id, output_text):
    return TraceMetric(
        trace_id=trace_id,
        agent_name="tooling_advisor",
        model="groq/llama-3.3-70b-versatile",
        cost_usd=0.01,
        total_tokens=500,
        latency_ms=500.0,
        status="success",
        timestamp=datetime.now(timezone.utc),
        output_text=output_text,
    )


def test_flags_email_in_output():
    results = pii.evaluate([], [_trace("t1", "Contact me at founder@example.com for details.")])

    assert len(results) == 1
    assert results[0].detector == "pii"
    assert "email" in results[0].evidence["pii_types"]
    assert results[0].severity == "high"


def test_flags_ssn_in_output():
    results = pii.evaluate([], [_trace("t1", "SSN on file: 123-45-6789")])

    assert len(results) == 1
    assert "ssn" in results[0].evidence["pii_types"]


def test_flags_multiple_pii_types_in_one_output():
    results = pii.evaluate(
        [], [_trace("t1", "Email founder@example.com or call 555-123-4567.")]
    )

    assert len(results) == 1
    assert set(results[0].evidence["pii_types"]) >= {"email", "phone"}


def test_no_false_positive_on_clean_text():
    results = pii.evaluate(
        [], [_trace("t1", "Your top niche is B2B analytics tooling for seed-stage teams.")]
    )

    assert results == []


def test_no_false_positive_on_plain_numbers():
    results = pii.evaluate(
        [], [_trace("t1", "Phase 1 runs from month 1 to month 3, budget $10000.")]
    )

    assert results == []


def test_handles_empty_output_gracefully():
    results = pii.evaluate([], [_trace("t1", "")])

    assert results == []
