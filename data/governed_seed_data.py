"""Seed lessons for Track 2 (Governed Memory), matching
plan/governed-memory-contracts.md. All events, contractors and people are fictional.
Units U1 to U4; U4 is the upcoming outage in samples/u4_outage_24h.csv.
"""
from datetime import datetime, timedelta, timezone

USERS = {"planner_07": "planner", "contractor_02": "contractor", "lead_01": "lead"}
ALL_ROLES = ["planner", "contractor", "lead"]

# (lesson_id, job_type, unit, equipment, category, sensitivity, delay_days,
#  planned_h, actual_h, outage_id, title, issue, recommendation)
APPROVED = [
    ("L-0001", "Heat exchanger inspection", "U2", "HX-201", "access", "public", 1.0, 8, 32, "2024-U2-spring",
     "Scaffold blocked lower tube-sheet access",
     "The scaffold platform did not reach the lower tube-sheet rows, so it was rebuilt mid-inspection.",
     "Have the inspection lead sign off the scaffold drawing before erection."),
    ("L-0002", "Heat exchanger inspection", "U1", "HX-101", "tooling", "public", 0.5, 8, 20, "2023-U1-fall",
     "Eddy current probe calibration left to night shift",
     "Probe calibration was left for the incoming night shift, which had no qualified technician. Inspection paused one shift.",
     "Complete probe calibration in the same shift as tooling preparation."),
    ("L-0003", "Heat exchanger inspection", "U2", "HX-201", "tooling", "internal", 1.5, 8, 44, "2024-U2-spring",
     "Wrong probe size shipped for HX tube inspection",
     "Probes for the wrong tube diameter were shipped. Correct probes arrived 1.5 days later.",
     "Check probe size against the unit's tube drawings when tooling is booked."),
    ("L-0004", "Tube plugging", "U3", "HX-301", "sequencing", "internal", 0.5, 6, 18, "2025-U3-fall",
     "More tubes plugged than planned",
     "Inspection found 3 percent of tubes needing plugs against 1 percent planned; plugging took three times as long.",
     "Size plugging contingency from the last two inspections, not one."),
    ("L-0005", "Scaffolding erection", "U3", "HX bay scaffold", "access", "public", 0.4, 12, 20, "2025-U3-fall",
     "Scaffold erection overlapped drain and vent",
     "Scaffold erection in the heat exchanger bay took 20 hours instead of 12 because of congestion with the drain and vent crew.",
     "Do not overlap scaffold erection with drain and vent in the same bay."),
    ("L-0006", "Isolation and permits", "U3", "Electrical isolation", "permits", "public", 0.2, 4, 8, "2025-U3-fall",
     "Isolation permits issued four hours late",
     "Work permits for the heat exchanger bay were issued late because the isolation list was finalised on the day.",
     "Freeze and pre-walk the isolation list 48 hours before shutdown."),
    # The demo lesson. Seeded as v2 (v1 superseded) so history shows a correction.
    ("L-0007", "Heat exchanger inspection", "U3", "HX-301", "tooling", "internal", 2.5, 8, 68, "2025-U3-fall",
     "Eddy current probe tooling not on site delayed U3 HX tube inspection",
     "Eddy current probe tooling was not on site at isolation, so the U3 heat exchanger (HX) tube inspection start slipped 2.5 days and hit the critical path.",
     "Complete tooling preparation and confirm eddy current probes are on site and calibrated before isolation; add a tooling verification milestone before HX tube inspection."),
    ("L-0008", "Crane lift", "U2", "Turbine hall crane", "resources", "public", 0.4, 4, 14, "2024-U2-spring",
     "Crane double-booked between units",
     "The turbine hall crane was booked for a U2 pump motor lift and a U1 valve lift in the same window. One lift waited 10 hours.",
     "Book the crane in one cross-unit schedule and flag overlapping lifts."),
    ("L-0009", "Valve overhaul", "U1", "MV-101", "parts", "public", 1.5, 12, 48, "2023-U1-fall",
     "Valve seat spares arrived late",
     "Replacement valve seats were ordered after the valve was opened. The overhaul waited 1.5 days for spares.",
     "Pre-order seats and gaskets for every valve overhaul in scope."),
    ("L-0010", "Channel head closure", "U3", "HX-301", "rework", "public", 0.25, 6, 12, "2025-U3-fall",
     "Midnight handover caused channel head re-torque",
     "Channel head closure crossed midnight. The torque record was not handed over and the night shift re-torqued all bolts.",
     "Avoid starting closure within two hours of a shift change, or use a signed torque sheet."),
    ("L-0011", "Hydrotest", "U2", "HX-201", "rework", "public", 0.5, 4, 16, "2024-U2-spring",
     "Hydrotest failed after tube plugging",
     "A tube plug leaked during hydrotest and the test was repeated after re-plugging.",
     "Verify plug seating before hydrotest."),
    ("L-0012", "Heat exchanger inspection", "U3", "HX-301", "resources", "restricted", 1.0, 8, 32, "2025-U3-fall",
     "Inspection contractor under-resourced",
     "Northline Inspection supplied two technicians instead of the contracted four. Commercial claim CC-2025-031 raised.",
     "Confirm named technicians 7 days before outage; apply contract clause 12."),
    ("L-0013", "Isolation and permits", "U2", "Electrical isolation", "permits", "restricted", 0.3, 4, 11, "2024-U2-spring",
     "Wrong breaker tagged during isolation",
     "A wrong breaker was tagged during U2 isolation. Found at verification, no injury. Investigation ongoing.",
     "Independently verify every isolation point."),
    ("L-0014", "Crane lift", "U3", "Turbine hall crane", "resources", "internal", 0.5, 4, 16, "2025-U3-fall",
     "Crane operator certification lapsed",
     "The Apex Access crane operator's certification had lapsed; the lift waited for a certified operator.",
     "Check contractor certifications at gate induction."),
    ("L-0015", "Unit shutdown", "U1", "Reactor unit", "sequencing", "public", 0.2, 6, 10, "2023-U1-fall",
     "Cooldown slower than planned",
     "Cooldown to work temperature took 4 hours longer than the plan assumed.",
     "Use the cooldown curve from the last outage, not the design value."),
    ("L-0016", "Drain and vent", "U2", "HX-201", "sequencing", "public", 0.15, 6, 10, "2024-U2-spring",
     "Drain and vent slowed by blocked vent valve",
     "A vent valve was seized, slowing draining by 4 hours.",
     "Stroke-test vent valves in the week before the outage."),
    ("L-0017", "Pump motor replacement", "U3", "P-302 motor", "parts", "public", 1.0, 10, 34, "2025-U3-fall",
     "Motor coupling did not fit",
     "The replacement motor shipped with a different coupling. A new coupling was machined on site.",
     "Check coupling dimensions on receipt, before the outage."),
    ("L-0018", "Valve overhaul", "U4", "MV-401", "parts", "public", 0.5, 12, 24, "2022-U4-spring",
     "Valve actuator spare missing from stores",
     "The stores record showed an actuator spare that was not on the shelf.",
     "Physically check critical spares two weeks before the outage."),
    ("L-0019", "Heat exchanger inspection", "U4", "HX-401", "access", "public", 0.5, 8, 20, "2022-U4-spring",
     "U4 manway bolts seized",
     "Manway bolts on HX-401 were seized; opening took an extra 12 hours.",
     "Apply penetrating oil and pre-loosen manway bolts at the start of the outage."),
    ("L-0020", "Unit restart", "U2", "Unit startup", "permits", "internal", 0.2, 8, 13, "2024-U2-spring",
     "Restart held for work order close-out",
     "Unit restart waited 5 hours for work order close-out signatures.",
     "Track work order close-out daily in the last 48 hours."),
    ("L-0021", "Weld repair", "U1", "Feedwater line", "resources", "internal", 1.0, 8, 32, "2023-U1-fall",
     "Certified welder not available on night shift",
     "The only certified welder was on days, so a night repair waited a shift.",
     "Roster a certified welder on every shift when weld repair is in scope."),
    ("L-0022", "Insulation removal", "U3", "Main steam line", "other", "public", 0.3, 6, 13, "2025-U3-fall",
     "Asbestos survey needed before insulation removal",
     "Older insulation needed a survey before removal, adding 7 hours.",
     "Check the insulation register and book surveys in advance."),
    ("L-0023", "Electrical testing", "U4", "Switchgear", "resources", "public", 0.25, 6, 12, "2022-U4-spring",
     "Test equipment shared with another unit",
     "Relay test set was in use on U2, delaying U4 switchgear testing 6 hours.",
     "Reserve test equipment per unit in the outage plan."),
    ("L-0024", "Scaffolding erection", "U2", "Boiler house", "weather", "public", 0.5, 12, 24, "2024-U2-spring",
     "High winds stopped external scaffolding",
     "Wind above 40 km/h stopped external scaffold erection for 12 hours.",
     "Schedule external scaffolding with weather float."),
    ("L-0025", "Heat exchanger inspection", "U1", "HX-101", "resources", "restricted", 0.5, 8, 20, "2023-U1-fall",
     "Inspector fatigue on extended shifts",
     "Inspectors worked 14-hour shifts and data quality issues required re-inspection of 40 tubes.",
     "Cap inspection shifts at 12 hours; fatigue policy FP-3 applies."),
    ("L-0026", "Isolation and permits", "U4", "Mechanical isolation", "permits", "internal", 0.3, 4, 11, "2022-U4-spring",
     "Mechanical isolation needed extra blind flange",
     "An unexpected tie-in needed an extra blind flange, delaying permit issue 7 hours.",
     "Walk down isolation boundaries against current P&IDs."),
    ("L-0027", "Tube plugging", "U2", "HX-201", "parts", "public", 0.3, 6, 13, "2024-U2-spring",
     "Not enough tube plugs on site",
     "Plug count was based on the plan, not the worst case; extra plugs were couriered.",
     "Hold plugs for twice the planned plugging scope."),
    ("L-0028", "Valve overhaul", "U3", "MV-301", "resources", "restricted", 0.5, 12, 24, "2025-U3-fall",
     "Valve contractor billing dispute",
     "Delta Valve Services disputed overtime rates mid-outage; work slowed until resolved.",
     "Agree overtime rates in the contract before the outage."),
    ("L-0029", "Hydrotest", "U3", "HX-301", "sequencing", "public", 0.2, 4, 9, "2025-U3-fall",
     "Hydrotest water not at temperature",
     "Hydrotest water was below the minimum temperature; heating took 5 hours.",
     "Start heating hydrotest water one shift before the test."),
    ("L-0030", "Unit restart", "U3", "Unit startup", "sequencing", "internal", 0.3, 8, 15, "2025-U3-fall",
     "Restart checks repeated after late scope change",
     "A late scope addition reopened a system; restart checks were repeated.",
     "Freeze outage scope 24 hours before restart."),
]

