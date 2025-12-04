"""Founder Niche Discovery Platform - Main FastAPI Application.

This platform helps aspiring founders discover their best startup niche
through an agentic AI system that analyzes profiles and generates roadmaps.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import logging
from pathlib import Path

# Load environment variables first
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from config import CORS_ORIGINS
from db.database import db, close_database
from api import auth_router, profile_router, analysis_router, reports_router

# Create the main app
app = FastAPI(
    title="Founder Niche Discovery Platform",
    description="AI-powered platform to help founders discover their ideal startup niche",
    version="1.0.0"
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Health check endpoint
@api_router.get("/")
async def root():
    return {"message": "Founder Niche Discovery Platform API", "status": "healthy"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "founder-niche-api"}

# Include all routers
api_router.include_router(auth_router)
api_router.include_router(profile_router)
api_router.include_router(analysis_router)
api_router.include_router(reports_router)

# Include the main router in the app
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS if isinstance(CORS_ORIGINS, list) else CORS_ORIGINS.split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Founder Niche Discovery Platform")
    yield
    logger.info("Shutting down Founder Niche Discovery Platform")
    await close_database()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    app.run(debug=True)
