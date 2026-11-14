"""Generate fictional outage "lessons" for the demo.

All plants, units and events are made up. Output is deterministic (fixed seed)
so every teammate gets the same data.
"""
import random
from datetime import datetime, timedelta, timezone

# Fictional plants in southern Ontario. [lng, lat] order, as GeoJSON requires.
PLANTS = {
    # Agreed ids unit-1, unit-2, unit-3, unit-5; coords match the backend's mock data (unit-3 is the demo unit).
    "unit-3": {"name": "Unit 3", "coords": [-79.07, 43.81]},
    "unit-1": {"name": "Unit 1", "coords": [-78.72, 43.87]},
    "unit-2": {"name": "Unit 2", "coords": [-78.90, 43.85]},
    "unit-5": {"name": "Unit 5", "coords": [-79.07, 43.08]},
}

# (category, template, base delay days, hot weather?, roles)
TEMPLATES = [
    ("cooling", "{month} {year} {plant} outage slipped {d} days: cooling water intake temperature exceeded limits at {t}C, condenser work paused.", 6, True, ["planner", "safety_officer"]),
    ("cooling", "{month} {year} {plant}: heat wave at {t}C forced derate before outage start; maintenance window pushed {d} days.", 4, True, ["planner", "grid_operator"]),
    ("grid", "{month} {year} {plant}: grid operator refused outage start during peak demand ({t}C); rescheduled {d} days later.", 5, True, ["planner", "grid_operator"]),
    ("grid", "{month} {year} {plant}: transmission line maintenance on adjacent node overlapped outage, {d} day delay to reconnect.", 3, False, ["planner", "grid_operator"]),
    ("staffing", "{month} {year} {plant}: contractor crew shortage delayed turbine inspection {d} days.", 4, False, ["planner"]),
    ("parts", "{month} {year} {plant}: replacement valve arrived late from supplier, outage extended {d} days.", 7, False, ["planner"]),
    ("safety", "{month} {year} {plant}: radiation work permit backlog delayed steam generator inspection {d} days.", 3, False, ["planner", "safety_officer"]),
    ("safety", "{month} {year} {plant}: heat stress limits for workers at {t}C cut shift lengths, outage ran {d} days long.", 5, True, ["planner", "safety_officer"]),
    ("weather", "{month} {year} {plant}: ice storm blocked site access, {d} day delay to crane work.", 4, False, ["planner", "safety_officer"]),
    ("weather", "{month} {year} {plant}: high winds above crane limits halted lifts for {d} days.", 2, False, ["planner", "safety_officer"]),
]

HOT_MONTHS = [6, 7, 8]
COLD_MONTHS = [1, 2, 3, 4, 5, 9, 10, 11, 12]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


# Fixed demo memories, same text and ids as the backend's mock data, so the
# scripted demo behaves the same on Atlas. demo_key = backend mock id.
# (demo_key, plant_id, content, lng, lat, temp, delay_days, category, roles)
DEMO_ANCHORS = [
    ("mock-july-overheat", "unit-3", "July 2024 Unit 3 outage slipped 6 days: cooling water intake too warm, condenser could not reject heat", -79.07, 43.81, 31, 6, "cooling", ["planner", "safety_officer", "grid_operator"]),
    ("mock-2", "unit-3", "Unit 3 turbine inspection in spring 2023 finished 2 days early after pre-staging scaffolding the week before", -79.06, 43.80, 12, 0, "staffing", ["planner", "safety_officer", "grid_operator"]),
    ("mock-3", "unit-3", "Unit 3 main transformer replacement needs grid operator sign-off 14 days ahead; late notice cost 3 days in 2022", -79.08, 43.82, 18, 3, "grid", ["planner", "grid_operator"]),
    ("mock-4", "unit-3", "Steam generator eddy current testing on Unit 3 needs radiation work permits approved 10 days before outage start", -79.065, 43.805, 20, 0, "safety", ["planner", "safety_officer"]),
    ("mock-5", "unit-3", "August 2023 heat wave: grid operator refused Unit 3 outage window due to peak demand, outage moved to September", -79.075, 43.815, 33, 5, "grid", ["planner", "grid_operator"]),
    ("mock-6", "unit-1", "Unit 1 refuelling outage in October 2023 ran on schedule; crane certification done one month early", -78.72, 43.87, 10, 0, "parts", ["planner", "safety_officer", "grid_operator"]),
    ("mock-7", "unit-1", "Unit 1 feedwater pump seal failure found during startup added 4 days to the 2022 outage", -78.73, 43.875, 22, 4, "parts", ["planner", "safety_officer", "grid_operator"]),
    ("mock-8", "unit-1", "Winter 2024 ice on Unit 1 intake screens delayed restart by 2 days", -78.71, 43.868, -8, 2, "weather", ["planner", "safety_officer", "grid_operator"]),
]


