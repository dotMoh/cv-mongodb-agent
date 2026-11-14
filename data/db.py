"""Shared async MongoDB connection (raw async PyMongo, no ODM).

Set MONGODB_URI (Atlas connection string) and optionally MONGODB_DB.
"""
import os

from pymongo import AsyncMongoClient

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", os.environ.get("MONGODB_DB", "outage_agent"))

MEMORIES = "memories"
VECTOR_INDEX = os.environ.get("VECTOR_INDEX", "vector_index")  # agreed with backend
MEMORIES = os.environ.get("COLLECTION", MEMORIES)
EMBED_DIMS = 384  # all-MiniLM-L6-v2

_client: AsyncMongoClient | None = None


def get_client() -> AsyncMongoClient:
    global _client
    if _client is None:
        _client = AsyncMongoClient(MONGODB_URI)
    return _client


def get_db():
    return get_client()[DB_NAME]


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
