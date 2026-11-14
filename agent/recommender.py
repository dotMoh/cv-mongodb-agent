"""Turn task risks into concrete Gantt changes, and apply decisions as a new schedule version.

Risk reductions are rule-of-thumb estimates per change type, labelled as estimates in the UI.
"""
from __future__ import annotations

import copy
import itertools
import re
from datetime import timedelta

from . import governance, schedules

_RECS: dict[str, dict] = {}       # rec_id -> recommendation (lives for the app session)
_counter = itertools.count(1)

# Expected share of the task's risk left after each change type (estimate).
RESIDUAL = {"move_earlier": 0.45, "add_prerequisite": 0.5, "add_milestone": 0.75, "add_contingency": 0.8,
            "resequence": 0.6}
PREP_WORDS = re.compile(r"tool|prep|probe|kit|calibrat|mobili", re.I)


def _by_id(tasks):
    return {t["id"]: t for t in tasks}


def project_end(tasks):
    ends = [t["end"] for t in tasks if t.get("end")]
    return max(ends) if ends else None


def project_start(tasks):
    starts = [t["start"] for t in tasks if t.get("start")]
    return min(starts) if starts else None


def _push_successors(tasks, changed_id):
    """Push successors later if they now start before a predecessor ends (durations kept)."""
    by = _by_id(tasks)
    queue = [changed_id]
    while queue:
        cur = queue.pop(0)
        for t in tasks:
            if cur in (t.get("predecessors") or []) and t.get("start") and t.get("end"):
                pred_end = max(by[p]["end"] for p in t["predecessors"] if p in by and by[p].get("end"))
                if t["start"] < pred_end:
                    delta = pred_end - t["start"]
                    t["start"] += delta
                    t["end"] += delta
                    queue.append(t["id"])


def apply_change(tasks: list[dict], rec: dict) -> list[dict]:
    """Returns a new task list with one recommendation applied (input untouched)."""
    tasks = copy.deepcopy(tasks)
    by = _by_id(tasks)
    prop = rec["proposed"]
    owner = by.get(rec["task_id"])
    if owner is not None:
        owner.setdefault("mitigations", []).append(
            {"rec_id": rec["rec_id"], "type": rec["type"], "residual": RESIDUAL.get(rec["type"], 1.0),
             "lessons": [l["lesson_id"] for l in rec.get("lessons", [])]})
        by = _by_id(tasks)
    if "new_task" in prop:
        nt = copy.deepcopy(prop["new_task"])
        tasks.append(nt)
        for tid in prop.get("feeds", []):
            if tid in by and nt["id"] not in by[tid]["predecessors"]:
                by[tid]["predecessors"].append(nt["id"])
        _push_successors(tasks, nt["id"])
    else:
        t = by.get(rec["target_id"])
        if t is None:
            return tasks
        t["start"], t["end"] = prop["start"], prop["end"]
        t["duration_hours"] = round((t["end"] - t["start"]).total_seconds() / 3600, 2)
        t["predecessors"] = [p for p in t["predecessors"] if p not in prop.get("drop_predecessors", [])]
        _push_successors(tasks, t["id"])
    return tasks


def _impact_hours(tasks, rec):
    before, after = project_end(tasks), project_end(apply_change(tasks, rec))
    return round((after - before).total_seconds() / 3600, 2) if before and after else 0.0


def _new_task(tid, name, start, hours, like, milestone=False):
    return {"id": tid, "name": name, "start": start, "end": start + timedelta(hours=hours), "duration_hours": hours,
            "unit": like.get("unit"), "contractor": like.get("contractor"), "equipment": like.get("equipment"),
            "discipline": like.get("discipline"), "predecessors": [], "critical": False, "milestone": milestone,
            "permit": None, "source_row": None, "added_by_agent": True}


def _rec(tr, task, rtype, target_id, proposed, reason, tasks):
    lessons = [{"lesson_id": m["lesson_id"], "version": m["version"], "title": m["title"]} for m in tr["matches"][:3]]
    top = tr["matches"][0]
    r = {"rec_id": f"R{next(_counter)}", "task_id": task["id"], "task_name": task["name"], "type": rtype,
         "target_id": target_id,
         "original": {"start": task["start"], "end": task["end"]},
         "proposed": proposed, "risk": f"{(top.get('category') or 'repeat issue').title()} ({top['lesson_id']} v{top['version']})",
         "reason": reason, "lessons": lessons, "risk_before_pct": tr["risk_pct"],
         "risk_after_pct": round(tr["risk_pct"] * RESIDUAL[rtype]), "status": "proposed", "estimate": True}
    if target_id != task["id"] and target_id in _by_id(tasks):
        t = _by_id(tasks)[target_id]
        r["original"] = {"start": t["start"], "end": t["end"], "task_name": t["name"]}
    r["duration_impact_hours"] = _impact_hours(tasks, r)
    _RECS[r["rec_id"]] = r
    return r


