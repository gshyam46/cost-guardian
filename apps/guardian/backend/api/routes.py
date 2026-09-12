"""Isolated Guardian data routes. Verify configured access before reading data or caches."""
import logging
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from auth import AUTH_CACHE_HEADERS, require_access
from config import POLL_INTERVAL_SECONDS
from db import db
from guardian.incident import Incident
from guardian.langfuse_client import LangfuseTraceSource
from guardian.metrics import MetricsReadLimitError, MongoMetricsStore
from guardian.source_io import SourceReadBusy, SourceReadTimeout, run_source_read
from guardian.store import MongoIncidentStore
from guardian.summaries import IncidentSummaryReader
from guardian.traces import LiveTraceReader
from identity.errors import HEADERS as IDENTITY_HEADERS
from identity.settings import load_settings
from identity.store import IdentityStore
from capture.settings import load_capture_mode
from capture.errors import CaptureError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian", tags=["guardian"])

# One client for the process, same pattern as the orchestrator singleton in
# api/analysis.py. Safe to construct with no credentials -- degrades to trace_url()
# always returning None rather than raising.
try:
    _capture_mode = load_capture_mode()
except CaptureError:
    _capture_mode = "invalid"
_trace_source = (LangfuseTraceSource() if _capture_mode == "langfuse" else
                 SimpleNamespace(available=False, api_version="direct-v1", trace_url=lambda _id: None))

# Read-only Langfuse views (runs, calls, live stats). Nothing here touches Guardian's
# database -- see guardian/traces.py for why these are read through, not stored.
_live = LiveTraceReader(_trace_source)


def close_source():
    close = getattr(_trace_source, "close", None)
    if callable(close):
        close()


class IncidentOut(Incident):
    """Incident plus resolved Langfuse deep links -- computed at response time, not
    stored, so a later Langfuse host/project change doesn't leave stale URLs in Mongo."""

    trace_urls: List[str] = []


def _with_trace_urls(incident: Incident) -> IncidentOut:
    if load_capture_mode() == "direct":
        return IncidentOut(**incident.model_dump(), trace_urls=[])
    urls = [
        url
        for url in (_trace_source.trace_url(trace_id) for trace_id in incident.trace_ids)
        if url
    ]
    return IncidentOut(**incident.model_dump(), trace_urls=urls)


class AccessResponse(BaseModel):
    authenticated: Literal[True] = True
    auth_mode: Literal["api_key"] = "api_key"
    deployment_mode: Literal["single_project"] = "single_project"
    permissions: List[Literal["read", "resolve_incidents"]] = Field(default_factory=lambda: ["read", "resolve_incidents"])


@router.get("/access")
async def get_access(request: Request, response: Response):
    """Verify access independently of telemetry and dashboard health."""
    principal = await require_access(request, db)
    response.headers.update(IDENTITY_HEADERS if principal else AUTH_CACHE_HEADERS)
    return principal.access_response() if principal else AccessResponse()


class OverviewResponse(BaseModel):
    open_incidents: int
    open_by_severity: dict
    open_by_detector: dict
    incidents_last_7_days: int


class TrendPoint(BaseModel):
    date: str
    count: int


class SummaryCoverage(BaseModel):
    status: Literal["complete", "partial"]
    invalid_timestamp_count: int


class IncidentSummaryResponse(BaseModel):
    overview: OverviewResponse
    trends: List[TrendPoint]
    coverage: SummaryCoverage
    as_of: str
    timezone: Literal["UTC"]
    window_start: str
    window_end: str


class MetricPoint(BaseModel):
    hour: str
    agent_name: str
    call_count: int
    error_count: int
    total_cost_usd: Optional[float]
    known_cost_usd: Optional[float] = None
    cost_known_count: Optional[int] = None
    cost_unknown_count: Optional[int] = None
    total_tokens: Optional[int]
    known_total_tokens: Optional[int] = None
    tokens_known_count: Optional[int] = None
    tokens_unknown_count: Optional[int] = None
    avg_latency_ms: Optional[float]
    latency_known_count: Optional[int] = None
    latency_unknown_count: Optional[int] = None
    unknown_status_count: Optional[int] = None
    coverage_status: str = "legacy"
    accounting_status: str = "provisional_incremental"
    conflict_count: int = 0
    aggregate_issues: List[str] = Field(default_factory=list)


