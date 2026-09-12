"""Shared data types for the Guardian detection layer."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional


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
    cost_usd: Optional[float]
    total_tokens: Optional[int]
    latency_ms: Optional[float]
    status: str  # observation-level "success" | "error" | "unknown"
    timestamp: datetime
    output_text: Optional[str] = None
    observation_id: Optional[str] = None  # Required by source normalization.
    source: str = "langfuse"
    observation_kind: str = "GENERATION"
    project_id: Optional[str] = None  # Attribution, never tenant authorization.
    environment: Optional[str] = None
    version: Optional[str] = None
    parent_observation_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    ended_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completion_state: str = "unknown"
    cost_usd_decimal: Optional[str] = None
    revision_fingerprint: Optional[str] = None
    normalization_issues: tuple[str, ...] = ()
    status_message: Optional[str] = None  # Existing content feature; not a safe diagnostic.
    time_to_first_token_ms: Optional[float] = None
    trace_name: Optional[str] = None  # Explicit observation trace context, not a child name.
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    trace_tags: tuple[str, ...] = ()

    @property
    def revision(self) -> Optional[str]:
        """Compatibility name for the normalized fingerprint, not a sequence."""
        return self.revision_fingerprint


@dataclass
class NormalizationResult:
    metric: Optional[TraceMetric]
    disposition: Literal["valid", "invalid"]
    issues: tuple[str, ...] = ()


@dataclass
class SourceReadResult:
    metrics: list[TraceMetric]
    status: Literal["complete", "partial", "failed"]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    pages_fetched: int = 0
    records_read: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0
    issues: dict[str, int] = field(default_factory=dict)
    error_code: Optional[str] = None
    next_page: Optional[int] = None
    api_version: str = "v1"
    next_cursor: Optional[str] = field(default=None, repr=False)

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None or self.next_page is not None

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass
class SourceRowDisposition:
    """One source row, including duplicates and unusable observations.

    ``metric`` is transient and may contain existing content features. Durable
    stores must use an explicit scalar allowlist, never serialize this whole
    object. Quarantined rows have no metric and retain no raw content.
    """

    ordinal: int
    disposition: Literal["accepted", "quarantined"]
    record_fingerprint: str
    metric: Optional[TraceMetric] = field(default=None, repr=False)
    observation_id: Optional[str] = field(default=None, repr=False)
    trace_id: Optional[str] = field(default=None, repr=False)
    source_project_id: Optional[str] = field(default=None, repr=False)
    issues: tuple[str, ...] = ()


@dataclass
class SourcePageResult:
    """A single page's protocol validity, independently of row data quality.

    An ``ok`` page is committable only after all its row dispositions have been
    durably recorded. ``exhausted`` describes source traversal, not settlement or
    absence of quarantined data. Failed pages never contain committable rows.
    """

    rows: list[SourceRowDisposition]
    status: Literal["ok", "failed"]
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    api_version: str = "v2"
    normalization_version: str = "langfuse-v2-1"
    query_fingerprint: Optional[str] = None
    request_cursor: Optional[str] = field(default=None, repr=False)
    next_cursor: Optional[str] = field(default=None, repr=False)
    exhausted: Optional[bool] = None
    error_code: Optional[str] = None
    issues: dict[str, int] = field(default_factory=dict)
    records_read: int = 0

    @property
    def committable(self) -> bool:
        return self.status == "ok" and self.exhausted is not None

    @property
    def has_more(self) -> bool:
        return self.committable and self.exhausted is False and self.next_cursor is not None