# Earlier version of L-0007 (superseded by v2 above).
L0007_V1 = dict(
    title="Tooling arrived late for U3 HX inspection",
    issue="Eddy current tooling arrived late for the U3 heat exchanger inspection, costing about 1.5 days.",
    impact="1.5 day delay", delay_days=1.5, created_by="planner_07",
)
L0007_V2_REASON = "Outage completion report confirmed 2.5 days total delay including probe calibration."

# Drafts: (lesson_id, job_type, unit, equipment, category, sensitivity, delay_days, days_until_expiry, title, issue, recommendation)
DRAFTS = [
    ("L-0031", "Drain and vent", "U3", "HX-301", "sequencing", "public", 0.1, 28,
     "Drain and vent crossed midnight and slowed",
     "Draining the heat exchanger across midnight took 3 hours longer at shift handover.",
     "Plan drain and vent to finish before the shift change."),
    ("L-0032", "Heat exchanger inspection", "U4", "HX-401", "tooling", "public", 0.0, 15,
     "U4 HX-401 has a different tube pitch from U3",
     "U4 HX-401 uses a different tube pitch; probes sized for U3 may not fit.",
     "Confirm probe size against U4 drawings."),
    ("L-0033", "Crane lift", "U4", "Turbine hall crane", "resources", "internal", 0.2, 2,
     "Crane inspection due during U4 outage",
     "The crane's annual inspection falls in the U4 outage window.",
     "Move the crane inspection or book a mobile crane."),
]

