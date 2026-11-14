"""Answer questions about the uploaded schedule from the risk report and recommendations."""
from __future__ import annotations

import json
import re

from . import llm

SYSTEM = ("You are an outage planning agent for a power station. Answer the planner's question using ONLY the "
          "schedule risks, recommendations and lessons given. Cite lessons as L-xxxx vN. If the evidence does not "
          "answer the question, say so. Never invent lessons, numbers or past events. Be concise, no emojis.")


def _context(tasks, report, recommendations):
    risks = [{k: r[k] for k in ("task_id", "task_name", "risk_pct", "classification", "delay_exposure_days",
                                "confidence", "critical", "knock_on", "explanation")}
             | {"lessons": [f"{m['lesson_id']} v{m['version']}: {m['title']}" for m in r["matches"]]}
             for r in report["tasks"] if r["matches"]][:10]
    recs = [{k: r[k] for k in ("rec_id", "task_id", "type", "reason", "risk_before_pct", "risk_after_pct",
                               "duration_impact_hours")} for r in (recommendations or [])][:10]
    return json.dumps({"overall": report["overall"], "hidden_by_policy": report.get("hidden_by_policy", 0),
                       "task_risks": risks, "recommendations": recs}, default=str)


def _cited(report, text):
    ids = set(re.findall(r"L-\d{4}", text))
    out = []
    for r in report["tasks"]:
        for m in r["matches"]:
            if m["lesson_id"] in ids and m["lesson_id"] not in [o["lesson_id"] for o in out]:
                out.append({"lesson_id": m["lesson_id"], "version": m["version"], "title": m["title"]})
    return out


def _fallback(question, tasks, report, recommendations):
    q = question.lower()
    risky = [r for r in report["tasks"] if r["matches"]]
    names = {t["id"]: t["name"] for t in tasks}
    if not risky:
        return "No sufficiently similar historical outage lessons found for this schedule."
    def line(r):
        ls = ", ".join(f"{m['lesson_id']} v{m['version']}" for m in r["matches"][:2])
        return (f"- {r['task_name']}: {r['risk_pct']}% ({r['classification']}, {r['confidence']}), "
                f"~{r['delay_exposure_days']:g} d exposure. Evidence: {ls}.")
    if any(w in q for w in ("recommend", "change", "reduce", "improve", "shorten")):
        if not recommendations:
            return "No changes recommended: no task is above the risk threshold."
        return "Recommended changes:\n" + "\n".join(
            f"- {r['task_name']}: {r['reason']} (risk {r['risk_before_pct']}% to {r['risk_after_pct']}%, "
            f"{r['duration_impact_hours']:+g}h on outage length)" for r in recommendations[:6])
    if "critical" in q:
        crit = [r for r in risky if r["critical"]][:5]
        if not crit:
            return "No critical-path task matched a historical lesson."
        return "Critical-path tasks with repeat risk:\n" + "\n".join(line(r) for r in crit)
    m = re.search(r"\b(U\d)\b", question, re.I)
    words = [w for w in re.findall(r"[a-z]{4,}", q) if w not in ("could", "previous", "affected", "outage", "delays", "have", "experienced", "similar", "problems", "with", "what", "which", "biggest")]
    focus = [r for r in risky if any(w in (r["task_name"] or "").lower() for w in words)]
    if any(w in q for w in ("similar", "before", "previous", "experienced", "history")) or focus:
        rows = focus or risky[:5]
        return "Matching past lessons:\n" + "\n".join(
            f"- {r['task_name']} ← " + "; ".join(f"{x['lesson_id']} v{x['version']} ({x['unit']}): {x['title']} "
                                                  f"[similarity {x['similarity']:.2f}]" for x in r["matches"][:3])
            for r in rows)
    o = report["overall"]
    return (f"Overall outage risk {o['risk_pct']}% ({o['classification']}, {o['confidence']}). Highest risks:\n"
            + "\n".join(line(r) for r in risky[:5])
            + ("\n" + f"{report['hidden_by_policy']} matching lessons are hidden by your access policy."
               if report.get("hidden_by_policy") else ""))


def ask(user_id: str, question: str, tasks: list[dict], report: dict, recommendations: list[dict] | None = None) -> dict:
    ctx = _context(tasks, report, recommendations)
    text = llm.chat(SYSTEM, f"Context (JSON):\n{ctx}\n\nQuestion: {question}")
    source = llm.provider()
    if not text:
        text, source = _fallback(question, tasks, report, recommendations), "fallback"
    return {"answer": text, "lessons_cited": _cited(report, text), "source": source}
