"""/plan and /learn must return exactly what frontend/README.md and app.js read."""
from datetime import date


def test_plan_top_level_keys(plan):
    body = plan()
    for key in ("schedule", "memories_used", "heat_points"):
        assert key in body, f"frontend needs '{key}'"
    assert isinstance(body["schedule"], list) and body["schedule"]


def test_schedule_steps(plan):
    for s in plan()["schedule"]:
        assert isinstance(s["step"], str) and s["step"]
        start, end = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
        assert start <= end
        assert isinstance(s["note"], str)
        assert isinstance(s["shifted"], bool)


def test_memories_used_shape(plan):
    mems = plan()["memories_used"]
    assert mems, "demo task should recall at least one memory"
    for m in mems:
        assert isinstance(m["_id"], str), "_id must be a string, not ObjectId"
        assert isinstance(m["content"], str)
        assert isinstance(m["score"], (int, float))
        assert "embedding" not in m, "never send 384 floats to the browser"
        assert m["metadata"]["status"] in ("active", "corrected")
        loc = m.get("location")
        if loc:
            assert loc["type"] == "Point" and len(loc["coordinates"]) == 2


def test_heat_points_are_lat_first(client, plan):
    pts = plan()["heat_points"]
    assert pts
    for p in pts:
        lat, lng, w = p
        assert -90 <= lat <= 90 and -180 <= lng <= 180
        assert 0 <= w <= 1
    # GeoJSON is [lng, lat]; Leaflet.heat is [lat, lng]. Check the flip really happened.
    mem = client.get("/memories").json()[0]
    g_lng, g_lat = mem["location"]["coordinates"]
    assert [g_lat, g_lng] in [p[:2] for p in pts]


def test_learn_response(client):
    r = client.post("/learn", json={"content": "Test lesson", "plant_id": "unit-3"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and isinstance(body["id"], str)


def test_plan_accepts_display_role_names(plan):
    assert plan(role="Safety Officer")["schedule"]