# Forgotten lesson: tombstone only (content removed under retention policy).
FORGOTTEN = ("L-0034", "Valve overhaul", "U2", "MV-201", "parts",
             "Duplicate of L-0009 and named an individual; forgotten under retention policy.")


def embed_text(doc: dict) -> str:
    """Must match the contract exactly."""
    return f"{doc['job_type']}. {doc['unit']} {doc['equipment']}. {doc['title']}. {doc['issue']}. {doc['recommendation']}"


def _impact(delay_days: float) -> str:
    return f"{delay_days:g} day delay" if delay_days else "No delay recorded"


# Lesson graph for $graphLookup. (from, type, to, note); stored on both ends with the
# inverse type (led_to <-> caused_by, same_root_cause both ways).
LINKS = [
    ("L-0005", "led_to", "L-0007", "Scaffold overrun compressed the window to stage inspection tooling"),
    ("L-0007", "led_to", "L-0010", "Inspection slip pushed channel head closure across the midnight handover"),
    ("L-0010", "led_to", "L-0029", "Late closure moved hydrotest before the water was heated"),
    ("L-0007", "same_root_cause", "L-0002", "Inspection tooling not verified before the work window"),
    ("L-0007", "same_root_cause", "L-0003", "Inspection tooling not verified before the work window"),
    ("L-0007", "same_root_cause", "L-0012", "Inspection contractor readiness not confirmed before outage"),
    ("L-0006", "led_to", "L-0005", "Late permits delayed scaffold start into the drain and vent window"),
    ("L-0027", "led_to", "L-0011", "Plug shortage forced rushed plugging and a leaking plug"),
    ("L-0004", "led_to", "L-0027", "Plugging scope underestimated, so plug stock ran short"),
    ("L-0008", "same_root_cause", "L-0023", "Shared equipment not booked across units"),
    ("L-0009", "same_root_cause", "L-0018", "Critical spares not physically verified before outage"),
    ("L-0017", "same_root_cause", "L-0018", "Critical spares not physically verified before outage"),
    ("L-0021", "same_root_cause", "L-0025", "Shift rostering of qualified staff"),
    ("L-0013", "same_root_cause", "L-0026", "Isolation boundaries not verified against current drawings"),
]
INVERSE = {"led_to": "caused_by", "caused_by": "led_to", "same_root_cause": "same_root_cause"}


