"""Guardian's own MongoDB connection.

Separate from any monitored application's database layer -- Guardian owns the
`guardian_incidents`, `guardian_metrics` and `guardian_state` collections and nothing
else.
"""
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from config import DB_NAME, MONGO_URL

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def close_database() -> None:
    client.close()
