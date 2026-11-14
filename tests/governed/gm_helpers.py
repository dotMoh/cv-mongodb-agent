"""Shared helpers for the governed-memory tests."""
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

PLANNER, CONTRACTOR, LEAD = "planner_07", "contractor_02", "lead_01"

NEW_LESSON = {
    "job_type": "Valve overhaul",
    "unit": "U2",
    "equipment": "MV-210",
    "title": "Valve seat lapping kit missing from tool crib",
    "issue": "Lapping kit was out for calibration; overhaul start slipped one shift.",
    "impact": "0.5 day delay",
    "recommendation": "Check calibration due dates of lapping kits a week before the outage.",
    "category": "tooling",
    "delay_days": 0.5,
    "sensitivity": "internal",
}


def audit_latest(governance, **match):
    """Newest audit entry matching all given fields, or None."""
    for e in governance.audit_log(limit=500):
        if all(e.get(k) == v for k, v in match.items()):
            return e
    return None


def task(tid, name, start, hours, unit="U4", predecessors=(), critical=False):
    return {"id": tid, "name": name, "start": start, "end": start + timedelta(hours=hours),
            "duration_hours": float(hours), "unit": unit, "contractor": "Acme", "equipment": None,
            "discipline": "Mechanical", "predecessors": list(predecessors), "critical": critical,
            "milestone": False, "permit": None, "source_row": None}


DAY0 = datetime(2027, 4, 12, 6, 0)
