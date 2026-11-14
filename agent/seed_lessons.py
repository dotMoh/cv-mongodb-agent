"""Seed OPEX lessons for the mock store (the data thread can reuse these for Atlas).
Each tuple: lesson_id, unit, equipment, job_type, category, delay_days, sensitivity, title, issue, recommendation
"""
from __future__ import annotations

from datetime import datetime

SEED = [
    ("L-0001", "U2", "BFP-2A", "Boiler feed pump overhaul", "parts", 1.5, "public",
     "Wrong seal kit revision delayed BFP overhaul",
     "Seal kit delivered was the wrong revision; pump reassembly waited for the correct parts.",
     "Kit and verify spare parts against the work order revision before the outage."),
    ("L-0002", "U1", "TV-101", "Turbine valve inspection", "access", 0.5, "public",
     "Scaffold not erected before valve inspection shift",
     "Scaffold erection overran into the inspection shift; crew stood down for half a day.",
     "Complete and tag scaffold one shift before access-dependent inspections."),
    ("L-0003", "U3", "HX-301", "Heat exchanger isolation", "permits", 0.75, "internal",
     "HX isolation permit approved late on night shift",
     "Work permit for heat exchanger isolation was approved after shift change, delaying isolation.",
     "Pre-approve isolation permits on the day shift before the outage starts."),
    ("L-0004", "U2", "HX-201", "Heat exchanger inspection", "resources", 1.0, "restricted",
     "NDT contractor under-resourced on night shift",
     "Contractor NDT crew was short two technicians on night shift; inspection ran 40% long.",
     "Confirm contractor night-shift headcount in writing 48 hours before start."),
    ("L-0005", "U4", "COND-4", "Condenser waterbox cleaning", "weather", 1.0, "public",
     "Warm intake water slowed condenser cleaning",
     "High intake water temperature limited waterbox entry time and slowed cleaning.",
     "Schedule waterbox work for cooler periods or add contingency in summer outages."),
    ("L-0006", "U1", "HX-101", "Heat exchanger tube inspection", "rework", 1.0, "internal",
     "Missing verification stage caused HX tube re-inspection",
     "Tube inspection results were not verified before plugging; several tubes had to be re-inspected.",
     "Add a verification hold point between tube inspection and tube plugging."),
    ("L-0007", "U3", "HX-301", "Heat exchanger tube inspection", "tooling", 2.5, "internal",
     "Tooling access delayed U3 heat exchanger tube inspection",
     "Eddy current inspection tooling was not on site at isolation; heat exchanger tube inspection start slipped 2.5 days.",
     "Confirm inspection tooling is on site and tested before isolation; prepare tooling the shift before."),
    ("L-0008", "U2", "HX-201", "Heat exchanger tube inspection", "tooling", 1.5, "public",
     "Expired probe calibration paused HX inspection",
     "Eddy current probe calibration certificate had expired; heat exchanger inspection paused until a replacement probe arrived.",
     "Check tooling calibration certificates during tooling preparation."),
    ("L-0009", "U3", "CRANE-1", "Crane lift", "resources", 1.0, "internal",
     "Crane double-booked with turbine work",
     "Polar crane was booked for turbine lifts at the same time as pump removal.",
     "Resolve crane bookings across all work packages before the schedule is frozen."),
    ("L-0010", "U4", "BUS-4", "Electrical isolation", "permits", 0.5, "public",
     "Lockout verification slowed at midnight shift change",
     "Electrical isolation lockout verification was repeated across the midnight shift handover.",
     "Avoid scheduling isolation verification across shift handovers."),
    ("L-0011", "U1", "V-115", "Valve repacking", "parts", 0.5, "public",
     "Valve packing spares not kitted",
     "Packing sets were not kitted; fitters waited for stores.",
     "Kit valve packing spares per valve before the outage."),
    ("L-0012", "U3", "PA-GATE", "Contractor site access", "access", 0.5, "restricted",
     "Protected area badge delays for contractors",
     "Contractor badges were not activated for the protected area on day one.",
     "Activate contractor protected-area access 72 hours before mobilization."),
    ("L-0013", "U4", "HX-401", "Heat exchanger tube inspection", "sequencing", 2.0, "restricted",
     "Regulator hold point extended HX inspection",
     "A regulatory witness hold point on heat exchanger tube inspection was not scheduled, adding two days.",
     "Book regulator witness points in the schedule as milestones before the outage."),
    ("L-0014", "U2", "GEN-2", "Generator inspection", "sequencing", 1.0, "internal",
     "Generator inspection overlapped hydro test",
     "Generator inspection overlapped the hydrostatic test window; both had to be resequenced.",
     "Do not overlap generator inspection with hydro testing in the same area."),
    ("L-0015", "U1", "P-102", "Pump alignment", "rework", 0.75, "public",
     "Pump alignment rework after coupling change",
     "Alignment was done before the coupling was replaced and had to be repeated.",
     "Sequence coupling replacement before final alignment."),
    ("L-0016", "U3", "HX-302", "Tube plugging", "rework", 0.5, "internal",
     "Tube plugging rework after missed inspection data",
     "Plugging crew started before the inspection report was issued and had to redo two tubes.",
     "Gate tube plugging on an issued inspection report."),
]

ALL_ROLES = ["planner", "contractor", "lead"]


def seed_docs() -> list[dict]:
    t0 = datetime(2026, 9, 1, 9, 0, tzinfo=None)
    docs = []
    for (lid, unit, equip, job, cat, delay, sens, title, issue, rec) in SEED:
        docs.append({
            "lesson_id": lid, "version": 1, "job_type": job, "unit": unit, "equipment": equip,
            "title": title, "issue": issue, "impact": f"{delay:g} day delay", "recommendation": rec,
            "category": cat, "delay_days": delay, "sensitivity": sens,
            "allowed_roles": ["lead"] if sens == "restricted" else list(ALL_ROLES),
            "status": "approved", "source": "seed",
            "evidence": [{"type": "outage_record", "ref": f"2025-{unit}-spring", "detail": issue}],
            "outage_id": f"2025-{unit}-spring", "created_by": "lead_01", "created_at": t0,
            "approved_by": "lead_01", "approved_at": t0, "expires_at": None,
            "supersedes": None, "superseded_by": None, "change_reason": None,
        })
    # History example: L-0006 had a v1 that was corrected.
    v1 = dict(docs[5], version=1, status="superseded", impact="0.5 day delay", delay_days=0.5,
              issue="Some tubes were re-inspected.", recommendation="Review inspection data.")
    docs[5].update(version=2, change_reason="Delay measured from outage records was 1 day, not 0.5.",
                   created_at=datetime(2026, 10, 1, 9, 0, tzinfo=None))
    docs.insert(5, v1)
    return docs


def embed_text(d: dict) -> str:
    return f"{d.get('job_type', '')}. {d.get('unit', '')} {d.get('equipment', '')}. {d.get('title', '')}. {d.get('issue', '')}. {d.get('recommendation', '')}"
