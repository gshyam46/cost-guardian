"""Turns detector output into stored, deduplicated incidents.

Detectors are re-run over an overlapping window of traces every poll cycle (needed to
maintain a rolling baseline -- see docs/ARCHITECTURE.md), so this module's dedup check
is what stands between that and duplicate incidents for the same anomaly.
"""
import logging
from typing import List

from .detectors.base import DetectorResult
from .incident import Incident
from .store import IncidentStore

logger = logging.getLogger(__name__)


async def process_detector_results(
    results: List[DetectorResult], store: IncidentStore
) -> List[Incident]:
    """Persist new incidents for triggered, not-yet-seen detector results.

    Returns only incidents actually created by this call, not pre-existing ones --
    callers use this to know what's new since the last poll (e.g. to notify).
    """
    created: List[Incident] = []

    for result in results:
        if not result.triggered:
            continue

        if not result.trace_ids:
            logger.warning(
                f"Detector {result.detector} triggered with no trace_ids -- skipping. "
                "An incident must be traceable to evidence."
            )
            continue

        primary_trace_id = result.trace_ids[0]
        if await store.exists(result.detector, primary_trace_id):
            continue

        incident = Incident(
            detector=result.detector,
            severity=result.severity or "low",
            title=result.title or f"{result.detector} anomaly",
            summary=result.summary,
            evidence=result.evidence,
            trace_ids=result.trace_ids,
            agent_name=result.agent_name,
        )
        await store.save(incident)
        created.append(incident)
        logger.info(f"[Guardian] New incident: {incident.title} ({incident.severity})")

    return created
