"""Shared async MongoDB connection (raw async PyMongo, no ODM).

Reads MONGODB_URI etc. from the environment or from .env in the repo root.
"""
import os
from pathlib import Path

from pymongo import AsyncMongoClient


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from the repo-root .env (or data/.env) without overriding
    variables already set. No extra dependency, works the same on Windows."""
    here = Path(__file__).resolve().parent
    for path in (here.parent / ".env", here / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


_load_dotenv()

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
