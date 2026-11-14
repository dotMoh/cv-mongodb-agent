"""End-to-end demo without the UI:  python -m agent.demo  (from the repo root)."""
from pathlib import Path

from . import chat, governance as g, lesson_gen, recommender, risk, schedule_parser, schedules
from .embeddings import mode

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = next((p for p in (ROOT / "data" / "samples" / "u4_outage_24h.csv", ROOT / "samples" / "u4_outage_24h.csv",
                           ROOT / "agent" / "samples" / "u4_outage_24h.csv") if p.exists()), None)
ACTUALS = SAMPLE.with_name("u4_actuals.csv") if SAMPLE else None


def show(report, n=4):
    o = report["overall"]
    print(f"  overall {o['risk_pct']}% {o['classification']} ({o['confidence']}), hidden by policy: {report['hidden_by_policy']}")
    for r in report["tasks"][:n]:
        ls = ", ".join(f"{m['lesson_id']} v{m['version']} ({m['similarity']:.2f})" for m in r["matches"][:3])
        print(f"  {r['task_id']} {r['task_name'][:40]:40} {r['risk_pct']:>3}% {r['classification']:6} {ls or r['message']}")


def main():
    import sys

    from . import config
    readonly = "--readonly" in sys.argv
    print(f"embeddings: {mode()}  data: {config.DATA_SOURCE}  {'(read-only check)' if readonly else ''}")
    parsed = schedule_parser.parse(SAMPLE)
    print(f"1. Parsed {SAMPLE.name}: {parsed['summary']}; ambiguities: {len(parsed['ambiguities'])}")
    tasks = parsed["tasks"]
    if readonly:
        for user in ("planner_07", "contractor_02", "lead_01"):
            vis = g.visible_lessons(user)
            print(f"   {user}: sees {len(vis['lessons'])} approved lessons, {vis['hidden_count']} hidden by policy")
        print("2. Planner risk assessment:"); show(risk.assess("planner_07", tasks))
        print("Read-only check done (only audit entries were written).")
        return
    base = schedules.save_baseline("planner_07", "U4 24h outage", tasks)
    rep = risk.assess("planner_07", tasks)
    print("2. Planner risk assessment:"); show(rep)
    recs = recommender.recommend("planner_07", tasks, rep)
    for r in recs[:4]:
        print(f"   {r['rec_id']} {r['type']:16} {r['task_name'][:30]:30} {r['risk_before_pct']}% -> {r['risk_after_pct']}% "
              f"({r['duration_impact_hours']:+g}h)")
    top_task = recs[0]["task_id"] if recs else None
    v2 = recommender.apply("planner_07", base["schedule_id"],
                           {r["rec_id"]: "accept" for r in recs if r["task_id"] == top_task})
    print(f"3. Accepted changes for {top_task}: schedule v{v2['version']} (baseline v1 untouched)")
    show(risk.assess("planner_07", v2["tasks"]), 3)
    print("4. Contractor view:"); show(risk.assess("contractor_02", tasks), 2)
    try:
        g.approve("contractor_02", "L-0007")
    except g.PermissionDenied as e:
        print(f"   contractor approve denied and logged: {e}")
    print("5. Lead corrects L-0007:")
    new = g.correct("lead_01", "L-0007", {"delay_days": 3.0, "recommendation": "Fit-check probes on the actual tube pitch the shift before."},
                    reason="2027 completion data: probe fit issue also seen on U4")
    print(f"   now v{new['version']}; history: {[(v['version'], v['status']) for v in g.history('lead_01', 'L-0007')]}")
    if ACTUALS and ACTUALS.exists():
        drafts = lesson_gen.generate("planner_07", tasks, ACTUALS)
        print(f"6. Auto-generated {len(drafts)} draft lessons: {[(d['lesson_id'], d['title']) for d in drafts]}")
        if drafts:
            g.approve("lead_01", drafts[0]["lesson_id"])
            print(f"   lead approved {drafts[0]['lesson_id']}")
    ans = chat.ask("planner_07", "What are the biggest risks in this outage?", tasks, rep, recs)
    print(f"7. Ask ({ans['source']}):\n{ans['answer'][:600]}")
    print("8. Audit log (latest 5):")
    for e in g.audit_log(5):
        print(f"   {e['ts']:%H:%M:%S} {e['user_id']:13} {e['action']:16} {e.get('lesson_id') or '':7} {'ok' if e['allowed'] else 'DENIED'}")


if __name__ == "__main__":
    main()
