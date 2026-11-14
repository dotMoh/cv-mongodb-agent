"""Outage Planning Agent API. Run: uvicorn main:app --reload --port 8000"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from embeddings import embed, mode as embed_mode
from memory_store import ALL_ROLES, make_store, normalize_role
from planner import make_plan

app = FastAPI(title="Outage Planning Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store = make_store()


class PlanRequest(BaseModel):
    task: str = Field(..., examples=["Plan the July maintenance outage for Unit 3"])
    role: str = "planner"
    plant_id: str = "unit-3"


class LearnRequest(BaseModel):
    content: str = Field(..., examples=["Unit 3 July maintenance outage update: intake chiller retrofit finished in 2025, so July cooling water temperatures and heat waves no longer delay Unit 3 outages."])
    plant_id: str = "unit-3"
    corrects_id: str | None = None
    access_level: list[str] | None = None
    temperature_celsius: float | None = None
    location: dict | None = None  # GeoJSON Point; copied from the corrected memory if omitted
    ttl_days: int | None = None   # sets metadata.expires_at for the TTL index


@app.get("/health")
async def health():
    return {"ok": True, "data_source": config.DATA_SOURCE, "llm_mode": config.LLM_MODE,
            "ollama_model": config.OLLAMA_MODEL, "embeddings": embed_mode()}


@app.post("/plan")
async def plan(req: PlanRequest):
    t0 = time.perf_counter()
    role = normalize_role(req.role)
    memories = await store.search(req.task, req.plant_id, role)
    result, source, err = await make_plan(req.task, role, memories)
    return {
        "schedule": result["schedule"],
        "memories_used": memories,
        "heat_points": await store.heat_points(req.plant_id),
        "summary": result["summary"],
        "adjustments": result.get("adjustments", []),
        "source": source,
        "llm_error": err,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


@app.post("/learn")
async def learn(req: LearnRequest):
    old = None
    if req.corrects_id:
        old = await store.get(req.corrects_id)
        if not old:
            raise HTTPException(404, f"memory {req.corrects_id} not found")
    now = datetime.now(timezone.utc)
    doc = {
        "plant_id": req.plant_id,
        "content": req.content,
        "embedding": embed(req.content),
        "location": req.location or (old or {}).get("location"),
        "metadata": {
            "access_level": [normalize_role(r) for r in req.access_level] if req.access_level else ALL_ROLES,
            "status": "active",
            "temperature_celsius": req.temperature_celsius,
            "expires_at": now + timedelta(days=req.ttl_days) if req.ttl_days else None,
            "corrects_id": req.corrects_id,
            "created_at": now,
        },
    }
    if doc["location"] is None:
        del doc["location"]
    new_id = await store.insert(doc)
    corrected = await store.mark_corrected(req.corrects_id, new_id) if req.corrects_id else False
    return {"ok": True, "id": new_id, "corrected_id": req.corrects_id if corrected else None, "status": "active"}


@app.get("/memories")
async def memories(plant_id: str | None = Query(None)):
    """Debug view: every memory (active and corrected) without embeddings."""
    return await store.list(plant_id)


@app.post("/reset")
async def reset():
    """Mock mode only: restore the seed memories so the demo can be rerun."""
    await store.reset()
    return {"ok": True}
