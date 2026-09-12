"""Shared result type for all Guardian detectors."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models import TraceMetric


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
    observation_ids: List[str] = field(default_factory=list)
    source: str = "langfuse"
    project_id: Optional[str] = None
    rule_version: str = "1"
    finding_kind: str = "anomaly"


def observation_identity(candidate: TraceMetric, finding_kind: str, rule_version: str) -> dict:
    """Carry source identity separately from changing presentation/evidence.

    Hand-built legacy candidates can lack an observation ID. The engine retains
    an explicitly coarser trace/agent fallback for those callers; production
    normalization requires an actual source observation ID.
    """
    return {
        "observation_ids": [candidate.observation_id] if candidate.observation_id else [],
        "source": candidate.source,
        "project_id": candidate.project_id,
        "rule_version": rule_version,
        "finding_kind": finding_kind,
    }
