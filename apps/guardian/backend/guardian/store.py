"""Where incidents are stored.

IncidentStore is an interface, not a concrete class, specifically so
incident_engine.py's dedup/severity logic is unit-testable without a running
database -- InMemoryIncidentStore is what the test suite uses; MongoIncidentStore is
what the app and worker use. See docs/ARCHITECTURE.md.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from .incident import Incident


class IncidentStore(ABC):
    @abstractmethod
    async def create_if_absent(self, incident: Incident) -> bool:
        """Atomically insert a stable incident ID; return whether it was created.

        Existing evidence and human lifecycle state remain untouched on replay.
        """
        ...

    @abstractmethod
    async def save(self, incident: Incident) -> None: ...

    @abstractmethod
    async def exists(self, detector: str, trace_id: str) -> bool:
        """Legacy lookup only; creation uses an atomic stable observation identity."""
        ...

    @abstractmethod
    async def list_open(self, limit: int = 100) -> List[Incident]: ...

    @abstractmethod
    async def get(self, incident_id: str) -> Optional[Incident]: ...

    @abstractmethod
    async def resolve(self, incident_id: str) -> None: ...


class InMemoryIncidentStore(IncidentStore):
    """Local test store; never an automatic fallback for failed durable writes."""

    def __init__(self) -> None:
        self._incidents: Dict[str, Incident] = {}

    async def save(self, incident: Incident) -> None:
        self._incidents[incident.id] = incident

    async def create_if_absent(self, incident: Incident) -> bool:
        # No await between lookup and insertion: atomic among this loop's tasks.
        if incident.id in self._incidents:
            return False
        self._incidents[incident.id] = incident.model_copy(deep=True)
        return True

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

    def __init__(self, db, session=None) -> None:
        self._collection = db.guardian_incidents
        self._session = session

    def _session_options(self) -> dict:
        return {"session": self._session} if self._session is not None else {}

    @staticmethod
    def _to_doc(incident: Incident) -> dict:
        doc = incident.model_dump()
        created = doc["created_at"]
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("incident_creation_time_requires_timezone")
        created = created.astimezone(timezone.utc)
        doc["created_at"] = created.isoformat()
        doc["created_at_utc"] = created
        doc["summary_schema"] = 1
        if doc.get("resolved_at"):
            doc["resolved_at"] = doc["resolved_at"].isoformat()
        return doc

    @staticmethod
    def _from_doc(doc: dict) -> Incident:
        return Incident(**{k: v for k, v in doc.items() if k != "_id"})

    async def save(self, incident: Incident) -> None:
        await self._collection.update_one(
            {"id": incident.id}, {"$set": self._to_doc(incident)}, upsert=True,
            **self._session_options(),
        )

    async def create_if_absent(self, incident: Incident) -> bool:
        """Use Mongo's unique _id and insert-only write; no check-then-save race.

        A supplied session lets the caller atomically commit this with ledger
        work. Duplicate-key errors inside transactions must propagate: suppressing
        one could misreport success after Mongo aborted the surrounding transaction.
        """
        try:
            result = await self._collection.update_one(
                {"_id": incident.id}, {"$setOnInsert": self._to_doc(incident)},
                upsert=True, **self._session_options(),
            )
        except DuplicateKeyError:
            if self._session is not None:
                raise
            # A concurrent same-ID insert may win an upsert race. Do not hide a
            # different unique-index conflict or a database lookup failure.
            if await self._collection.find_one({"_id": incident.id}, {"_id": 1}):
                return False
            raise
        return result.upserted_id is not None

    async def exists(self, detector: str, trace_id: str) -> bool:
        doc = await self._collection.find_one(
            {"detector": detector, "trace_ids": trace_id}, **self._session_options(),
        )
        return doc is not None

    async def list_open(self, limit: int = 100) -> List[Incident]:
        cursor = (
            self._collection.find({"status": "open"}, **self._session_options()).sort("created_at", -1).limit(limit)
        )
        return [self._from_doc(doc) async for doc in cursor]

    async def get(self, incident_id: str) -> Optional[Incident]:
        doc = await self._collection.find_one({"id": incident_id}, **self._session_options())
        return self._from_doc(doc) if doc else None

    async def resolve(self, incident_id: str) -> None:
        await self._collection.update_one(
            {"id": incident_id},
            {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat()}},
            **self._session_options(),
        )
