"""Niche report models."""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid


class Niche(BaseModel):
    """A recommended startup niche/problem space."""
    name: str
    description: str
    problem_statement: str
    target_audience: str
    why_fits_you: str
    market_opportunity: str
    competition_level: str  # low, medium, high
    fit_score: int  # 1-100
    improvement_areas: List[str] = []
    cofounder_skills_needed: List[str] = []


class RoadmapPhase(BaseModel):
    """A phase in the roadmap."""
    phase_name: str  # e.g., "0-3 months"
    goals: List[str]
    actions: List[str]
    resources: List[Dict[str, str]]  # {"name": "...", "url": "...", "type": "free/paid"}
    milestones: List[str]
    deliverables: List[str]


class Roadmap(BaseModel):
    """Complete roadmap for founder journey."""
    phases: List[RoadmapPhase]
    suggested_roles: List[Dict[str, str]]  # {"role": "...", "company_type": "...", "why": "..."}
    first_customer_strategies: List[str]


class ToolRecommendation(BaseModel):
    """Tool/platform recommendation."""
    name: str
    category: str  # e.g., "AI/ML", "Cloud", "Development", "Analytics"
    description: str
    pricing: str  # "free", "freemium", "low-cost", "open-source"
    url: Optional[str] = None
    why_recommended: str


class ProfileSummary(BaseModel):
    """Summarized profile from the Profile Analyst agent."""
    background_summary: str
    key_strengths: List[str]
    notable_skills: List[str]
    constraints_summary: str
    ideal_founder_archetype: str


class NicheReport(BaseModel):
    """Complete niche discovery report."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    profile_id: str
    
    # Agent outputs
    profile_summary: ProfileSummary
    recommended_niches: List[Niche]
    selected_niche: Optional[Niche] = None
    roadmap: Roadmap
    tool_recommendations: List[ToolRecommendation]
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "completed"  # pending, processing, completed, failed
    
    # Progress tracking
    milestones_completed: List[str] = []


class ReportSummary(BaseModel):
    """Summary of a report for listing."""
    id: str
    top_niche: str
    fit_score: int
    created_at: datetime
    status: str
