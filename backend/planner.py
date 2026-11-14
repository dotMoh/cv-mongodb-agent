"""Turns (task, role, memories) into a schedule. Ollama first, rule-based fallback.

Schedule step shape (what the frontend renders):
  {"phase": str, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "duration_days": int,
   "risk": "low"|"medium"|"high", "note": str}
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import httpx

from config import LLM_MODE, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

BASE_PHASES = [
    ("Pre-outage prep and permits", 5),
    ("Shutdown and cooldown", 2),
    ("Inspection and maintenance", 8),
    ("Post-maintenance testing", 3),
    ("Restart and grid sync", 2),
]

NEGATION = re.compile(r"\b(no longer|resolved|fixed|not an issue|no delay|eliminated)\b", re.I)
COOLING = re.compile(r"(intake|cooling water|condenser)", re.I)
HEAT = re.compile(r"(warm|heat|hot|overheat|temperature)", re.I)
RESOLVED_COOLING = re.compile(r"chiller", re.I)
GRID_DEMAND = re.compile(r"(peak demand|grid operator refused|heat wave)", re.I)
PERMITS = re.compile(r"permit", re.I)
SIGNOFF = re.compile(r"(sign-off|notice)", re.I)


def _first_monday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def target_start(task: str, today: date | None = None) -> date:
    today = today or date.today()
    month = next((i + 1 for i, m in enumerate(MONTHS) if m in task.lower() or m[:3] + " " in task.lower()), None)
    if month is None:
        month = today.month % 12 + 1
    year = today.year if month > today.month else today.year + 1
    return _first_monday(year, month)


def _lay_out(start: date, phases: list[dict]) -> list[dict]:
    cur = start
    out = []
    for p in phases:
        end = cur + timedelta(days=p["duration_days"] - 1)
        out.append({"phase": p["phase"], "shifted": p.get("shifted", False), "start": cur.isoformat(), "end": end.isoformat(),
                    "duration_days": p["duration_days"], "risk": p.get("risk", "low"), "note": p.get("note", "")})
        cur = end + timedelta(days=1)
    return out


def rule_based_plan(task: str, role: str, memories: list[dict]) -> dict:
    start = target_start(task)
    summer = start.month in (6, 7, 8, 9)
    phases = [{"phase": n, "duration_days": d, "risk": "low", "note": ""} for n, d in BASE_PHASES]
    by_name = {p["phase"]: p for p in phases}
    adjustments = []
    pre_steps = []

    def note(phase, text, risk=None, shifted=True):
        p = by_name[phase]
        p["shifted"] = p.get("shifted", False) or shifted
        p["note"] = (p["note"] + " " + text).strip()
        if risk and ["low", "medium", "high"].index(risk) > ["low", "medium", "high"].index(p["risk"]):
            p["risk"] = risk

    # A lesson saying the cooling problem is fixed (e.g. chiller retrofit) overrides every older heat lesson.
    resolved = next((m for m in memories if COOLING.search(m.get("content", ""))
                     and (NEGATION.search(m["content"]) or RESOLVED_COOLING.search(m["content"]))), None)
    heat_noted = False

    for m in memories:
        c, mid = m.get("content", ""), m.get("id")
        if COOLING.search(c) and (HEAT.search(c) or NEGATION.search(c) or RESOLVED_COOLING.search(c)):
            if resolved:
                if heat_noted:
                    continue
                heat_noted = True
                mid = resolved.get("id")
                note("Inspection and maintenance", f"Intake cooling issue resolved per recent lesson ({mid}); no heat buffer needed.", shifted=False)
                adjustments.append({"memory_id": mid, "change": "No heat buffer: cooling water issue marked resolved."})
            elif summer and not heat_noted:
                heat_noted = True
                start -= timedelta(days=21)
                by_name["Inspection and maintenance"]["duration_days"] += 3
                note("Inspection and maintenance", f"Moved 3 weeks earlier and added 3 buffer days: warm intake water slipped a past July outage ({mid}).", "high")
                adjustments.append({"memory_id": mid, "change": "Start moved 3 weeks earlier and 3 buffer days added to avoid warm cooling water."})
        elif GRID_DEMAND.search(c) and summer and resolved and re.search(r"heat wave", resolved["content"], re.I):
            continue  # the fix lesson says heat waves no longer delay this unit
        elif GRID_DEMAND.search(c) and summer:
            note("Restart and grid sync", f"Confirm the window with the grid operator early; summer peak demand blocked a past outage ({mid}).", "medium")
            adjustments.append({"memory_id": mid, "change": "Flagged restart for grid operator confirmation due to summer peak demand."})
        elif PERMITS.search(c):
            if by_name["Pre-outage prep and permits"]["duration_days"] < 10:
                by_name["Pre-outage prep and permits"]["duration_days"] = 10
            note("Pre-outage prep and permits", f"Radiation work permits need 10 days lead time ({mid}).", "medium")
            adjustments.append({"memory_id": mid, "change": "Prep phase extended to 10 days for permit approvals."})
        elif SIGNOFF.search(c):
            pre_steps.append({"phase": "Notify grid operator (14 days ahead)", "duration_days": 1, "risk": "medium",
                              "note": f"Late grid sign-off cost 3 days previously ({mid}).", "shifted": True})
            adjustments.append({"memory_id": mid, "change": "Added grid operator notice 14 days before the outage."})

    schedule = _lay_out(start, phases)
    for s in pre_steps:
        d = start - timedelta(days=14)
        schedule.insert(0, {**s, "start": d.isoformat(), "end": d.isoformat()})

    total = sum(p["duration_days"] for p in phases)
    summary = f"{total}-day outage starting {start.strftime('%B %d, %Y')}"
    summary += f", shaped by {len(adjustments)} past lesson(s)." if adjustments else ", no past lessons changed the baseline."
    return {"summary": summary, "schedule": schedule, "adjustments": adjustments}


# ---------------------------------------------------------------- Ollama
SYSTEM_PROMPT = """You are an outage planning agent for a power generation station.
You plan maintenance outages and you MUST learn from past lessons: if a lesson shows a risk
for this plant and season, change the dates, durations or risk levels to avoid it, and say which
lesson caused each change. Ignore lessons that are irrelevant. Dates are ISO YYYY-MM-DD and phases
must be back to back. Reply with JSON only, in exactly this shape:
{"summary": str,
 "schedule": [{"phase": str, "start": str, "end": str, "duration_days": int, "risk": "low"|"medium"|"high", "note": str}],
 "adjustments": [{"memory_id": str, "change": str}]}"""


def _user_prompt(task, role, memories, draft):
    lessons = "\n".join(f"- [{m['id']}] {m['content']}" for m in memories) or "- (none)"
    return (f"Role asking: {role}\nTask: {task}\n\nPast lessons (id in brackets):\n{lessons}\n\n"
            f"Draft schedule to revise:\n{json.dumps(draft['schedule'], indent=1)}\n")


def _valid(plan) -> bool:
    try:
        assert isinstance(plan["summary"], str) and plan["schedule"]
        for s in plan["schedule"]:
            date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
            s.setdefault("risk", "low"), s.setdefault("note", "")
            s["duration_days"] = int(s.get("duration_days") or
                                     (date.fromisoformat(s["end"]) - date.fromisoformat(s["start"])).days + 1)
        plan.setdefault("adjustments", [])
        return True
    except Exception:
        return False


async def ollama_plan(task, role, memories, draft) -> dict:
    payload = {
        "model": OLLAMA_MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0.2},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _user_prompt(task, role, memories, draft)}],
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        plan = json.loads(r.json()["message"]["content"])
    if not _valid(plan):
        raise ValueError("Ollama returned an invalid plan")
    return plan


def normalize_steps(plan: dict) -> dict:
    """Frontend contract: each step has "step" (name), start, end, note, shifted."""
    for s in plan["schedule"]:
        s["step"] = s.get("step") or s.get("phase") or s.get("name") or "Step"
        s.setdefault("phase", s["step"])
        s.setdefault("shifted", s.get("risk") in ("medium", "high") and bool(s.get("note")))
    return plan


async def make_plan(task: str, role: str, memories: list[dict]) -> tuple[dict, str, str | None]:
    """Returns (plan, source, error). source is "ollama" or "fallback"."""
    baseline = rule_based_plan(task, role, [])
    if LLM_MODE != "fallback":
        try:
            return normalize_steps(await ollama_plan(task, role, memories, baseline)), "ollama", None
        except Exception as e:
            if LLM_MODE == "ollama":
                raise
            err = f"{type(e).__name__}: {e}"[:200]
    else:
        err = None
    return normalize_steps(rule_based_plan(task, role, memories)), "fallback", err