def recommend(user_id: str, tasks: list[dict], report: dict, min_risk: int = 50, max_tasks: int = 5) -> list[dict]:
    governance.role_of(user_id)
    by = _by_id(tasks)
    p_start = project_start(tasks)
    recs = []
    done = 0
    for tr in report["tasks"]:
        task = by.get(tr["task_id"])
        if not task or not tr["matches"] or tr["risk_pct"] < min_risk or not task.get("start") or not task.get("end"):
            continue
        if tr.get("mitigated") or done >= max_tasks:
            continue
        done += 1
        cats = {m.get("category") for m in tr["matches"]}
        top = tr["matches"][0]
        exposure_h = (tr["delay_exposure_days"] or 0) * 24
        if cats & {"tooling", "parts"}:
            prep = next((by[p] for p in task["predecessors"] if p in by and PREP_WORDS.search(by[p]["name"])), None)
            if prep:
                new_start = max(p_start, prep["start"] - timedelta(hours=12)) if p_start else prep["start"] - timedelta(hours=12)
                dur = prep["end"] - prep["start"]
                recs.append(_rec(tr, task, "move_earlier", prep["id"],
                                 {"start": new_start, "end": new_start + dur, "drop_predecessors": list(prep["predecessors"])},
                                 f"Move '{prep['name']}' to the previous shift so missing or wrong tooling is found before "
                                 f"'{task['name']}' is due to start. {top['title']}.", tasks))
                v_start = new_start + dur
                recs.append(_rec(tr, task, "add_milestone", task["id"],
                                 {"new_task": _new_task(f"{task['id']}-V", "Tooling verification: fit and calibration check",
                                                        v_start, 2.0, task, milestone=True), "feeds": [task["id"]]},
                                 "Add a two-hour verification milestone: confirm probes fit this equipment and calibration "
                                 "certificates are current.", tasks))
            else:
                s = task["start"] - timedelta(hours=14)
                recs.append(_rec(tr, task, "add_prerequisite", task["id"],
                                 {"new_task": _new_task(f"{task['id']}-P", "Confirm tooling and parts on site and tested", s, 2.0, task),
                                  "feeds": [task["id"]]},
                                 f"Add a prerequisite check the shift before. {top.get('recommendation') or ''}", tasks))
        elif cats & {"permits", "access"}:
            s = (p_start or task["start"]) - timedelta(hours=4)
            recs.append(_rec(tr, task, "add_prerequisite", task["id"],
                             {"new_task": _new_task(f"{task['id']}-P", "Pre-approve permits and confirm access (scaffold, badges)",
                                                    s, 2.0, task), "feeds": [task["id"]]},
                             f"Clear permits and access before the outage starts. {top.get('recommendation') or ''}", tasks))
        elif cats & {"rework", "sequencing"}:
            recs.append(_rec(tr, task, "add_milestone", task["id"],
                             {"new_task": _new_task(f"{task['id']}-H", f"Verification hold point after {task['name']}",
                                                    task["end"], 1.0, task, milestone=True), "feeds": tr["knock_on"][:1]},
                             f"Add a verification hold point before downstream work. {top.get('recommendation') or ''}", tasks))
        if task.get("critical") and tr["classification"] == "High":
            hours = float(min(4, max(1, round(exposure_h * 0.1))))
            recs.append(_rec(tr, task, "add_contingency", task["id"],
                             {"start": task["start"], "end": task["end"] + timedelta(hours=hours)},
                             f"Add {hours:g}h contingency to protect the critical path: similar work slipped "
                             f"{tr['delay_exposure_days']:g} days on average.", tasks))
        elif not any(r["task_id"] == task["id"] for r in recs):
            hours = float(min(4, max(1, round(exposure_h * 0.05))))
            recs.append(_rec(tr, task, "add_contingency", task["id"],
                             {"start": task["start"], "end": task["end"] + timedelta(hours=hours)},
                             f"Add {hours:g}h contingency. {top.get('recommendation') or ''}", tasks))
    return recs


def get(rec_id: str) -> dict | None:
    return _RECS.get(rec_id)


def apply(user_id: str, schedule_id: str, decisions: dict, recommendations: list[dict] | None = None) -> dict:
    """decisions: {rec_id: "accept" | "reject" | {"modify": {...fields of the rec to override...}}}.
    Applies to the latest version and saves a new one. The baseline is never changed."""
    governance._require(user_id, "decide_recommendation", "rec_accept")
    for r in recommendations or []:
        _RECS[r["rec_id"]] = r
    base = schedules.get(schedule_id)
    if base is None:
        raise KeyError(schedule_id)
    tasks = copy.deepcopy(base["tasks"])
    applied, record = [], {}
    for rec_id, decision in decisions.items():
        rec = _RECS.get(rec_id)
        if rec is None:
            raise KeyError(f"unknown recommendation {rec_id}")
        if decision == "reject":
            governance.audit(user_id, "rec_reject", detail=f"{rec_id} {rec['type']} on {rec['task_id']}")
            record[rec_id] = "rejected"
            continue
        if isinstance(decision, dict) and "modify" in decision:
            rec = {**rec, **copy.deepcopy(decision["modify"])}
            governance.audit(user_id, "rec_modify", detail=f"{rec_id} {rec['type']} on {rec['task_id']} (modified)")
            record[rec_id] = "modified"
        else:
            governance.audit(user_id, "rec_accept", detail=f"{rec_id} {rec['type']} on {rec['task_id']}")
            record[rec_id] = "accepted"
        tasks = apply_change(tasks, rec)
        applied.append({"rec_id": rec_id, "type": rec["type"], "task_id": rec["task_id"], "decision": record[rec_id],
                        "lessons": rec.get("lessons", [])})
    return schedules.save_version(user_id, schedule_id, tasks, base["version"], applied, record)


def compare(schedule_a: dict, schedule_b: dict) -> list[dict]:
    """Per-task diff for the two-Gantt view: status changed | added | unchanged."""
    a, out = _by_id(schedule_a["tasks"]), []
    for t in schedule_b["tasks"]:
        o = a.get(t["id"])
        if o is None:
            out.append({"task_id": t["id"], "status": "added", "task": t})
        elif (o["start"], o["end"], o["predecessors"]) != (t["start"], t["end"], t["predecessors"]):
            out.append({"task_id": t["id"], "status": "changed", "task": t, "was": {"start": o["start"], "end": o["end"]}})
        else:
            out.append({"task_id": t["id"], "status": "unchanged", "task": t})
    return out
