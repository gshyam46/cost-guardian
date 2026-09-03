# observability/dd_config.py
import os
from ddtrace import patch_all, tracer

# Make sure all integrations (FastAPI, httpx, LiteLLM, etc.) are patched
patch_all()

# Set service/env if not already provided via env vars
if not os.getenv("DD_SERVICE"):
    os.environ["DD_SERVICE"] = "founderpath"

if not os.getenv("DD_ENV"):
    os.environ["DD_ENV"] = "dev"

# Minimal sanity: make sure LLM Observability has an app name
if not os.getenv("DD_LLMOBS_ML_APP"):
    os.environ["DD_LLMOBS_ML_APP"] = "founder-niche-ai"

# Optional: set some global tags
tracer.set_tags({
    "project": "founderpath",
    "component": "backend",
})
