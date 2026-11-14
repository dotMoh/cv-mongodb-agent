"""Data-layer functions for the backend (Person B imports these).

    from memory_store import hybrid_search, heat_points, learn

All functions are async and return JSON-ready dicts (ObjectId -> str, datetime -> ISO).
"""
from datetime import datetime, timezone

from bson import ObjectId

from db import MEMORIES, VECTOR_INDEX, get_db
from embeddings import embed
from seed_data import PLANTS

EARTH_RADIUS_KM = 6378.1


def _clean(doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        if k == "embedding":
            continue
        if isinstance(v, ObjectId):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, dict):
            v = _clean(v)
        out[k] = v
        if k == "_id":
            out["id"] = v
    return out


async def hybrid_search(
    query: str,
    role: str = "planner",
    plant_id: str | None = None,
    radius_km: float = 50,
    min_temperature: float | None = None,
    categories: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """Semantic search over active memories the role may see, near the plant.

    $vectorSearch must be the first stage and can't do geo filtering, so
    role/status/temperature/category are pre-filters inside $vectorSearch and
    distance to the plant is a $geoWithin $match afterwards. Neighbouring units
    within radius_km count, so Unit 3 learns from Unit 1's mistakes.
    """
    filters: list[dict] = [
        {"metadata.status": {"$eq": "active"}},
        {"metadata.access_level": {"$in": [role]}},
    ]
    if min_temperature is not None:
        filters.append({"metadata.temperature_celsius": {"$gte": min_temperature}})
    if categories:
        filters.append({"category": {"$in": categories}})

    pipeline: list[dict] = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "embedding",
                "queryVector": embed(query),
                "numCandidates": max(100, limit * 20),
                "limit": limit * 4,  # over-fetch, the geo filter below trims it
                "filter": {"$and": filters},
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
    ]
    if plant_id and plant_id in PLANTS:
        lng, lat = PLANTS[plant_id]["coords"]
        pipeline.append({
            "$match": {"location": {"$geoWithin": {"$centerSphere": [[lng, lat], radius_km / EARTH_RADIUS_KM]}}}
        })
    pipeline += [{"$limit": limit}, {"$project": {"embedding": 0}}]

    cursor = await get_db()[MEMORIES].aggregate(pipeline)
    return [_clean(d) async for d in cursor]


async def heat_points(plant_id: str | None = None) -> list[list[float]]:
    """Past delays as Leaflet.heat points: [[lat, lng, intensity 0..1], ...]."""
    match: dict = {"metadata.status": "active", "delay_days": {"$gt": 0}}
    if plant_id:
        match["plant_id"] = plant_id
    cursor = get_db()[MEMORIES].find(match, {"location": 1, "delay_days": 1})
    docs = [d async for d in cursor]
    if not docs:
        return []
    max_delay = max(d["delay_days"] for d in docs)
    return [
        [d["location"]["coordinates"][1], d["location"]["coordinates"][0], round(d["delay_days"] / max_delay, 3)]
        for d in docs
    ]


async def learn(
    content: str,
    plant_id: str,
    corrects_id: str | None = None,
    category: str = "lesson",
    delay_days: int = 0,
    temperature_celsius: float | None = None,
    access_level: list[str] | None = None,
    expires_at: datetime | None = None,
) -> dict:
    """Store a new lesson. If corrects_id is given, that old memory is marked
    'corrected' so hybrid_search stops returning it."""
    plant = PLANTS.get(plant_id)
    doc = {
        "plant_id": plant_id,
        "title": content[:60],
        "category": category,
        "content": content,
        "delay_days": delay_days,
        "event_date": datetime.now(timezone.utc),
        "location": {"type": "Point", "coordinates": plant["coords"] if plant else [0.0, 0.0]},
        "embedding": embed(content),
        "metadata": {
            "access_level": access_level or ["planner", "safety_officer", "grid_operator"],
            "status": "active",
            "temperature_celsius": temperature_celsius,
            "expires_at": expires_at,
        },
    }
    coll = get_db()[MEMORIES]
    old_filter = None
    if corrects_id:
        # Accept an ObjectId string or a demo_key such as "mock-july-overheat".
        old_filter = {"_id": ObjectId(corrects_id)} if ObjectId.is_valid(corrects_id) else {"demo_key": corrects_id}
        doc["corrects_id"] = corrects_id
    result = await coll.insert_one(doc)
    if old_filter:
        await coll.update_one(
            old_filter,
            {"$set": {"metadata.status": "corrected", "corrected_by": result.inserted_id}},
        )
    doc["_id"] = result.inserted_id
    return _clean(doc)
