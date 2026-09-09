"""Authentication API routes using Emergent Auth."""
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import httpx
import logging

from db.database import db
from models.user import User, UserSession
from auth.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class SessionRequest(BaseModel):
    """Request body for session processing."""
    session_id: str


class UserResponse(BaseModel):
    """Response model for user data."""
    id: str
    email: str
    name: str
    picture: str | None = None


@router.post("/session")
async def process_session(request: SessionRequest, response: Response):
    """Process session ID from Emergent Auth and create local session.
    
    This endpoint:
    1. Exchanges the session_id for user data from Emergent Auth
    2. Creates/updates user in our database
    3. Creates a local session
    4. Sets httpOnly cookie for auth
    """
    try:
        # Exchange session_id for user data
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": request.session_id}
            )
            
            if auth_response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session")
            
            auth_data = auth_response.json()
        
        # Check if user exists
        existing_user = await db.users.find_one({"email": auth_data["email"]})
        
        if existing_user:
            user_id = existing_user["id"]
        else:
            # Create new user
            user = User(
                email=auth_data["email"],
                name=auth_data["name"],
                picture=auth_data.get("picture")
            )
            user_doc = user.model_dump()
            user_doc["created_at"] = user_doc["created_at"].isoformat()
            await db.users.insert_one(user_doc)
            user_id = user.id
        
        # Create session
        session = UserSession(
            user_id=user_id,
            session_token=auth_data["session_token"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        session_doc = session.model_dump()
        session_doc["created_at"] = session_doc["created_at"].isoformat()
        session_doc["expires_at"] = session_doc["expires_at"].isoformat()
        await db.user_sessions.insert_one(session_doc)
        
        # Set cookie
        response.set_cookie(
            key="session_token",
            value=auth_data["session_token"],
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
            max_age=7 * 24 * 60 * 60  # 7 days
        )
        
        return {
            "id": user_id,
            "email": auth_data["email"],
            "name": auth_data["name"],
            "picture": auth_data.get("picture")
        }
        
    except httpx.RequestError as e:
        logger.error(f"Auth request error: {e}")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    """Get current authenticated user."""
    user = await get_current_user(request)
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout current user."""
    # Get session token
    session_token = request.cookies.get("session_token")
    if session_token:
        # Delete session from database
        await db.user_sessions.delete_one({"session_token": session_token})
    
    # Clear cookie
    response.delete_cookie(
        key="session_token",
        path="/",
        secure=True,
        samesite="none"
    )
    
    return {"message": "Logged out successfully"}
