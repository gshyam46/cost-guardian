"""Shared result type for all Guardian detectors."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DetectorResult:
    """One anomaly flagged by a detector.

    `evidence` is required in spirit (not enforced by the type system, but every
    detector implementation must populate it) -- a result a user can't independently
    verify against the underlying trace is worse than no result. `trace_ids` must be
    non-empty for any triggered result; incident_engine.py rejects results without it.
    """

    triggered: bool
    detector: str
    trace_ids: List[str] = field(default_factory=list)
    severity: Optional[str] = None  # "low" | "medium" | "high"
    title: str = ""
    summary: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    agent_name: Optional[str] = None
