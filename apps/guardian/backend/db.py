"""Guardian owns its incident, metric, observation ledger, state and identity collections."""
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from config import DB_NAME, MONGO_URL

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def close_database() -> None:
    client.close()
