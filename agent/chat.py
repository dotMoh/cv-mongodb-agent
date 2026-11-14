"""Answer questions about the uploaded schedule from the risk report and recommendations."""
from __future__ import annotations

import json
import re

from . import governance, llm

SECTIONS = ("Relevant Lessons", "What The Conclusion Does or Does Not Show (Context)",
            "Recommended Mitigations", "Lessons Cited")

SYSTEM = ("You are an outage planning agent for a power station. Answer the planner's question using ONLY the "
          "schedule risks, recommendations, lessons and lesson chains given. Cite lessons as L-xxxx vN. If the "
          "evidence does not answer the question, say so. Never invent lessons, numbers or past events. "
          "Be concise, no emojis.\n\n"
          "lesson_chains come from a lesson graph: each seed lesson is followed by lessons linked to it "
          "(caused_by, led_to, same_root_cause) up to two hops away. Use them to explain chains of events, e.g. "
          "'L-0005 v1 led to L-0007 v2', and only claim a link that is listed.\n\n"
          "Format the answer in Markdown with exactly these four headers, in this order, each as a line "
          "starting with '## ':\n"
          "## Relevant Lessons\n(short bullets: lesson, unit, what happened, and linked lessons in the chain)\n"
          "## What The Conclusion Does or Does Not Show (Context)\n(the direct answer, its confidence, and its "
          "limits, e.g. few matches or lessons hidden by policy)\n"
          "## Recommended Mitigations\n(bullets from the recommendations and lesson recommendations)\n"
          "## Lessons Cited\n(bullets: L-xxxx vN: title)\n"
          "Put every number in bold, e.g. **78%**, **2.5 days**, **3 lessons**. Use '- ' bullets. "
          "No other headers, no tables.")


def _chains(user_id, question, report):
    """Lesson graph around the riskiest tasks' top lessons and the question itself."""
    if report.get("memory") is False:
        return []
    seeds = []
    for r in report["tasks"]:
        if r["matches"] and r["matches"][0]["lesson_id"] not in seeds:
            seeds.append(r["matches"][0]["lesson_id"])
    chains = governance.lesson_chain(user_id, seed_ids=seeds[:3]) if seeds else []
    have = {c["lesson_id"] for c in chains}
    if question.strip():
        chains += [c for c in governance.lesson_chain(user_id, query=question, k=2) if c["lesson_id"] not in have]
    return [c for c in chains if c["chain"]]


def _chain_ctx(chains):
    short = lambda d: {k: d.get(k) for k in ("lesson_id", "version", "title", "unit", "delay_days", "recommendation")}
    return [dict(short(c), linked=[dict(short(x), link=x["type"], via=x["via"], hops=x["hops"]) for x in c["chain"]])
            for c in chains][:5]


def _context(tasks, report, recommendations, chains=None):
    risks = [{k: r[k] for k in ("task_id", "task_name", "risk_pct", "classification", "delay_exposure_days",
                                "confidence", "critical", "knock_on", "explanation")}
             | {"lessons": [f"{m['lesson_id']} v{m['version']}: {m['title']}" for m in r["matches"]]}
             for r in report["tasks"] if r["matches"]][:10]
    recs = [{k: r[k] for k in ("rec_id", "task_id", "type", "reason", "risk_before_pct", "risk_after_pct",
                               "duration_impact_hours")} for r in (recommendations or [])][:10]
    return json.dumps({"overall": report["overall"], "hidden_by_policy": report.get("hidden_by_policy", 0),
                       "task_risks": risks, "recommendations": recs,
                       "lesson_chains": _chain_ctx(chains or [])}, default=str)


def _cited(report, text, chains=None):
    ids = set(re.findall(r"L-\d{4}", text))
    pool = [m for r in report["tasks"] for m in r["matches"]]
    pool += [x for c in (chains or []) for x in [c] + c["chain"]]
    out = []
    for m in pool:
        if m["lesson_id"] in ids and m["lesson_id"] not in [o["lesson_id"] for o in out]:
            out.append({"lesson_id": m["lesson_id"], "version": m["version"], "title": m["title"]})
    return out


def _num(x):
    return f"**{x:g}**" if isinstance(x, (int, float)) else f"**{x}**"


