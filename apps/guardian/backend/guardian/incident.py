"""Incident: the unit Guardian surfaces to a user.

Deliberately structured, not a free-text alert -- `evidence` must contain the actual
values that triggered it and `trace_ids` must point back to the real Langfuse trace(s),
so every incident is independently checkable. See docs/ARCHITECTURE.md.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detector: str
    severity: str  # "low" | "medium" | "high"
    title: str
    summary: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    trace_ids: List[str] = Field(default_factory=list)
    agent_name: Optional[str] = None
    status: str = "open"  # "open" | "resolved"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
