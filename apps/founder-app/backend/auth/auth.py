"""Authentication utilities using Emergent Auth."""
from fastapi import Request, HTTPException
from typing import Optional
from datetime import datetime, timezone
from db.database import db
from models.user import User


async def get_session_token(request: Request) -> Optional[str]:
    """Extract session token from cookies or Authorization header."""
    # Check cookies first
    session_token = request.cookies.get("session_token")
    if session_token:
        return session_token
    
    # Fallback to Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    
    return None


async def get_current_user(request: Request) -> User:
    """Get the current authenticated user. Raises 401 if not authenticated."""
    session_token = await get_session_token(request)
    
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = await db.user_sessions.find_one({"session_token": session_token})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Check expiry
    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    
    # Find user
    user_doc = await db.users.find_one({"id": session["user_id"]})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Convert datetime if needed
    if isinstance(user_doc.get('created_at'), str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'].replace('Z', '+00:00'))
    
    return User(**{k: v for k, v in user_doc.items() if k != '_id'})


async def get_optional_user(request: Request) -> Optional[User]:
    """Get the current user if authenticated, None otherwise."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
