"""Cost Guardian API service.

Standalone: runs on its own port, with its own database and its own auth. It does not
import from, or get imported by, any application it monitors -- the only coupling is
that both talk to Langfuse.

Run:
    cd apps/guardian/backend
    uvicorn server:app --reload --port 8001

The worker is a separate process:
    python -m guardian.worker
"""
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.routes import router as guardian_router
from config import CORS_ORIGINS, GUARDIAN_API_KEY
from db import close_database

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Cost Guardian",
    description="AI reliability and incident intelligence, layered over existing LLM observability.",
    version="0.1.0",
)

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health_check():
    """Unauthenticated on purpose so orchestrators can probe it."""
    return {"status": "healthy", "service": "cost-guardian"}


api_router.include_router(guardian_router)
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Cost Guardian API")
    if not GUARDIAN_API_KEY:
        logger.warning(
            "GUARDIAN_API_KEY is not set -- every data endpoint will return 503 until "
            "it is configured in apps/guardian/backend/.env"
        )
    yield
    await close_database()


app.router.lifespan_context = lifespan
