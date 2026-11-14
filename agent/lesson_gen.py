"""Propose draft lessons from planned vs actual performance. Drafts never skip Lead approval."""
from __future__ import annotations

import re

from . import governance
from .schedule_parser import _blank, _read, _to_dt

OVERRUN_PCT = 0.25
OVERRUN_HOURS = 2.0

CATEGORY_WORDS = [
    ("tooling", r"tool|probe|calibrat|eddy"), ("parts", r"spare|part|kit|seal|gasket|stores"),
    ("permits", r"permit|isolat|lockout|loto"), ("access", r"scaffold|access|badge|rope"),
    ("resources", r"crew|staff|short|resourc|crane|double.?book"), ("weather", r"weather|heat|temperature|wind|rain"),
    ("rework", r"re-?test|rework|redo|re-?inspect|repeat"), ("sequencing", r"sequenc|overlap|clash|hold point|waiting"),
]
RECOMMEND = {
    "tooling": "Confirm tooling fits the equipment and is calibrated before isolation; prepare it the shift before.",
    "parts": "Kit and verify parts against the work order before the outage.",
    "permits": "Pre-approve permits and isolations before the outage window opens.",
    "access": "Complete and inspect access (scaffold, badges) one shift ahead.",
    "resources": "Confirm crew and equipment bookings in writing 48 hours ahead.",
    "weather": "Add weather contingency or move weather-sensitive work.",
    "rework": "Add a verification hold point before downstream work.",
    "sequencing": "Resequence to avoid the overlap and add the hold point to the schedule.",
    "other": "Review the cause with the work group and add contingency for similar work.",
}

ACTUAL_COLS = {
    "id": ["task_id", "task id", "id", "activity id"], "name": ["task_name", "task name", "name", "activity"],
    "actual_start": ["actual_start", "actual start", "act start", "started"],
    "actual_end": ["actual_end", "actual end", "actual finish", "act finish", "finished"],
    "cause": ["delay_cause", "delay cause", "cause", "reason", "comment", "notes"],
}


def _pick(columns, names):
    norm = {re.sub(r"[^a-z0-9]+", " ", c.lower()).strip(): c for c in columns}
    for n in names:
        k = re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()
        if k in norm:
            return norm[k]
    return None


def _rows(actuals, filename):
    if isinstance(actuals, list):
        return actuals
    df = _read(actuals, filename)
    cols = {k: _pick(list(df.columns), v) for k, v in ACTUAL_COLS.items()}
    out = []
    for row in df.to_dict("records"):
        out.append({k: (row.get(c) if c else None) for k, c in cols.items()})
    return out


def categorize(text: str) -> str:
    for cat, pat in CATEGORY_WORDS:
        if re.search(pat, text or "", re.I):
            return cat
    return "other"


def generate(user_id: str, planned: list[dict], actuals_file, filename: str | None = None,
             outage_id: str | None = None, save: bool = True) -> list[dict]:
    """Compare planned vs actual durations; overruns >= 25% or >= 2h become draft lessons with evidence.
    Late starts caused by upstream tasks are not counted (overrun is on the task's own duration)."""
    governance._require(user_id, "generate_lessons", "auto_generate")
    by_id = {str(t["id"]): t for t in planned}
    by_name = {str(t["name"]).lower(): t for t in planned}
    drafts = []
    for row in _rows(actuals_file, filename):
        t = by_id.get(str(row.get("id") or "").strip()) or by_name.get(str(row.get("name") or "").strip().lower())
        if not t or not t.get("start") or not t.get("end"):
            continue
        a_start, _ = _to_dt(row.get("actual_start"), t["start"].date())
        a_end, _ = _to_dt(row.get("actual_end"), (a_start or t["start"]).date())
        if not a_start or not a_end:
            continue
        planned_h = (t["end"] - t["start"]).total_seconds() / 3600
        actual_h = (a_end - a_start).total_seconds() / 3600
        over = actual_h - planned_h
        if over < OVERRUN_HOURS and (planned_h == 0 or over / planned_h < OVERRUN_PCT):
            continue
        cause = None if _blank(row.get("cause")) else str(row["cause"]).strip()
        cat = categorize(f"{cause or ''} {t['name']}")
        evidence = [{"type": "outage_completion", "ref": outage_id or "uploaded actuals",
                     "detail": f"{t['id']} planned {planned_h:g}h ({t['start']:%d %b %H:%M}-{t['end']:%H:%M}), "
                               f"actual {actual_h:g}h ({a_start:%d %b %H:%M}-{a_end:%d %b %H:%M})"
                               + (f"; cause: {cause}" if cause else "")}]
        fields = {
            "job_type": re.sub(r"\(.*?\)", "", t["name"]).strip(), "unit": t.get("unit"), "equipment": t.get("equipment"),
            "title": f"{t['name']} overran by {over:g}h",
            "issue": cause or f"Took {actual_h:g}h against {planned_h:g}h planned; cause not recorded.",
            "impact": f"{over:g}h overrun ({over / 24:.2f} day delay exposure)",
            "recommendation": RECOMMEND[cat], "category": cat, "delay_days": round(over / 24, 2),
            "sensitivity": "internal", "evidence": evidence, "outage_id": outage_id,
        }
        dupes = governance.retrieve("lead_01", f"{fields['job_type']} {fields['issue']}", k=3, log=False, min_similarity=0.45)["lessons"]
        fields["duplicates"] = [{"lesson_id": d["lesson_id"], "version": d["version"], "title": d["title"],
                                 "similarity": d["similarity"]} for d in dupes]
        if save:
            drafts.append(governance.add_lesson(user_id, fields, source="auto_generated", action="auto_generate"))
        else:
            drafts.append(dict(fields, status="draft", source="auto_generated"))
    return drafts