async def _incident_summary(days, *, require_complete=False):
    try:
        snapshot = await IncidentSummaryReader(db).snapshot(days=days, now=datetime.now(timezone.utc))
    except Exception:
        logger.warning("[Guardian] Incident summary unavailable")
        raise HTTPException(status_code=503, detail="Incident summary is unavailable. Retry shortly.", headers={"Retry-After": "5"}) from None
    if require_complete and snapshot["coverage"]["status"] != "complete":
        raise HTTPException(status_code=503, detail="Some incident timestamps are unusable. View summary coverage before using these totals.")
    return snapshot


@router.get("/summary", response_model=IncidentSummaryResponse)
async def get_incident_summary(request: Request, days: int = Query(14, ge=1, le=90)):
    """UTC calendar summary including today, with explicit historical coverage."""
    await require_access(request, db)
    return await _incident_summary(days)


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(request: Request):
    await require_access(request, db)
    return (await _incident_summary(7, require_complete=True))["overview"]


@router.get("/incidents", response_model=List[IncidentOut])
async def list_incidents(request: Request, status: Optional[Literal["open", "resolved"]] = None, limit: int = Query(100, ge=1, le=500)):
    """List incidents. `status` filters to "open" or "resolved"; omit for all."""
    await require_access(request, db)

    query = {"status": status} if status else {}
    cursor = db.guardian_incidents.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(limit)
    return [_with_trace_urls(Incident(**doc)) for doc in docs]


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: str, request: Request):
    await require_access(request, db)

    store = MongoIncidentStore(db)
    incident = await store.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _with_trace_urls(incident)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(incident_id: str, request: Request):
    principal = await require_access(request, db, mutation=True)
    if principal:
        incident = await IdentityStore(db, load_settings()).resolve(principal, incident_id)
        return _with_trace_urls(incident)

    store = MongoIncidentStore(db)
    incident = await store.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    await store.resolve(incident_id)
    return _with_trace_urls(await store.get(incident_id))


@router.get("/trends", response_model=List[TrendPoint])
async def get_trends(request: Request, days: int = Query(14, ge=1, le=90)):
    """UTC calendar days including today; incomplete history is unavailable."""
    await require_access(request, db)
    return (await _incident_summary(days, require_complete=True))["trends"]


@router.get("/metrics", response_model=List[MetricPoint])
async def get_metrics(request: Request, hours: int = Query(48, ge=1, le=168)):
    """Hourly cost/latency/error rollups per agent, oldest first.

    This endpoint serves aggregates. Live endpoints separately serve source-derived
    call/run metadata and bounded content previews.
    """
    await require_access(request, db)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        rollups = await MongoMetricsStore(db).since(since)
    except MetricsReadLimitError:
        raise HTTPException(status_code=422, detail="This window exceeds 5,000 metric buckets. Choose a shorter window.") from None
    return [MetricPoint(**rollup) for rollup in rollups]


# --- Live views ---------------------------------------------------------------
#
# One bounded read feeds the widgets, with explicit coverage and cached freshness.
# The worker and live views both consume source capacity; quotas depend on the
# deployed endpoint/plan. Derived previews are cached in memory, not written here
# to Mongo. Content processing/privacy remains an explicit R2 requirement.


