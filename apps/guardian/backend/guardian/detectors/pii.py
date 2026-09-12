"""PII detection.

Regex against well-defined formats (email, phone, SSN, credit card, IP address). No
baseline needed -- unlike cost/latency, "contains an SSN" isn't a statistical property
of an agent's history, it's true or false about one output. Ships ahead of prompt
injection detection because it's mechanically checkable: every pattern below has a
concrete, testable ground truth. See docs/PRODUCT.md for why injection detection is
deferred instead of shipped as an unvalidated heuristic.
"""
import re
from typing import List

from ..models import TraceMetric
from .base import DetectorResult, observation_identity

NAME = "pii"
RULE_VERSION = "1"

PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
    "ssn": re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0{4})\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip_address": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    ),
}


def detect_pii(text: str) -> List[str]:
    """Return the list of PII pattern labels found in text (empty if none)."""
    if not text:
        return []
    return [label for label, pattern in PII_PATTERNS.items() if pattern.search(text)]


def evaluate(baseline: List[TraceMetric], candidates: List[TraceMetric]) -> List[DetectorResult]:
    results: List[DetectorResult] = []

    for candidate in candidates:
        found = detect_pii(candidate.output_text or "")
        if not found:
            continue

        results.append(
            DetectorResult(
                triggered=True,
                detector=NAME,
                trace_ids=[candidate.trace_id],
                severity="high",
                title=f"Possible PII in {candidate.agent_name} output",
                summary=f"Detected {', '.join(found)} pattern(s) in agent output.",
                evidence={"pii_types": found},
                agent_name=candidate.agent_name,
                **observation_identity(candidate, "pii_pattern", RULE_VERSION),
            )
        )

    return results
