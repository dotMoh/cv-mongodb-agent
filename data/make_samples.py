"""Generate sample outage schedules and actuals in data/samples/.

    python make_samples.py

- u4_outage_24h.csv    clean 24-hour U4 outage, 20 tasks, demo file
- u4_outage_24h.xlsx   same outage, different column names, Day + time-only columns
                       (midnight rollover), no Critical column, and one ambiguous row
- u4_actuals.csv       actual start/end for the CSV; two tasks overran (tooling prep, HX inspection)
"""
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "samples"
DAY0 = datetime(2027, 3, 1)

# id, name, unit, equipment, discipline, contractor, start "D HH:MM", end "D HH:MM", preds, critical, milestone, permit
TASKS = [
    ("T01", "Unit U4 shutdown and cooldown", "U4", "Reactor unit", "Operations", "Station operations", "1 06:00", "1 08:00", "", True, False, ""),
    ("T02", "Electrical isolation and permits", "U4", "Electrical isolation", "Electrical", "Station operations", "1 08:00", "1 10:00", "T01", True, False, "WP-401"),
    ("T03", "Mechanical isolation", "U4", "Mechanical isolation", "Mechanical", "Station operations", "1 08:00", "1 10:00", "T01", False, False, "WP-402"),
    ("T04", "Drain and vent HX-401", "U4", "HX-401", "Mechanical", "Station operations", "1 10:00", "1 13:00", "T02;T03", True, False, "WP-403"),
    ("T05", "Scaffolding erection HX bay", "U4", "HX bay scaffold", "Access", "Apex Access Ltd", "1 10:00", "1 14:00", "T02", False, False, ""),
    ("T06", "Insulation removal main steam line", "U4", "Main steam line", "Insulation", "Apex Access Ltd", "1 10:00", "1 12:00", "T02", False, False, ""),
    ("T07", "Open HX-401 manway and channel head", "U4", "HX-401", "Mechanical", "Northline Inspection Services", "1 14:00", "1 15:00", "T04;T05", True, False, ""),
    ("T08", "Tooling preparation (eddy current probes)", "U4", "HX-401", "Inspection", "Northline Inspection Services", "1 15:00", "1 16:00", "T07", True, False, ""),
    ("T09", "U4 HX tube inspection", "U4", "HX-401", "Inspection", "Northline Inspection Services", "1 16:00", "1 22:00", "T08", True, False, ""),
    ("T10", "Tube plugging (as required)", "U4", "HX-401", "Mechanical", "Northline Inspection Services", "1 22:00", "2 00:30", "T09", True, False, ""),
    ("T11", "Valve overhaul MV-401", "U4", "MV-401", "Mechanical", "Delta Valve Services", "1 14:00", "2 02:00", "T03", False, False, "WP-404"),
    ("T12", "Crane lift P-402 motor", "U4", "Turbine hall crane", "Lifting", "Station operations", "1 12:00", "1 13:00", "T02", False, False, "LP-17"),
    ("T13", "Pump motor replacement P-402", "U4", "P-402 motor", "Electrical", "Station operations", "1 13:00", "1 19:00", "T12", False, False, ""),
    ("T14", "Electrical testing switchgear", "U4", "Switchgear", "Electrical", "Station operations", "1 19:00", "1 23:00", "T13", False, False, ""),
    ("T15", "Channel head closure", "U4", "HX-401", "Mechanical", "Northline Inspection Services", "2 00:30", "2 02:30", "T10", True, False, ""),
    ("T16", "Hydrotest HX-401", "U4", "HX-401", "Mechanical", "Station operations", "2 02:30", "2 04:00", "T15", True, False, ""),
    ("T17", "Remove scaffolding HX bay", "U4", "HX bay scaffold", "Access", "Apex Access Ltd", "2 04:00", "2 05:00", "T16", False, False, ""),
    ("T18", "Remove isolations", "U4", "Electrical isolation", "Operations", "Station operations", "2 04:00", "2 05:00", "T16;T11;T14", True, False, ""),
    ("T19", "Unit restart", "U4", "Unit startup", "Operations", "Station operations", "2 05:00", "2 06:00", "T18;T17", True, False, ""),
    ("T20", "Unit online", "U4", "Unit startup", "Operations", "Station operations", "2 06:00", "2 06:00", "T19", True, True, ""),
]

