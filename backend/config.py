"""Configuration module for the Founder Niche Discovery Platform."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Database
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'founder_niche_db')

# CORS
CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')

# LLM Configuration
# Use user's own Gemini key if provided, otherwise fall back to Emergent key
GOOGLE_GEMINI_API_KEY = os.environ.get('GOOGLE_GEMINI_API_KEY', '')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

def get_llm_api_key():
    """Get the appropriate LLM API key."""
    if GOOGLE_GEMINI_API_KEY:
        return GOOGLE_GEMINI_API_KEY
    return EMERGENT_LLM_KEY

def get_llm_provider():
    """Get the LLM provider based on which key is available."""
    if GOOGLE_GEMINI_API_KEY:
        return "gemini"
    return "gemini"  # Using Emergent key with Gemini model



