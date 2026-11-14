"""Per-task repeat risk from approved, policy-visible lessons. Scores are indicative estimates, never invented."""
from __future__ import annotations

from . import governance

NO_MATCH_MESSAGE = "No sufficiently similar historical outage lessons found."
TOP_K = 5
SIM_WEIGHT = 0.85          # one perfect match alone gives 85% repeat probability
NON_CRITICAL_WEIGHT = 0.6  # off-critical-path tasks matter less to the outage


def classify(pct: float) -> str:
    return "High" if pct >= 60 else "Medium" if pct >= 30 else "Low" if pct > 0 else "None"


def confidence(n: int) -> str:
    return "indicative" if n < 2 else "moderate" if n <= 3 else "supported"


def task_query(t: dict) -> str:
    return " ".join(str(x) for x in (t.get("name"), t.get("unit"), t.get("equipment"), t.get("discipline")) if x)


def successors(tasks: list[dict], task_id: str) -> list[str]:
    """All tasks downstream of task_id through predecessor links."""
    kids = {}
    for t in tasks:
        for p in t.get("predecessors") or []:
            kids.setdefault(p, []).append(t["id"])
    out, stack = [], list(kids.get(task_id, []))
    while stack:
        k = stack.pop(0)
        if k not in out:
            out.append(k)
            stack += kids.get(k, [])
    return out


def assess_task(user_id: str, t: dict, tasks: list[dict], _seen: dict | None = None) -> dict:
    res = governance.retrieve(user_id, task_query(t), k=TOP_K, log=False)
    if _seen is not None:
        for l in res["lessons"]:
            _seen["used"].setdefault(l["lesson_id"], l["version"])
        for lid in res["hidden_ids"]:
            _seen["hidden"].add(lid)
    matches = [{"lesson_id": l["lesson_id"], "version": l["version"], "title": l.get("title"),
                "similarity": round(l["similarity"], 3), "delay_days": float(l.get("delay_days") or 0),
                "category": l.get("category"), "unit": l.get("unit"), "recommendation": l.get("recommendation"),
                "sensitivity": l.get("sensitivity")} for l in res["lessons"]]
    base = {"task_id": t["id"], "task_name": t.get("name"), "critical": bool(t.get("critical")),
            "knock_on": successors(tasks, t["id"]), "hidden_matches": res["hidden_count"]}
    if not matches:
        return dict(base, risk_pct=0, classification="None", repeat_probability_pct=0, delay_exposure_days=None,
                    similarity=None, confidence=None, matches=[], evidence=[], explanation=NO_MATCH_MESSAGE,
                    mitigation=None, message=NO_MATCH_MESSAGE)
    # Cite the most consequential lesson first: similarity x delay (L-0007's 2.5 days beats a closer 0.5-day lesson).
    matches.sort(key=lambda m: m["similarity"] * max(m["delay_days"], 0.1), reverse=True)
    p_none = 1.0
    for m in matches:
        p_none *= 1 - m["similarity"] * SIM_WEIGHT
    repeat = 1 - p_none
    wsum = sum(m["similarity"] for m in matches)
    exposure = sum(m["similarity"] * m["delay_days"] for m in matches) / wsum
    weight = 1.0 if t.get("critical") else NON_CRITICAL_WEIGHT
    residual = 1.0
    for mit in t.get("mitigations") or []:
        residual *= mit.get("residual", 1.0)
    pct = round(min(repeat * weight * residual, 0.99) * 100)
    top = matches[0]
    n = len(matches)
    expl = (f"{n} similar lesson{'s' if n > 1 else ''}; closest: \"{top['title']}\" ({top['unit']}, "
            f"{top['delay_days']:g} d, similarity {top['similarity']:.2f}).")
    if base["knock_on"] and t.get("critical"):
        expl += f" On the critical path: a slip pushes {len(base['knock_on'])} downstream task(s)."
    if residual < 1.0:
        expl += f" Mitigated by {len(t['mitigations'])} accepted change(s) (estimated {round((1 - residual) * 100)}% reduction)."
    return dict(base, risk_pct=pct, classification=classify(pct), repeat_probability_pct=round(repeat * 100),
                mitigated=residual < 1.0,
                delay_exposure_days=round(exposure, 2), similarity=max(m["similarity"] for m in matches), confidence=confidence(n),
                matches=matches, evidence=list(matches), explanation=expl, mitigation=top.get("recommendation"),
                message=None)