def _fallback(question, tasks, report, recommendations, chains=None):
    """Rule-based answer in the same four sections as the LLM answer."""
    q = question.lower()
    chains = chains or []
    risky = [r for r in report["tasks"] if r["matches"]]
    o = report["overall"]
    hidden = report.get("hidden_by_policy") or 0
    if report.get("memory") is False:
        risky = []
    stop = {"could", "previous", "affected", "outage", "delays", "have", "experienced", "similar", "problems",
            "with", "what", "which", "biggest", "risk", "risks", "task", "tasks", "this", "schedule", "there"}
    words = [w for w in re.findall(r"[a-z]{4,}", q) if w not in stop]
    if "critical" in q:
        rows = [r for r in risky if r["critical"]][:5]
    else:
        rows = [r for r in risky if any(w in (r["task_name"] or "").lower() for w in words)][:5] or risky[:5]
    by_seed = {c["lesson_id"]: c for c in chains}

    lessons, seen = [], set()
    for r in rows:
        for m in r["matches"][:2]:
            if m["lesson_id"] in seen or len(lessons) >= 6:
                continue
            seen.add(m["lesson_id"])
            line = (f"- {m['lesson_id']} v{m['version']} ({m.get('unit', '')}): {m['title']}, "
                    f"{_num(m.get('delay_days') or 0)} days delay, similarity {_num(round(m['similarity'], 2))} "
                    f"to {r['task_name']}")
            c = by_seed.get(m["lesson_id"])
            if c:
                line += "\n  - Chain: " + "; ".join(f"{x['type'].replace('_', ' ')} {x['lesson_id']} v{x['version']} "
                                                     f"({x['title']})" for x in c["chain"][:4])
            lessons.append(line)
    for c in chains:
        if c["lesson_id"] not in seen and len(lessons) < 7:
            lessons.append(f"- {c['lesson_id']} v{c['version']}: {c['title']}\n  - Chain: " + "; ".join(
                f"{x['type'].replace('_', ' ')} {x['lesson_id']} v{x['version']} ({x['title']})" for x in c["chain"][:4]))
    if not lessons:
        lessons = ["- No sufficiently similar historical outage lessons found for this schedule."
                   if report.get("memory") is not False else "- Memory off: no historical lessons were consulted."]

    ctx = []
    if rows:
        ctx.append(f"Overall outage risk is {_num(o['risk_pct'])}% ({o['classification']}, {o['confidence']}), "
                   f"with {_num(o['tasks_at_risk'])} tasks at risk and about {_num(o['total_delay_exposure_days'])} "
                   f"days of delay exposure.")
        for r in rows[:3]:
            ctx.append(f"- {r['task_name']}: {_num(r['risk_pct'])}% ({r['classification']}), "
                       f"{_num(len(r['matches']))} matching lessons, confidence {r['confidence']}"
                       + (", on the critical path" if r.get("critical") else "")
                       + (f", knock-on to {', '.join(r['knock_on'][:4])}" if r.get("knock_on") else "") + ".")
        ctx.append("It shows these tasks resemble past delays. It does not prove they will repeat: scores are "
                   "indicative and based only on approved lessons you may see.")
    else:
        ctx.append("The evidence does not answer this question: no approved lesson matched the schedule.")
    if hidden:
        ctx.append(f"{_num(hidden)} matching lessons are hidden by your access policy.")

    mit = []
    recs = [x for x in (recommendations or []) if not rows or x["task_id"] in {r["task_id"] for r in rows}] or (recommendations or [])
    for x in recs[:5]:
        mit.append(f"- {x['task_name'] if 'task_name' in x else x['task_id']}: {x['reason']} (risk "
                   f"{_num(x['risk_before_pct'])}% to {_num(x['risk_after_pct'])}%, "
                   f"{'+' if x['duration_impact_hours'] >= 0 else ''}{_num(x['duration_impact_hours'])}h)")
    if not mit:
        mit = [f"- {r['task_name']}: {r['mitigation']}" for r in rows[:3] if r.get("mitigation")] or \
              ["- No changes recommended: no task is above the risk threshold."]

    cited = []
    for m in [m for r in rows for m in r["matches"][:2]] + [x for c in chains for x in [c] + c["chain"][:4]]:
        line = f"- {m['lesson_id']} v{m['version']}: {m['title']}"
        if line not in cited:
            cited.append(line)
    body = [lessons, ctx, mit, cited or ["- None"]]
    return "\n\n".join(f"## {h}\n" + "\n".join(b) for h, b in zip(SECTIONS, body))


def ask(user_id: str, question: str, tasks: list[dict], report: dict, recommendations: list[dict] | None = None) -> dict:
    """Returns {"answer" (Markdown, four ## sections), "lessons_cited", "source", "chains"}."""
    chains = _chains(user_id, question, report)
    ctx = _context(tasks, report, recommendations, chains)
    text = llm.chat(SYSTEM, f"Context (JSON):\n{ctx}\n\nQuestion: {question}")
    source = llm.provider()
    if not text:
        text, source = _fallback(question, tasks, report, recommendations, chains), "fallback"
    return {"answer": text, "lessons_cited": _cited(report, text, chains), "source": source,
            "chains": _chain_ctx(chains)}
