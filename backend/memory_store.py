"""Data layer. /plan and /learn only talk to this module.

Swap mock -> Atlas by setting DATA_SOURCE=mongo and MONGODB_URI. If Person A's
hybrid search query differs, replace MongoStore.search() only; keep the return shape:
a list of memory dicts with "id" (str) and "score" (float), no "embedding".
"""
from __future__ import annotations

import copy
import math
import uuid
from datetime import datetime, timezone

from config import COLLECTION, DATA_SOURCE, DB_NAME, MONGODB_URI, TOP_K, VECTOR_INDEX
from embeddings import embed

ALL_ROLES = ["planner", "safety_officer", "grid_operator"]


def normalize_role(role: str | None) -> str:
    return (role or "planner").strip().lower().replace(" ", "_")


def to_public(doc: dict) -> dict:
    """Strip the embedding and make the id a string so it is JSON-safe."""
    out = copy.deepcopy({k: v for k, v in doc.items() if k != "embedding" and k != "_id"})
    out["id"] = out["_id"] = str(doc.get("_id", doc.get("id")))
    meta = out.get("metadata") or {}
    for key in ("expires_at", "corrected_at", "created_at"):
        if isinstance(meta.get(key), datetime):
            meta[key] = meta[key].isoformat()
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out


def heat_from_docs(docs: list[dict]) -> list[list[float]]:
    """Leaflet.heat format: [lat, lng, intensity 0..1]. GeoJSON stores [lng, lat]."""
    points = []
    for d in docs:
        loc = d.get("location") or {}
        coords = loc.get("coordinates")
        if not coords or len(coords) != 2:
            continue
        meta = d.get("metadata") or {}
        if meta.get("severity") is not None:
            intensity = float(meta["severity"])
        else:
            temp = meta.get("temperature_celsius")
            intensity = 0.5 if temp is None else (float(temp) - 15) / 20
        points.append([coords[1], coords[0], round(max(0.2, min(1.0, intensity)), 2)])
    return points


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# ---------------------------------------------------------------- mock data
def _seed(plant, content, lng, lat, temp, roles=None, mid=None):
    return {
        "_id": mid,
        "plant_id": plant,
        "content": content,
        "location": {"type": "Point", "coordinates": [lng, lat]},
        "metadata": {
            "access_level": roles or ALL_ROLES,
            "status": "active",
            "temperature_celsius": temp,
            "expires_at": None,
        },
    }


MOCK_MEMORIES = [
    _seed("unit-3", "July 2024 Unit 3 outage slipped 6 days: cooling water intake too warm, condenser could not reject heat", -79.07, 43.81, 31, mid="mock-july-overheat"),
    _seed("unit-3", "Unit 3 turbine inspection in spring 2023 finished 2 days early after pre-staging scaffolding the week before", -79.06, 43.80, 12, mid="mock-2"),
    _seed("unit-3", "Unit 3 main transformer replacement needs grid operator sign-off 14 days ahead; late notice cost 3 days in 2022", -79.08, 43.82, 18, roles=["planner", "grid_operator"], mid="mock-3"),
    _seed("unit-3", "Steam generator eddy current testing on Unit 3 needs radiation work permits approved 10 days before outage start", -79.065, 43.805, 20, roles=["planner", "safety_officer"], mid="mock-4"),
    _seed("unit-3", "August 2023 heat wave: grid operator refused Unit 3 outage window due to peak demand, outage moved to September", -79.075, 43.815, 33, roles=["planner", "grid_operator"], mid="mock-5"),
    _seed("unit-1", "Unit 1 refuelling outage in October 2023 ran on schedule; crane certification done one month early", -78.72, 43.87, 10, mid="mock-6"),
    _seed("unit-1", "Unit 1 feedwater pump seal failure found during startup added 4 days to the 2022 outage", -78.73, 43.875, 22, mid="mock-7"),
    _seed("unit-1", "Winter 2024 ice on Unit 1 intake screens delayed restart by 2 days", -78.71, 43.868, -8, mid="mock-8"),
]