def assess(user_id: str, tasks: list[dict]) -> dict:
    seen = {"used": {}, "hidden": set()}
    rows = [assess_task(user_id, t, tasks, seen) for t in tasks]
    rows.sort(key=lambda r: r["risk_pct"], reverse=True)
    for lid, ver in seen["used"].items():
        governance.audit(user_id, "retrieve", lesson_id=lid, version=ver, detail="risk assessment evidence")
    for lid in sorted(seen["hidden"]):
        governance.audit(user_id, "retrieve_denied", allowed=False, lesson_id=lid,
                         detail="matching lesson hidden by policy")
    at_risk = [r for r in rows if r["risk_pct"] > 0]
    # Overall = mean of the three highest-risk critical-path tasks (all tasks if none are critical).
    pool = [r["risk_pct"] for r in rows if r["critical"]] or [r["risk_pct"] for r in rows]
    top3 = sorted(pool, reverse=True)[:3]
    overall = round(sum(top3) / len(top3)) if top3 else 0
    n_lessons = len(seen["used"])
    return {
        "overall": {
            "risk_pct": overall, "classification": classify(overall),
            "confidence": "indicative" if n_lessons < 4 else "moderate" if n_lessons < 8 else "supported",
            "tasks_at_risk": len(at_risk),
            "total_delay_exposure_days": round(sum((r["repeat_probability_pct"] / 100) * (r["delay_exposure_days"] or 0)
                                                   for r in at_risk if r["critical"]), 2),
            "critical_path_at_risk": any(r["critical"] and r["classification"] in ("Medium", "High") for r in rows),
            "lessons_used": n_lessons,
            "note": "Indicative estimate from similarity to approved lessons, not a validated statistical model. "
                    "Overall = mean of the three highest-risk critical-path tasks.",
        },
        "tasks": rows,
        "hidden_by_policy": len(seen["hidden"]),
    }


def heatmap(tasks: list[dict], report: dict, by: str = "task", bucket_hours: int = 2, top: int = 12) -> dict:
    """Risk over the outage timeline for a heatmap (e.g. plotly go.Heatmap(z=..., x=cols, y=rows)).
    by="task": the riskiest `top` tasks; by="discipline" | "unit" | "contractor": max task risk per group.
    Each cell = risk % of the task(s) active in that time bucket, else 0."""
    from datetime import timedelta

    risk_by_id = {r["task_id"]: r["risk_pct"] for r in report["tasks"]}
    timed = [t for t in tasks if t.get("start") and t.get("end")]
    if not timed:
        return {"rows": [], "cols": [], "z": []}
    t0 = min(t["start"] for t in timed).replace(minute=0, second=0, microsecond=0)
    t1 = max(t["end"] for t in timed)
    cols, cur = [], t0
    while cur < t1:
        cols.append(cur)
        cur += timedelta(hours=bucket_hours)
    if by == "task":
        chosen = sorted(timed, key=lambda t: risk_by_id.get(t["id"], 0), reverse=True)[:top]
        chosen.sort(key=lambda t: t["start"])
        groups = [(f"{t['id']} {t['name'][:32]}", [t]) for t in chosen]
    else:
        g = {}
        for t in timed:
            g.setdefault(t.get(by) or "(none)", []).append(t)
        groups = sorted(g.items())
    z = []
    for _, members in groups:
        row = []
        for c in cols:
            c_end = c + timedelta(hours=bucket_hours)
            active = [risk_by_id.get(t["id"], 0) for t in members
                      if t["start"] < c_end and (t["end"] > c or (t["end"] == t["start"] and c <= t["start"] < c_end))]
            row.append(max(active) if active else 0)
        z.append(row)
    return {"rows": [label for label, _ in groups], "cols": [c.strftime("%a %H:%M") for c in cols],
            "col_times": cols, "z": z}
