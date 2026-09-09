"""Guardian API routes: incidents, metrics and overview stats for the dashboard.

Authenticated with Guardian's own API key (see auth.py) -- this service no longer
borrows a monitored application's session, because it no longer shares a process with
one. Still single-tenant: one key, one Langfuse project. Per-project keys are a real
multi-tenancy requirement tracked in docs/PHASES.md, not an oversight.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth import require_api_key
from db import db
from guardian.incident import Incident
from guardian.langfuse_client import LangfuseTraceSource
from guardian.metrics import MongoMetricsStore
from guardian.store import MongoIncidentStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian", tags=["guardian"])

# One client for the process, same pattern as the orchestrator singleton in
# api/analysis.py. Safe to construct with no credentials -- degrades to trace_url()
# always returning None rather than raising.
_trace_source = LangfuseTraceSource()


class IncidentOut(Incident):
    """Incident plus resolved Langfuse deep links -- computed at response time, not
    stored, so a later Langfuse host/project change doesn't leave stale URLs in Mongo."""

    trace_urls: List[str] = []


def _with_trace_urls(incident: Incident) -> IncidentOut:
    urls = [
        url
        for url in (_trace_source.trace_url(trace_id) for trace_id in incident.trace_ids)
        if url
    ]
    return IncidentOut(**incident.model_dump(), trace_urls=urls)


class OverviewResponse(BaseModel):
    open_incidents: int
    open_by_severity: dict
    open_by_detector: dict
    incidents_last_7_days: int


class TrendPoint(BaseModel):
    date: str
    count: int


class MetricPoint(BaseModel):
    hour: str
    agent_name: str
    call_count: int
    error_count: int
    total_cost_usd: float
    total_tokens: int
    avg_latency_ms: float


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(request: Request):
    require_api_key(request)

    open_docs = await db.guardian_incidents.find({"status": "open"}, {"_id": 0}).to_list(1000)
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_count = await db.guardian_incidents.count_documents(
        {"created_at": {"$gte": seven_days_ago}}
    )

    return OverviewResponse(
        open_incidents=len(open_docs),
        open_by_severity=dict(Counter(d.get("severity", "unknown") for d in open_docs)),
        open_by_detector=dict(Counter(d.get("detector", "unknown") for d in open_docs)),
        incidents_last_7_days=recent_count,
    )


@router.get("/incidents", response_model=List[IncidentOut])
async def list_incidents(request: Request, status: Optional[str] = None, limit: int = 100):
    """List incidents. `status` filters to "open" or "resolved"; omit for all."""
    require_api_key(request)

    query = {"status": status} if status else {}
    cursor = db.guardian_incidents.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(limit)
    return [_with_trace_urls(Incident(**doc)) for doc in docs]


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: str, request: Request):
    require_api_key(request)

    store = MongoIncidentStore(db)
    incident = await store.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _with_trace_urls(incident)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(incident_id: str, request: Request):
    require_api_key(request)

    store = MongoIncidentStore(db)
    incident = await store.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    await store.resolve(incident_id)
    return _with_trace_urls(await store.get(incident_id))


@router.get("/trends", response_model=List[TrendPoint])
async def get_trends(request: Request, days: int = 14):
    """Incident count per day for the last `days` days, oldest first."""
    require_api_key(request)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    docs = await db.guardian_incidents.find(
        {"created_at": {"$gte": since.isoformat()}}, {"_id": 0, "created_at": 1}
    ).to_list(10000)

    counts = Counter()
    for doc in docs:
        created_at = doc.get("created_at", "")
        day = created_at[:10] if created_at else "unknown"
        counts[day] += 1

    points = []
    for i in range(days):
        day = (since + timedelta(days=i)).date().isoformat()
        points.append(TrendPoint(date=day, count=counts.get(day, 0)))
    return points


@router.get("/metrics", response_model=List[MetricPoint])
async def get_metrics(request: Request, hours: int = 48):
    """Hourly cost/latency/error rollups per agent, oldest first.

    Aggregates only -- for an individual call, follow an incident's trace_urls into
    Langfuse. Guardian does not serve raw traces.
    """
    require_api_key(request)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rollups = await MongoMetricsStore(db).since(since)
    return [MetricPoint(**rollup) for rollup in rollups]