@router.get("/live")
async def get_live(request: Request, hours: int = Query(24, ge=1, le=168), runs: int = Query(8, ge=1, le=100), calls: int = Query(60, ge=1, le=100)):
    """Stats, recent runs and the call feed for the last `hours`, in one response."""
    await require_access(request, db)
    if load_capture_mode() == "direct":
        from guardian.direct_traces import DirectTraceReader
        from guardian.traces import LiveReadError
        try:
            return await DirectTraceReader(db, load_settings()).snapshot(hours=hours, run_limit=runs, call_limit=calls)
        except LiveReadError:
            raise HTTPException(503, "Captured telemetry is temporarily unavailable. Retry shortly.") from None
    try:
        return await run_source_read(_live.snapshot, hours=hours, run_limit=runs, call_limit=calls)
    except (SourceReadBusy, SourceReadTimeout):
        raise HTTPException(status_code=503, detail="Telemetry read is busy or timed out. Retry shortly.", headers={"Retry-After": "5"}) from None


@router.get("/live/runs/{trace_id}")
async def get_live_run(trace_id: str, request: Request, hours: int = Query(default=168, ge=1, le=168)):
    """Observed generations in an accessible window; absence does not prove a missing trace."""
    await require_access(request, db)
    if load_capture_mode() == "direct":
        from guardian.direct_traces import DirectTraceReader
        from guardian.traces import LiveReadError
        try:
            return await DirectTraceReader(db, load_settings()).run_detail(trace_id, hours)
        except LiveReadError:
            raise HTTPException(503, "Captured telemetry is temporarily unavailable. Retry shortly.") from None
    if not _live.available:
        raise HTTPException(status_code=503, detail="Langfuse is not configured.")
    from guardian.traces import LiveReadError

    try:
        run = await run_source_read(_live.run_detail, trace_id, hours)
    except (SourceReadBusy, SourceReadTimeout, LiveReadError):
        raise HTTPException(status_code=503, detail="Guardian could not read this run from the telemetry source. Retry shortly.", headers={"Retry-After": "5"}) from None
    return run


@router.get("/monitoring")
async def get_monitoring(request: Request):
    """Worker progress and source-read coverage; API liveness is separate."""
    await require_access(request, db)
    if load_capture_mode() == "direct":
        from capture.service import CaptureService
        status = await CaptureService(db, load_settings()).status()
        return {"source_configured": True, "source_api_version": "direct-v1", "source_kind": "guardian_direct",
                "healthy": False, "status": "direct_capture", "capture": status,
                "stale": status["worker_status"] == "stale", "accounting_status": "ledger-1"}
    doc = await db.guardian_state.find_one({"_id": "guardian_worker_cursor"}) or {}
    now = datetime.now(timezone.utc)
    threshold = max(120, max(1, POLL_INTERVAL_SECONDS) * 3 + 20)
    attempted = doc.get("last_attempt_at")
    age = None
    try:
        if attempted:
            stamp = datetime.fromisoformat(attempted)
            age = max(0.0, (now - stamp.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        pass
    stale = age is None or age > threshold
    configured = _trace_source.available
    source_api = getattr(_trace_source, "api_version", "unknown")
    worker_api = doc.get("source_api_version")
    status = doc.get("processing_status", "not_polled")
    if not configured:
        status = "not_configured"
    elif not attempted:
        status = "not_polled"
    elif stale:
        status = "stale"
    elif worker_api in {"v1", "v2"} and source_api in {"v1", "v2"} and worker_api != source_api:
        status = "source_configuration_changed"
    fields = (
        "last_attempt_at", "last_finished_at", "read_status", "read_error_code",
        "window_start", "window_end", "source_fetched_at", "pages_fetched",
        "records_read", "invalid_count", "duplicate_count", "source_row_limit", "detector_failures",
        "source_watermark", "processing_watermark", "pending_observations", "dirty_buckets", "quarantined_records",
    )
    return {
        **{key: doc.get(key) for key in fields},
        "source_configured": configured,
        "source_api_version": source_api,
        "worker_source_api_version": worker_api,
        "configuration_error": getattr(_trace_source, "configuration_error", None),
        "status": status,
        "healthy": configured and not stale and status == "complete" and doc.get("read_status") == "complete",
        "stale": stale,
        "stale_after_seconds": threshold,
        "last_successful_checkpoint": doc.get("last_polled_at"),
        "accounting_status": doc.get("ledger_version", "provisional_incremental"),
    }
