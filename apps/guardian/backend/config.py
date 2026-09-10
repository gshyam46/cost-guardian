"""Cost Guardian configuration.

Guardian is a standalone service. It shares no code and no process with the
applications it monitors -- it only reads their telemetry out of Langfuse. That means
it needs its own database handle, its own auth, and its own port.
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
# Guardian used to piggyback on the monitored app's session cookies, which only worked
# because they shared a process. As its own service it needs its own credential. A
# single static API key is deliberate for the MVP: Guardian is currently single-tenant
# ("watch my own stack"). Real multi-tenancy needs per-project keys -- tracked in
# docs/PHASES.md, not forgotten.
GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "")

# --- Worker -------------------------------------------------------------------
# How often the worker asks Langfuse for new generations. 60s is the sane default for
# a real deployment; a live demo wants it lower so the dashboard reacts while someone
# is still watching it.
#
# There is a hard floor, though, and it is not ingestion lag: Langfuse Cloud allows 15
# API requests/minute for the entire project, and the dashboard's live views draw on
# the same allowance. A worker polling every 15s can spend half that budget on its own
# and push the dashboard into 429s. 30s is the lowest value that leaves room for both.
POLL_INTERVAL_SECONDS = int(os.environ.get("GUARDIAN_POLL_INTERVAL_SECONDS", "60"))

# --- Langfuse (the telemetry source Guardian reads) ----------------------------
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
