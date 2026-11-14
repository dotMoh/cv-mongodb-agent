"""Create all indexes on the memories collection.

- Atlas Vector Search index (embedding + filter fields)
- TTL index on metadata.expires_at (temporary constraints delete themselves)
- 2dsphere index on location (geo queries, heatmap)

Run: python create_indexes.py
"""
import asyncio
import time

from pymongo import ASCENDING, GEOSPHERE
from pymongo.operations import SearchIndexModel

from db import EMBED_DIMS, MEMORIES, VECTOR_INDEX, close_client, get_db

VECTOR_INDEX_DEFINITION = {
    "fields": [
        {"type": "vector", "path": "embedding", "numDimensions": EMBED_DIMS, "similarity": "cosine"},
        {"type": "filter", "path": "plant_id"},
        {"type": "filter", "path": "category"},
        {"type": "filter", "path": "metadata.access_level"},
        {"type": "filter", "path": "metadata.status"},
        {"type": "filter", "path": "metadata.temperature_celsius"},
    ]
}


async def create_indexes(wait: bool = True) -> None:
    coll = get_db()[MEMORIES]

    # TTL: expireAfterSeconds=0 means "delete at the time stored in the field".
    # Docs with expires_at = null are never deleted.
    await coll.create_index([("metadata.expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at")
    await coll.create_index([("location", GEOSPHERE)], name="location_2dsphere")
    await coll.create_index([("plant_id", ASCENDING), ("metadata.status", ASCENDING)], name="plant_status")
    print("Created TTL, 2dsphere and plant/status indexes.")

    existing = [ix async for ix in await coll.list_search_indexes()]
    if any(ix["name"] == VECTOR_INDEX for ix in existing):
        print(f"Vector index '{VECTOR_INDEX}' already exists, updating definition.")
        await coll.update_search_index(VECTOR_INDEX, VECTOR_INDEX_DEFINITION)
    else:
        await coll.create_search_index(
            SearchIndexModel(definition=VECTOR_INDEX_DEFINITION, name=VECTOR_INDEX, type="vectorSearch")
        )
        print(f"Requested vector index '{VECTOR_INDEX}'.")

    if wait:
        print("Waiting for the vector index to become queryable (usually under a minute)...")
        start = time.time()
        while time.time() - start < 300:
            indexes = [ix async for ix in await coll.list_search_indexes(VECTOR_INDEX)]
            if indexes and indexes[0].get("queryable"):
                print("Vector index is ready.")
                return
            await asyncio.sleep(5)
        print("Still building after 5 minutes. Check Atlas > Search & Vector Search.")


if __name__ == "__main__":
    async def main():
        try:
            await create_indexes()
        finally:
            await close_client()

    asyncio.run(main())