class MockStore:
    def __init__(self):
        self.docs = {d["_id"]: dict(copy.deepcopy(d), embedding=embed(d["content"])) for d in MOCK_MEMORIES}

    async def search(self, task, plant_id, role, k=TOP_K):
        q = embed(task)
        hits = []
        for d in self.docs.values():
            meta = d["metadata"]
            if d["plant_id"] != plant_id or meta["status"] != "active" or role not in meta["access_level"]:
                continue
            hits.append((_cosine(q, d["embedding"]), d))
        hits.sort(key=lambda h: h[0], reverse=True)
        return [dict(to_public(d), score=round(s, 3)) for s, d in hits[:k]]

    async def heat_points(self, plant_id):
        return heat_from_docs(list(self.docs.values()))

    async def get(self, mem_id):
        d = self.docs.get(mem_id)
        return to_public(d) if d else None

    async def insert(self, doc):
        doc["_id"] = uuid.uuid4().hex[:24]
        self.docs[doc["_id"]] = doc
        return doc["_id"]

    async def mark_corrected(self, mem_id, new_id):
        d = self.docs.get(mem_id)
        if not d:
            return False
        d["metadata"].update(status="corrected", corrected_by=new_id, corrected_at=datetime.now(timezone.utc))
        return True

    async def list(self, plant_id=None):
        return [to_public(d) for d in self.docs.values() if not plant_id or d["plant_id"] == plant_id]

    async def reset(self):
        self.__init__()


# ---------------------------------------------------------------- MongoDB Atlas
class MongoStore:
    def __init__(self):
        from pymongo import AsyncMongoClient

        self.client = AsyncMongoClient(MONGODB_URI)
        self.col = self.client[DB_NAME][COLLECTION]

    @staticmethod
    def _by_id(mem_id):
        """Match an ObjectId string, or a seed demo_key such as "mock-july-overheat"."""
        from bson import ObjectId

        if ObjectId.is_valid(mem_id):
            return {"_id": ObjectId(mem_id)}
        return {"$or": [{"_id": mem_id}, {"demo_key": mem_id}]}

    async def search(self, task, plant_id, role, k=TOP_K):
        # Hybrid search: $vectorSearch must be stage 1; geo is handled on the map, not here.
        # The vector index must declare plant_id, metadata.status and metadata.access_level as "filter" fields.
        pipeline = [
            {
                "$vectorSearch": {
                    "index": VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": embed(task),
                    "numCandidates": 100,
                    "limit": k,
                    "filter": {
                        "plant_id": plant_id,
                        "metadata.status": "active",
                        "metadata.access_level": role,
                    },
                }
            },
            {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
        ]
        cursor = await self.col.aggregate(pipeline)
        return [dict(to_public(d), score=round(d.get("score", 0), 3)) async for d in cursor]

    async def heat_points(self, plant_id):
        cursor = self.col.find({"location": {"$exists": True}}, {"embedding": 0}).limit(500)
        return heat_from_docs([d async for d in cursor])

    async def get(self, mem_id):
        d = await self.col.find_one(self._by_id(mem_id), {"embedding": 0})
        return to_public(d) if d else None

    async def insert(self, doc):
        res = await self.col.insert_one(doc)
        return str(res.inserted_id)

    async def mark_corrected(self, mem_id, new_id):
        res = await self.col.update_one(
            self._by_id(mem_id),
            {"$set": {"metadata.status": "corrected", "metadata.corrected_by": new_id,
                      "metadata.corrected_at": datetime.now(timezone.utc)}},
        )
        return res.matched_count == 1

    async def list(self, plant_id=None):
        q = {"plant_id": plant_id} if plant_id else {}
        cursor = self.col.find(q, {"embedding": 0}).limit(200)
        return [to_public(d) async for d in cursor]

    async def reset(self):
        raise NotImplementedError("reset is mock-only; reseed with Person A's script")


def make_store():
    return MongoStore() if DATA_SOURCE == "mongo" else MockStore()