def demo_anchor_docs() -> list[dict]:
    return [{
        "demo_key": key,
        "plant_id": plant_id,
        "title": content[:60],
        "category": category,
        "content": content,
        "delay_days": delay,
        "event_date": datetime(2024, 7, 15, tzinfo=timezone.utc),
        "location": {"type": "Point", "coordinates": [lng, lat]},
        "metadata": {"access_level": roles, "status": "active", "temperature_celsius": temp, "expires_at": None},
    } for key, plant_id, content, lng, lat, temp, delay, category, roles in DEMO_ANCHORS]


def generate_lessons(n: int = 60, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    plant_ids = list(PLANTS)
    lessons = demo_anchor_docs()
    for i in range(n):
        category, template, base_delay, hot, roles = TEMPLATES[i % len(TEMPLATES)]
        plant_id = plant_ids[(i // len(TEMPLATES)) % len(plant_ids)] if i % 3 else rng.choice(plant_ids)
        if hot and plant_id == "unit-3":
            # Keep Unit 3's hot-weather history to the demo anchors, so correcting
            # "mock-july-overheat" visibly changes the next plan.
            plant_id = "unit-1"
        plant = PLANTS[plant_id]
        year = rng.randint(2018, 2025)
        month = rng.choice(HOT_MONTHS if hot else COLD_MONTHS)
        if category == "weather" and "ice" in template:
            month = rng.choice([1, 2, 12])
        temp = rng.randint(29, 36) if hot else rng.randint(-15, 22)
        if "ice" in template:
            temp = rng.randint(-15, -2)
        delay = max(1, base_delay + rng.randint(-2, 3))
        lng, lat = plant["coords"]
        jitter = [round(lng + rng.uniform(-0.02, 0.02), 5), round(lat + rng.uniform(-0.02, 0.02), 5)]
        content = template.format(month=MONTH_NAMES[month - 1], year=year, plant=plant["name"], d=delay, t=temp)
        lessons.append({
            "plant_id": plant_id,
            "title": f"{plant['name']} {category} delay {MONTH_NAMES[month - 1]} {year}",
            "category": category,
            "content": content,
            "delay_days": delay,
            "event_date": datetime(year, month, rng.randint(1, 28), tzinfo=timezone.utc),
            "location": {"type": "Point", "coordinates": jitter},
            "metadata": {
                "access_level": roles,
                "status": "active",
                "temperature_celsius": temp,
                "expires_at": None,
            },
        })

    # Two temporary constraints that expire on their own (TTL demo).
    now = datetime.now(timezone.utc)
    for plant_id, text, days in [
        ("unit-3", "Temporary: east crane out of service for recertification, no heavy lifts at Unit 3.", 14),
        ("unit-5", "Temporary: grid operator restricts Unit 5 outages during the regional line upgrade.", 30),
    ]:
        lessons.append({
            "plant_id": plant_id,
            "title": "Temporary constraint",
            "category": "constraint",
            "content": text,
            "delay_days": 0,
            "event_date": now,
            "location": {"type": "Point", "coordinates": PLANTS[plant_id]["coords"]},
            "metadata": {
                "access_level": ["planner", "grid_operator", "safety_officer"],
                "status": "active",
                "temperature_celsius": None,
                "expires_at": now + timedelta(days=days),
            },
        })
    return lessons
