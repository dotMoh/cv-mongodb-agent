"""Run the demo against a RUNNING backend (real Atlas / Ollama). Stdlib only.

  python3 scripts/smoke_live.py                               # localhost:8000, unit-3
  python3 scripts/smoke_live.py --api http://10.0.0.5:8000 --plant lakeshore-3
  python3 scripts/smoke_live.py --learn                       # also POSTs the correction (changes the DB!)

Prints what the demo will show and exits non-zero if the demo beat is missing.
"""
import argparse
import json
import sys
import urllib.request

TASK = "Plan July maintenance outage for Unit 3"
FIX = "Intake chiller retrofit done in 2025: July intake temps now safe for full outage"


def call(api, method, path, body=None):
    req = urllib.request.Request(api + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def show(label, plan):
    # Pre-outage notice steps sit 14 days ahead; the outage itself starts at the first real phase.
    starts = sorted(s["start"] for s in plan["schedule"] if not str(s.get("step", "")).startswith("Notify"))
    print(f"\n== {label}: source={plan.get('source')} {plan.get('elapsed_ms')}ms  first start {starts[0] if starts else '?'}")
    print("   ", plan.get("summary", ""))
    for m in plan["memories_used"][:5]:
        print(f"    [{m.get('score')}] {m['_id']}  {m['content'][:80]}")
    if plan.get("llm_error"):
        print("    LLM fell back:", plan["llm_error"])
    return starts[0] if starts else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--plant", default="unit-3")
    ap.add_argument("--role", default="planner")
    ap.add_argument("--learn", action="store_true", help="POST the correction and re-plan")
    a = ap.parse_args()

    ok = True
    print("health:", call(a.api, "GET", "/health"))
    body = {"task": TASK, "role": a.role, "plant_id": a.plant}
    before = call(a.api, "POST", "/plan", body)
    start = show("before", before)
    if not before["memories_used"]:
        print("FAIL: no memories recalled. Wrong plant_id, index name, or index still building?")
        return 1
    if not before["heat_points"]:
        print("WARN: no heat_points, the map will be empty")
    if "-07-" in start:
        print("FAIL: plan still starts in July; no memory moved it")
        ok = False
    cited = [x["memory_id"] for x in before.get("adjustments", []) if x.get("memory_id")]
    target = cited[0] if cited else before["memories_used"][0]["_id"]
    print("memory to correct in the demo:", target)

    if a.learn:
        learned = call(a.api, "POST", "/learn", {"content": FIX, "plant_id": a.plant, "corrects_id": target})
        print("learn:", learned)
        after = call(a.api, "POST", "/plan", body)
        start2 = show("after", after)
        if target in [m["_id"] for m in after["memories_used"]]:
            print("FAIL: corrected memory still returned (status filter not applied?)")
            ok = False
        if "-07-" not in start2:
            print("WARN: plan did not return to July. Other heat memories for this plant may still be pulling it earlier.")
    print("\nOK" if ok else "\nDEMO BEAT MISSING")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
