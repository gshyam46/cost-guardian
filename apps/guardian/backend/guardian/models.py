"""Shared data types for the Guardian detection layer."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TraceMetric:
    """The subset of one Langfuse trace/generation that detectors care about.

    This is Guardian's internal representation -- langfuse_client.py is responsible
    for translating raw Langfuse API responses into these, so detectors never depend
    on Langfuse's response shape directly.
    """

    trace_id: str
    agent_name: str
    model: str
    cost_usd: float
    total_tokens: int
    latency_ms: float
    status: str  # "success" | "error"
    timestamp: datetime
    output_text: Optional[str] = None
