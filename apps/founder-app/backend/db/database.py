"""MongoDB database connection and utilities."""
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, DB_NAME

# MongoDB client
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


def get_database():
    """Get database instance."""
    return db


async def close_database():
    """Close database connection."""
    client.close()