def links_for(lesson_id: str) -> list[dict]:
    out = []
    for a, t, b, note in LINKS:
        if a == lesson_id:
            out.append({"lesson_id": b, "type": t, "note": note})
        elif b == lesson_id:
            out.append({"lesson_id": a, "type": INVERSE[t], "note": note})
    return out


def build_seed(now: datetime | None = None) -> dict:
    """Return {"lessons": [...], "audit_log": [...]} without embeddings or _ids.
    Version links (supersedes/superseded_by) are filled in by seed_governed.py after insert,
    using the `_link` key."""
    now = now or datetime.now(timezone.utc)
    lessons, audit = [], []
    t0 = now - timedelta(days=60)

    for i, (lid, job, unit, equip, cat, sens, delay, ph, ah, outage, title, issue, rec) in enumerate(APPROVED):
        created = t0 + timedelta(hours=i)
        base = dict(lesson_id=lid, version=1, job_type=job, unit=unit, equipment=equip, title=title, issue=issue,
                    impact=_impact(delay), recommendation=rec, category=cat, delay_days=delay, sensitivity=sens,
                    allowed_roles=list(ALL_ROLES), status="approved", source="seed",
                    evidence=[{"type": "outage_record", "ref": outage, "detail": f"planned {ph}h, actual {ah}h"}],
                    outage_id=outage, created_by="lead_01", created_at=created,
                    approved_by="lead_01", approved_at=created + timedelta(hours=2),
                    expires_at=None, supersedes=None, superseded_by=None, change_reason=None)
        if lid == "L-0007":
            v1 = dict(base, **L0007_V1, status="superseded", _link="L-0007:v1")
            v1["impact"] = _impact(v1["delay_days"])
            v1["evidence"] = [{"type": "shift_log", "ref": "U3 night shift 2025-09-14", "detail": "tooling late"}]
            v2 = dict(base, version=2, created_at=created + timedelta(days=10),
                      approved_at=created + timedelta(days=10, hours=1), change_reason=L0007_V2_REASON,
                      _link="L-0007:v2", _supersedes="L-0007:v1",
                      evidence=base["evidence"] + [{"type": "completion_report", "ref": "U3-OCR-2025-09 s4.2",
                                                    "detail": "2.5 days total incl. probe calibration"}])
            lessons += [v1, v2]
            audit += [
                _audit(created, "planner_07", "add", lid, 1, True, "lesson added from shift log"),
                _audit(created + timedelta(hours=2), "lead_01", "approve", lid, 1, True, ""),
                _audit(created + timedelta(days=10), "lead_01", "correct", lid, 2, True, L0007_V2_REASON),
            ]
        else:
            lessons.append(base)
            audit.append(_audit(created + timedelta(hours=2), "lead_01", "approve", lid, 1, True, "seed"))

    for j, (lid, job, unit, equip, cat, sens, delay, days_left, title, issue, rec) in enumerate(DRAFTS):
        created = now - timedelta(days=30 - days_left)
        lessons.append(dict(lesson_id=lid, version=1, job_type=job, unit=unit, equipment=equip, title=title,
                            issue=issue, impact=_impact(delay), recommendation=rec, category=cat, delay_days=delay,
                            sensitivity=sens, allowed_roles=list(ALL_ROLES), status="draft", source="manual",
                            evidence=[{"type": "planner_note", "ref": f"note-{lid}", "detail": ""}],
                            outage_id=None, created_by="planner_07", created_at=created,
                            approved_by=None, approved_at=None, expires_at=created + timedelta(days=30),
                            supersedes=None, superseded_by=None, change_reason=None))
        audit.append(_audit(created, "planner_07", "add", lid, 1, True, "saved as draft"))

    lid, job, unit, equip, cat, reason = FORGOTTEN
    created = t0 - timedelta(days=5)
    lessons.append(dict(lesson_id=lid, version=1, job_type=job, unit=unit, equipment=equip, title="[forgotten]",
                        issue="[content removed under retention policy]", impact="", recommendation="", category=cat,
                        delay_days=0, sensitivity="internal", allowed_roles=list(ALL_ROLES), status="forgotten",
                        source="seed", evidence=[], outage_id=None, created_by="planner_07", created_at=created,
                        approved_by="lead_01", approved_at=created, expires_at=None, supersedes=None,
                        superseded_by=None, change_reason=reason))
    audit.append(_audit(now - timedelta(days=3), "lead_01", "forget", lid, 1, True, reason))

    # A few denied attempts so the audit tab has red rows from the start.
    audit += [
        _audit(now - timedelta(days=2), "contractor_02", "retrieve_denied", "L-0012", 1, False, "restricted lesson hidden by policy"),
        _audit(now - timedelta(days=2), "contractor_02", "add", None, None, False, "contractor role is read only"),
        _audit(now - timedelta(days=1), "planner_07", "approve", "L-0031", 1, False, "only lead can approve"),
    ]
    for d in lessons:
        d["links"] = links_for(d["lesson_id"]) if d["status"] != "forgotten" else []
    return {"lessons": lessons, "audit_log": audit}


def _audit(ts, user, action, lesson_id, version, allowed, detail):
    return {"ts": ts, "user_id": user, "role": USERS[user], "action": action, "lesson_id": lesson_id,
            "version": version, "allowed": allowed, "detail": detail}
