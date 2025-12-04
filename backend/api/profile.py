"""Profile API routes."""
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone
import logging

from db.database import db
from models.profile import FounderProfile, ProfileCreate
from auth.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("", response_model=FounderProfile)
async def create_or_update_profile(profile_data: ProfileCreate, request: Request):
    """Create or update the founder profile for the current user."""
    user = await get_current_user(request)
    
    # Check if profile exists
    existing = await db.profiles.find_one({"user_id": user.id})
    
    if existing:
        # Update existing profile
        profile = FounderProfile(
            id=existing["id"],
            user_id=user.id,
            created_at=datetime.fromisoformat(existing["created_at"]) if isinstance(existing["created_at"], str) else existing["created_at"],
            updated_at=datetime.now(timezone.utc),
            **profile_data.model_dump()
        )
        
        profile_doc = profile.model_dump()
        profile_doc["created_at"] = profile_doc["created_at"].isoformat()
        profile_doc["updated_at"] = profile_doc["updated_at"].isoformat()
        
        await db.profiles.update_one(
            {"id": existing["id"]},
            {"$set": profile_doc}
        )
    else:
        # Create new profile
        profile = FounderProfile(
            user_id=user.id,
            **profile_data.model_dump()
        )
        
        profile_doc = profile.model_dump()
        profile_doc["created_at"] = profile_doc["created_at"].isoformat()
        profile_doc["updated_at"] = profile_doc["updated_at"].isoformat()
        
        await db.profiles.insert_one(profile_doc)
    
    return profile


@router.get("", response_model=FounderProfile | None)
async def get_profile(request: Request):
    """Get the founder profile for the current user."""
    user = await get_current_user(request)
    
    profile_doc = await db.profiles.find_one({"user_id": user.id}, {"_id": 0})
    
    if not profile_doc:
        return None
    
    # Convert datetime strings
    if isinstance(profile_doc.get('created_at'), str):
        profile_doc['created_at'] = datetime.fromisoformat(profile_doc['created_at'])
    if isinstance(profile_doc.get('updated_at'), str):
        profile_doc['updated_at'] = datetime.fromisoformat(profile_doc['updated_at'])
    
    return FounderProfile(**profile_doc)
