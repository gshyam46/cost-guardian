"""API routes package."""
from .auth import router as auth_router
from .profile import router as profile_router
from .analysis import router as analysis_router
from .reports import router as reports_router

__all__ = ['auth_router', 'profile_router', 'analysis_router', 'reports_router']
