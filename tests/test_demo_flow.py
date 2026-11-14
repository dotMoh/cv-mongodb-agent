"""The 60-second demo, end to end. If this goes red, the pitch is broken."""
from datetime import date

from conftest import DEMO_MEMORY, FIX_LESSON


def first_start(body):
    return min(date.fromisoformat(s["start"]) for s in body["schedule"] if "Notify" not in s["step"])


def test_demo_moment(client, plan):
    # 1. Memory changes the plan: July outage moves to June because of the overheating lesson.
    before = plan()
    assert DEMO_MEMORY in [m["_id"] for m in before["memories_used"]]
    assert first_start(before).month == 6, before["summary"]
    assert any(s["shifted"] for s in before["schedule"])
    assert any(a["memory_id"] == DEMO_MEMORY for a in before["adjustments"])

    # 2. Teach a correction.
    learned = client.post("/learn", json={"content": FIX_LESSON, "plant_id": "unit-3", "corrects_id": DEMO_MEMORY}).json()
    assert learned["corrected_id"] == DEMO_MEMORY

    # 3. Next plan: back in July, old memory gone, new lesson recalled.
    after = plan()
    used = [m["_id"] for m in after["memories_used"]]
    assert DEMO_MEMORY not in used
    assert learned["id"] in used
    assert first_start(after).month == 7, after["summary"]


def test_demo_is_repeatable_after_reset(client, plan):
    client.post("/learn", json={"content": FIX_LESSON, "plant_id": "unit-3", "corrects_id": DEMO_MEMORY})
    client.post("/reset")
    assert first_start(plan()).month == 6
