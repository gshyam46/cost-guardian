"""Founder profile models."""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
import uuid


class ProfileCreate(BaseModel):
    """Input model for creating/updating a founder profile."""
    # Background
    education: str
    current_role: str
    years_experience: int
    
    # Skills & Strengths
    tech_skills: List[str] = []
    domain_skills: List[str] = []
    soft_skills: List[str] = []
    previous_projects: Optional[str] = None
    
    # Interests
    excited_domains: List[str] = []
    
    # Constraints
    hours_per_week: int
    runway_months: Optional[int] = None
    location: Optional[str] = None
    risk_appetite: str  # low, medium, high
    
    # Career Goals
    target_roles: List[str] = []
    
    # Resources
    existing_portfolio: Optional[str] = None
    github_url: Optional[str] = None
    network_strength: str  # weak, moderate, strong
    
    # Learning Preference
    learning_mode: str  # build-first, theory-first, mentor-led, self-paced


class FounderProfile(ProfileCreate):
    """Full founder profile with metadata."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
