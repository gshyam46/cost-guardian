"""Where incidents are stored.

IncidentStore is an interface, not a concrete class, specifically so
incident_engine.py's dedup/severity logic is unit-testable without a running
database -- InMemoryIncidentStore is what the test suite uses; MongoIncidentStore is
what the app and worker use. See docs/ARCHITECTURE.md.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .incident import Incident


class IncidentStore(ABC):
    @abstractmethod
    async def save(self, incident: Incident) -> None: ...

    @abstractmethod
    async def exists(self, detector: str, trace_id: str) -> bool:
        """True if an incident already exists for this detector+trace combination.

        This is the dedup key: the worker re-scans an overlapping window of traces
        every poll cycle (needed to keep a rolling baseline), so without this every
        cycle would re-flag the same anomaly as a new incident.
        """
        ...

    @abstractmethod
    async def list_open(self, limit: int = 100) -> List[Incident]: ...

    @abstractmethod
    async def get(self, incident_id: str) -> Optional[Incident]: ...

    @abstractmethod
    async def resolve(self, incident_id: str) -> None: ...


class InMemoryIncidentStore(IncidentStore):
    """No I/O. Used by tests, and safe as a local fallback if Mongo is unavailable."""

    def __init__(self) -> None:
        self._incidents: Dict[str, Incident] = {}

    async def save(self, incident: Incident) -> None:
        self._incidents[incident.id] = incident

    async def exists(self, detector: str, trace_id: str) -> bool:
        return any(
            incident.detector == detector and trace_id in incident.trace_ids
            for incident in self._incidents.values()
        )

    async def list_open(self, limit: int = 100) -> List[Incident]:
        open_incidents = [i for i in self._incidents.values() if i.status == "open"]
        open_incidents.sort(key=lambda i: i.created_at, reverse=True)
        return open_incidents[:limit]

    async def get(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    async def resolve(self, incident_id: str) -> None:
        incident = self._incidents.get(incident_id)
        if incident:
            incident.status = "resolved"
            incident.resolved_at = datetime.now(timezone.utc)


class MongoIncidentStore(IncidentStore):
    """Real backing store used by the running app and the Guardian worker."""

    def __init__(self, db) -> None:
        self._collection = db.guardian_incidents

    @staticmethod
    def _to_doc(incident: Incident) -> dict:
        doc = incident.model_dump()
        doc["created_at"] = doc["created_at"].isoformat()
        if doc.get("resolved_at"):
            doc["resolved_at"] = doc["resolved_at"].isoformat()
        return doc

    @staticmethod
    def _from_doc(doc: dict) -> Incident:
        return Incident(**{k: v for k, v in doc.items() if k != "_id"})

    async def save(self, incident: Incident) -> None:
        await self._collection.update_one(
            {"id": incident.id}, {"$set": self._to_doc(incident)}, upsert=True
        )

    async def exists(self, detector: str, trace_id: str) -> bool:
        doc = await self._collection.find_one({"detector": detector, "trace_ids": trace_id})
        return doc is not None

    async def list_open(self, limit: int = 100) -> List[Incident]:
        cursor = (
            self._collection.find({"status": "open"}).sort("created_at", -1).limit(limit)
        )
        return [self._from_doc(doc) async for doc in cursor]

    async def get(self, incident_id: str) -> Optional[Incident]:
        doc = await self._collection.find_one({"id": incident_id})
        return self._from_doc(doc) if doc else None

    async def resolve(self, incident_id: str) -> None:
        await self._collection.update_one(
            {"id": incident_id},
            {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat()}},
        )
