"""Reports API routes."""
from fastapi import APIRouter, Request, HTTPException
from typing import List
from datetime import datetime
import logging

from db.database import db
from models.report import NicheReport, ReportSummary
from auth.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=List[ReportSummary])
async def list_reports(request: Request):
    """List all reports for the current user."""
    user = await get_current_user(request)
    
    reports = await db.reports.find(
        {"user_id": user.id},
        {"_id": 0, "id": 1, "recommended_niches": 1, "created_at": 1, "status": 1}
    ).sort("created_at", -1).to_list(100)
    
    summaries = []
    for r in reports:
        niches = r.get("recommended_niches", [])
        top_niche = niches[0] if niches else {}
        
        created_at = r.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        summaries.append(ReportSummary(
            id=r["id"],
            top_niche=top_niche.get("name", "Unknown"),
            fit_score=top_niche.get("fit_score", 0),
            created_at=created_at,
            status=r.get("status", "completed")
        ))
    
    return summaries


@router.get("/{report_id}")
async def get_report(report_id: str, request: Request):
    """Get a specific report by ID."""
    user = await get_current_user(request)
    
    report_doc = await db.reports.find_one(
        {"id": report_id, "user_id": user.id},
        {"_id": 0}
    )
    
    if not report_doc:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Convert datetime
    if isinstance(report_doc.get('created_at'), str):
        report_doc['created_at'] = datetime.fromisoformat(report_doc['created_at'])
    
    return report_doc


@router.delete("/{report_id}")
async def delete_report(report_id: str, request: Request):
    """Delete a report."""
    user = await get_current_user(request)
    
    result = await db.reports.delete_one({"id": report_id, "user_id": user.id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {"message": "Report deleted successfully"}


@router.patch("/{report_id}/milestones")
async def update_milestones(report_id: str, request: Request):
    """Update milestone completion status."""
    user = await get_current_user(request)
    body = await request.json()
    
    milestones = body.get("milestones_completed", [])
    
    result = await db.reports.update_one(
        {"id": report_id, "user_id": user.id},
        {"$set": {"milestones_completed": milestones}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return {"message": "Milestones updated successfully"}
