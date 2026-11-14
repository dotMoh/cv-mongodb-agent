"""Endpoint behaviour: filters, corrections, errors."""
from conftest import DEMO_MEMORY


def ids(body):
    return [m["_id"] for m in body["memories_used"]]


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] and body["data_source"] == "mock"


def test_plant_filter(plan):
    for m in plan(plant_id="unit-1")["memories_used"]:
        assert m["plant_id"] == "unit-1"


def test_role_filter(plan):
    # mock-3 is planner + grid_operator only; a safety officer must never see it.
    assert "mock-3" not in ids(plan(task="transformer replacement grid sign-off", role="safety_officer"))
    assert "mock-3" in ids(plan(task="transformer replacement grid sign-off", role="planner"))


def test_learn_unknown_correction_is_404(client):
    r = client.post("/learn", json={"content": "x", "plant_id": "unit-3", "corrects_id": "does-not-exist"})
    assert r.status_code == 404


def test_learn_marks_old_memory_corrected(client):
    r = client.post("/learn", json={"content": "Fixed it", "plant_id": "unit-3", "corrects_id": DEMO_MEMORY}).json()
    assert r["corrected_id"] == DEMO_MEMORY
    mems = {m["_id"]: m for m in client.get("/memories", params={"plant_id": "unit-3"}).json()}
    assert mems[DEMO_MEMORY]["metadata"]["status"] == "corrected"
    assert mems[r["id"]]["metadata"]["status"] == "active"
    assert mems[r["id"]]["location"] == mems[DEMO_MEMORY]["location"], "location copied from the corrected memory"


def test_learn_ttl_sets_expiry(client):
    r = client.post("/learn", json={"content": "Crane down", "plant_id": "unit-3", "ttl_days": 7}).json()
    mem = next(m for m in client.get("/memories").json() if m["_id"] == r["id"])
    assert mem["metadata"]["expires_at"]


def test_reset_restores_seed(client):
    client.post("/learn", json={"content": "Fixed it", "plant_id": "unit-3", "corrects_id": DEMO_MEMORY})
    client.post("/reset")
    mems = {m["_id"]: m for m in client.get("/memories").json()}
    assert mems[DEMO_MEMORY]["metadata"]["status"] == "active"
    assert len(mems) == 8
