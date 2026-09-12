"""Cost Guardian API service.

Standalone: runs on its own port, with its own database and its own auth. Monitored
applications send numeric usage events directly or provide an existing Langfuse
source. Guardian does not import the monitored application's runtime.

Run:
    cd apps/guardian/backend
    uvicorn server:app --reload --port 8001

The worker is a separate process:
    python -m guardian.worker
Optional Slack delivery uses another process:
    python -m notifications.worker
"""
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from api.routes import router as guardian_router, close_source
from config import CORS_ORIGINS, GUARDIAN_API_KEY
from db import close_database, db
from identity.routes import router as identity_router
from identity.settings import load_settings
from identity.errors import IdentityError
from identity.logging import install_callback_log_filter
from identity.middleware import PrivateGuardianResponses
from capture.routes import router as capture_router
from policies.routes import router as policy_router
from notifications.routes import router as notification_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
install_callback_log_filter()

app = FastAPI(
    title="Cost Guardian",
    description="AI cost and reliability monitoring from native usage events or Langfuse observations.",
    version="0.1.0",
)

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health_check():
    """Unauthenticated on purpose so orchestrators can probe it."""
    return {"status": "healthy", "service": "cost-guardian"}


@api_router.get("/ready")
async def readiness_check(request: Request):
    """Read-only deployment readiness; liveness and worker progress stay separate."""
    from deployment.readiness import ready
    try:
        configuration = getattr(request.app.state, "deployment_configuration", None)
        available = configuration is not None and await ready(db, configuration)
    except Exception:
        available = False
    return JSONResponse({"status": "ready" if available else "not_ready", "service": "cost-guardian"},
        status_code=200 if available else 503,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


api_router.include_router(guardian_router)
api_router.include_router(identity_router)
api_router.include_router(capture_router)
api_router.include_router(policy_router)
api_router.include_router(notification_router)
app.include_router(api_router)

# Absent in ordinary development commands. Explicit production builds use the
# final bounded static handler; API routes retain their own authentication/errors.
from deployment.static import install_static
install_static(app)

try:
    identity_settings = load_settings()
    allowed_origins = [identity_settings.ui_origin] if identity_settings.mode == "oidc" else CORS_ORIGINS
except IdentityError:
    allowed_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Cost Guardian API")
    if not hasattr(app.state, "deployment_configuration"):
        # Freeze the process configuration once. Public probes never re-read
        # secrets or re-snapshot the complete static build.
        from deployment.configuration import load_configuration
        try:
            app.state.deployment_configuration = load_configuration()
        except Exception:
            app.state.deployment_configuration = None
    try:
        auth_mode = load_settings().mode
    except IdentityError:
        auth_mode = "invalid"
        logger.warning("Guardian access configuration is invalid; authenticated routes are unavailable")
    if auth_mode == "api_key" and not GUARDIAN_API_KEY:
        logger.warning(
            "GUARDIAN_API_KEY is not set -- every data endpoint will return 503 until "
            "it is configured in apps/guardian/backend/.env"
        )
    try:
        yield
    finally:
        close_source()
        await close_database()


app.router.lifespan_context = lifespan
app.add_middleware(PrivateGuardianResponses)
