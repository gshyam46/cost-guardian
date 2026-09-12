"""Atomically create one incident per stable source/rule/finding identity.

Incident grouping/lifecycle expansion remains separate. Replayed measurements or
changed narratives cannot recreate or reopen an already recorded finding.
"""
import hashlib
import json
import logging
from typing import List, Optional

from .detectors.base import DetectorResult
from .incident import Incident
from .store import IncidentStore

logger = logging.getLogger(__name__)


def signal_id(result: DetectorResult, *, scope_id: Optional[str] = None) -> str:
    """Versioned canonical identity; never hash mutable evidence or raw content.

    Observation identity distinguishes calls from the same agent within one
    trace. Legacy callers without it use a coarser trace/agent identity. That
    fallback cannot establish distinct-observation coverage and must not be used
    as an invented source ID by ingestion.
    """
    if not isinstance(result.trace_ids, (list, tuple)) or not isinstance(result.observation_ids, (list, tuple)):
        raise ValueError("invalid_signal_identity")
    if not result.trace_ids or any(not isinstance(value, str) or not value.strip()
                                   for value in [*result.trace_ids, *result.observation_ids]):
        raise ValueError("invalid_signal_identity")
    traces = sorted(set(result.trace_ids))
    observations = sorted(set(result.observation_ids))
    values = (result.source, result.detector, result.rule_version, result.finding_kind)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("invalid_signal_identity")
    if any(value is not None and (not isinstance(value, str) or not value.strip())
           for value in (scope_id, result.project_id, result.agent_name)):
        raise ValueError("invalid_signal_identity")
    identity = {
        "schema": 1,
        "scope_id": scope_id,
        "source": result.source,
        "project_id": result.project_id,
        "detector": result.detector,
        "rule_version": result.rule_version,
        "finding_kind": result.finding_kind,
        "trace_ids": traces,
        "observation_ids": observations,
        "legacy_agent": result.agent_name if not observations else None,
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "signal_v1_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def process_detector_results(
    results: List[DetectorResult], store: IncidentStore, *, scope_id: Optional[str] = None
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

        try:
            identity = signal_id(result, scope_id=scope_id)
        except (TypeError, ValueError):
            logger.warning("[Guardian] Detector result has invalid signal identity; skipping")
            continue

        incident = Incident(
            id=identity,
            detector=result.detector,
            severity=result.severity or "low",
            title=result.title or f"{result.detector} anomaly",
            summary=result.summary,
            evidence=result.evidence,
            trace_ids=result.trace_ids,
            agent_name=result.agent_name,
        )
        if await store.create_if_absent(incident):
            created.append(incident)
            logger.info(f"[Guardian] New incident: {incident.title} ({incident.severity})")

    return created
