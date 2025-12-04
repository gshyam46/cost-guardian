"""Analysis API routes for running the agent pipeline."""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime, timezone

from db.database import db
from auth.auth import get_current_user
from services.orchestrator import NicheDiscoveryOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyze", tags=["analysis"])

orchestrator = NicheDiscoveryOrchestrator()


class AnalyzeRequest(BaseModel):
    """Request body for analysis."""
    profile_id: Optional[str] = None  # Use existing profile


class AnalyzeResponse(BaseModel):
    """Response for analysis request."""
    report_id: str
    status: str
    message: str


@router.post("", response_model=AnalyzeResponse)
async def run_analysis(request: Request, body: AnalyzeRequest = None):
    """Run the niche discovery analysis pipeline.
    
    This endpoint:
    1. Fetches the user's profile
    2. Runs all agents in sequence
    3. Saves the report to the database
    4. Returns the report ID
    """
    user = await get_current_user(request)
    body = body or AnalyzeRequest()
    
    # Get profile
    if body.profile_id:
        profile_doc = await db.profiles.find_one({"id": body.profile_id, "user_id": user.id})
    else:
        profile_doc = await db.profiles.find_one({"user_id": user.id})
    
    if not profile_doc:
        raise HTTPException(status_code=404, detail="Profile not found. Please complete onboarding first.")
    
    # Prepare profile data for agents
    profile_data = {
        "education": profile_doc.get("education", ""),
        "current_role": profile_doc.get("current_role", ""),
        "years_experience": profile_doc.get("years_experience", 0),
        "tech_skills": profile_doc.get("tech_skills", []),
        "domain_skills": profile_doc.get("domain_skills", []),
        "soft_skills": profile_doc.get("soft_skills", []),
        "previous_projects": profile_doc.get("previous_projects", ""),
        "excited_domains": profile_doc.get("excited_domains", []),
        "hours_per_week": profile_doc.get("hours_per_week", 10),
        "runway_months": profile_doc.get("runway_months"),
        "location": profile_doc.get("location", ""),
        "risk_appetite": profile_doc.get("risk_appetite", "medium"),
        "target_roles": profile_doc.get("target_roles", []),
        "existing_portfolio": profile_doc.get("existing_portfolio", ""),
        "github_url": profile_doc.get("github_url", ""),
        "network_strength": profile_doc.get("network_strength", "moderate"),
        "learning_mode": profile_doc.get("learning_mode", "build-first")
    }
    
    try:
        # Run the orchestrator
        logger.info(f"Starting analysis for user {user.id}")
        report = await orchestrator.run(profile_data, user.id, profile_doc["id"])
        
        # Save report to database
        report_doc = report.model_dump()
        report_doc["created_at"] = report_doc["created_at"].isoformat()
        
        await db.reports.insert_one(report_doc)
        
        logger.info(f"Analysis completed for user {user.id}, report {report.id}")
        
        return AnalyzeResponse(
            report_id=report.id,
            status="completed",
            message="Analysis completed successfully"
        )
        
    except Exception as e:
        logger.error(f"Analysis failed for user {user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
