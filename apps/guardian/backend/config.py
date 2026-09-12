"""Cost Guardian configuration.

Guardian is a standalone service. It shares no code and no process with the
applications it monitors. It reads Langfuse or accepts scoped terminal events in
direct mode, with its own database, authentication and port.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# --- Database -----------------------------------------------------------------
# Same cluster as the monitored app is fine, but a separate database: Guardian owns
# its incidents/metrics/cursor and must never be coupled to a monitored app's schema.
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("GUARDIAN_DB_NAME", "cost_guardian")

# --- Server -------------------------------------------------------------------
# 8001 so Guardian and a monitored app can run side by side on one machine.
PORT = int(os.environ.get("GUARDIAN_PORT", "8001"))
CORS_ORIGINS = os.environ.get("GUARDIAN_CORS_ORIGINS", "http://localhost:3001").split(",")

# --- Auth ---------------------------------------------------------------------
# Legacy local-development access. identity/settings.py owns named OIDC access;
# capture/settings.py owns source mode. Direct intake uses separate write-only
# credentials and requires an isolated named project. See docs/CAPTURE.md.
GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "")

# --- Worker -------------------------------------------------------------------
# Development polling default. Source quotas depend on endpoint, plan and
# organization; the worker and dashboard both consume that allowance. Verify the
# deployed source limits and ingestion delay before changing this interval.
POLL_INTERVAL_SECONDS = int(os.environ.get("GUARDIAN_POLL_INTERVAL_SECONDS", "60"))
# Stable single-connection identity; retain during credential rotation.
GUARDIAN_CONNECTION_ID = os.environ.get("GUARDIAN_CONNECTION_ID", "primary")

# --- Langfuse (the telemetry source Guardian reads) ----------------------------
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
LANGFUSE_READ_API = os.environ.get("LANGFUSE_READ_API", "v2")
