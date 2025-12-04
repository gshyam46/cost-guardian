"""User models for authentication."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import uuid


class User(BaseModel):
    """User model for storing user data."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True


class UserSession(BaseModel):
    """Session model for user authentication."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    session_token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