# Overruns for the actuals file: task -> (extra hours on its own duration, cause)
OVERRUNS = {
    "T08": (3.0, "Probes sized for U3 did not fit HX-401 tube pitch; correct probes fetched from stores"),
    "T09": (4.0, "Inspection started late after tooling issue and 40 extra tubes needed re-test"),
}


def at(s: str) -> datetime:
    d, hm = s.split()
    h, m = map(int, hm.split(":"))
    return DAY0 + timedelta(days=int(d) - 1, hours=h, minutes=m)


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for tid, name, unit, eq, disc, con, s, e, preds, crit, ms, permit in TASKS:
        start, end = at(s), at(e)
        rows.append({
            "Task ID": tid, "Task Name": name, "Unit": unit, "Equipment": eq, "Discipline": disc,
            "Contractor": con, "Start": start.strftime("%Y-%m-%d %H:%M"), "Finish": end.strftime("%Y-%m-%d %H:%M"),
            "Duration (h)": round((end - start).total_seconds() / 3600, 2), "Predecessors": preds,
            "Critical": "Yes" if crit else "No", "Milestone": "Yes" if ms else "No", "Permit": permit,
        })
    pd.DataFrame(rows).to_csv(OUT / "u4_outage_24h.csv", index=False)

    # XLSX: different headers, day number + time-only columns, comma-separated preds, no Critical column.
    x = []
    for r, t in zip(rows, TASKS):
        x.append({
            "WBS": r["Task ID"].replace("T", "4."), "Activity Description": r["Task Name"], "Area": "Unit 4",
            "Asset": r["Equipment"], "Trade": r["Discipline"], "Responsible": r["Contractor"],
            "Day": int(t[6].split()[0]), "Start Time": t[6].split()[1], "End Time": t[7].split()[1],
            "Dur (hrs)": r["Duration (h)"], "Depends On": ", ".join(p.replace("T", "4.") for p in r["Predecessors"].split(";") if p),
            "Key Milestone": "Y" if r["Milestone"] == "Yes" else "", "Work Permit": r["Permit"],
        })
    # Ambiguous row: no end time and no duration; the parser must flag it, not invent it.
    x.insert(13, {"WBS": "4.13a", "Activity Description": "Fire system impairment check", "Area": "Unit 4",
                  "Asset": "Fire protection", "Trade": "Operations", "Responsible": "Station operations",
                  "Day": 1, "Start Time": "18:00", "End Time": "", "Dur (hrs)": None, "Depends On": "4.02",
                  "Key Milestone": "", "Work Permit": ""})
    with pd.ExcelWriter(OUT / "u4_outage_24h.xlsx") as w:
        pd.DataFrame(x).to_excel(w, sheet_name="Outage Plan", index=False)

    # Actuals: overruns stretch the task itself; downstream tasks start later but keep their durations.
    actual_end, acts = {}, []
    for tid, name, *_rest in TASKS:
        s, e, preds = at(_rest[4]), at(_rest[5]), [p for p in _rest[6].split(";") if p]
        dur = e - s
        a_start = max([s] + [actual_end[p] for p in preds if p in actual_end])
        extra, cause = OVERRUNS.get(tid, (0.0, ""))
        a_end = a_start + dur + timedelta(hours=extra)
        actual_end[tid] = a_end
        acts.append({"task_id": tid, "task_name": name, "planned_start": s.strftime("%Y-%m-%d %H:%M"),
                     "planned_end": e.strftime("%Y-%m-%d %H:%M"), "actual_start": a_start.strftime("%Y-%m-%d %H:%M"),
                     "actual_end": a_end.strftime("%Y-%m-%d %H:%M"), "delay_cause": cause})
    pd.DataFrame(acts).to_csv(OUT / "u4_actuals.csv", index=False)
    print(f"Wrote {len(rows)} tasks to u4_outage_24h.csv, {len(x)} rows to u4_outage_24h.xlsx, actuals to u4_actuals.csv in {OUT}")


if __name__ == "__main__":
    main()
