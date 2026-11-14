"""Run the backend in its fast, deterministic mode: in-memory data, rule planner, hash embeddings.

These env vars must be set before backend modules are imported (config.py reads them at import).
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATA_SOURCE"] = "mock"
os.environ["LLM_MODE"] = "fallback"
os.environ["EMBEDDINGS"] = "hash"
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  (backend/main.py)

DEMO_TASK = "Plan July maintenance outage for Unit 3"
DEMO_MEMORY = "mock-july-overheat"
FIX_LESSON = "Unit 3 July maintenance outage update: intake chiller retrofit finished in 2025, so July cooling water temperatures and heat waves no longer delay Unit 3 outages."


@pytest.fixture
def client():
    c = TestClient(main.app)
    c.post("/reset")  # every test starts from the seed memories
    yield c


@pytest.fixture
def plan(client):
    def _plan(task=DEMO_TASK, role="planner", plant_id="unit-3"):
        r = client.post("/plan", json={"task": task, "role": role, "plant_id": plant_id})
        assert r.status_code == 200, r.text
        return r.json()
    return _plan
