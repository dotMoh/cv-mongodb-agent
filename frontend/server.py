"""Outage Router server: serves the page in this folder and exposes a small JSON API over agent/.

Run from the repo root:   python frontend/server.py      then open http://localhost:8000
Standard library only (plus whatever agent/ needs). It only calls existing agent/ functions.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import mimetypes
import os
import sys
import threading
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # repo root, so `import agent` works
from agent import chat, config, governance, recommender, risk, schedule_parser, schedules, store  # noqa: E402
from agent.embeddings import mode as embed_mode  # noqa: E402

USERS = {"planner_07": "Planner", "contractor_02": "Contractor", "lead_01": "Lead"}
SAMPLE = HERE / "sample" / "u4_outage_24h.csv"
SESSIONS: dict[str, dict] = {}  # token -> {"tasks", "file", "summary", "ambiguities"}
LOCK = threading.RLock()        # one agent call at a time (the demo store is not thread-safe)

# ---------------------------------------------------------------- plant model
# The page draws four reactor units side by side. Each lesson or task lands in a zone of its unit,
# in page coordinates 0..1 (x across, y down). Must match the drawing in app.js.
UNIT_X = {"U1": 0.125, "U2": 0.375, "U3": 0.625, "U4": 0.875}
ZONE_POS = {  # (dx from unit centre, y)
    "reactor": (0.0, 0.27),
    "hx": (-0.075, 0.47),
    "piping": (0.06, 0.52),
    "electrical": (0.075, 0.88),
    "turbine": (-0.02, 0.76),
}
ZONE_WORDS = [
    ("hx", ("hx", "heat exchanger", "tube", "channel head", "eddy", "scaffold", "boiler")),
    ("turbine", ("turbine", "crane", "bearing", "generator")),
    ("electrical", ("switchgear", "electrical", "transformer", "isolation", "breaker", "cable")),
    ("piping", ("mv-", "valve", "pump", "p-3", "feedwater", "steam line", "hydrotest", "drain", "vent", "weld",
                "insulation", "seal", "pipe")),
    ("reactor", ("reactor", "shutdown", "startup", "restart", "cooldown", "fuel", "restoration")),
]


def zone_of(*texts) -> str:
    text = " ".join(str(t or "") for t in texts).lower()
    for zone, words in ZONE_WORDS:
        if any(w in text for w in words):
            return zone
    return "reactor"


def _jitter(key: str, spread: float = 0.035):
    h = hashlib.md5(key.encode()).digest()
    return (h[0] / 255 - 0.5) * spread, (h[1] / 255 - 0.5) * spread


def plant_xy(unit, zone, key):
    dx, y = ZONE_POS[zone]
    jx, jy = _jitter(key)
    return round(UNIT_X[unit] + dx + jx, 4), round(y + jy, 4)


def _user(u):
    return u if u in USERS else "planner_07"


def _role(user_id):
    return governance.USERS[user_id]


def _bool(v, default=True):
    if v is None:
        return default
    return str(v).lower() not in ("0", "false", "off", "no")


# ---------------------------------------------------------------- memory on / off
_HAS_FLAG = "use_memory" in inspect.signature(risk.assess).parameters


@contextmanager
def _no_retrieval():
    """Only for an agent/ without risk.assess(use_memory=...): retrieval returns nothing."""
    real = governance.retrieve
    governance.retrieve = lambda *a, **k: {"lessons": [], "hidden_count": 0, "hidden_ids": []}
    try:
        yield
    finally:
        governance.retrieve = real


def assess(user_id, tasks, memory=True):
    if memory:
        return risk.assess(user_id, tasks)
    if _HAS_FLAG:
        return risk.assess(user_id, tasks, use_memory=False)
    with _no_retrieval():
        return risk.assess(user_id, tasks)


# ---------------------------------------------------------------- heat
def heat_points(user_id, tasks=None, report=None, memory=True):
    """[[x, y, weight 0..1, label, kind]] on the plant drawing.
    Past failures: approved lessons this role may read (policy applied, not audited: it is only a picture).
    Planned: tasks in this schedule weighted by their risk."""
    pts = []
    if memory:
        role = _role(user_id)
        for l in governance._current_versions():
            d = float(l.get("delay_days") or 0)
            if l.get("status") != "approved" or l.get("unit") not in UNIT_X or d <= 0 or not governance.can_read(role, l):
                continue
            x, y = plant_xy(l["unit"], zone_of(l.get("equipment"), l.get("job_type"), l.get("title")), l["lesson_id"])
            pts.append([x, y, round(min(1.0, 0.25 + d / 3), 3),
                        f"{l['lesson_id']} v{l['version']} {l['unit']}: {l.get('title')} ({d:g} d delay)", "past"])
    if tasks and report:
        rmap = {r["task_id"]: r["risk_pct"] for r in report["tasks"]}
        for t in tasks:
            if rmap.get(t["id"]) and t.get("unit") in UNIT_X:
                x, y = plant_xy(t["unit"], zone_of(t.get("name"), t.get("discipline")), t["id"])
                pts.append([x, y, round(rmap[t["id"]] / 100, 3), f"Planned {t['id']}: {t['name']} ({rmap[t['id']]}% risk)",
                            "planned"])
    return pts


def unit_risk(tasks, report):
    out = {}
    if not (tasks and report):
        return out
    rmap = {r["task_id"]: r["risk_pct"] for r in report["tasks"]}
    for t in tasks:
        if t.get("unit") in UNIT_X:
            out[t["unit"]] = max(out.get(t["unit"], 0), rmap.get(t["id"], 0))
    return out


# ---------------------------------------------------------------- analysis
def _top(rep, n=5):
    top = []
    for r in [r for r in rep["tasks"] if r["risk_pct"] > 0][:n]:
        m = r["matches"][0] if r["matches"] else None
        top.append({"task": r["task_name"], "risk_pct": r["risk_pct"], "classification": r["classification"],
                    "delay_days": r["delay_exposure_days"], "lessons": len(r["matches"]),
                    "cite": f"{m['lesson_id']} v{m['version']}: {m['title']}" if m else "",
                    "mitigation": r["mitigation"]})
    return top


def _short(o):
    return {k: o.get(k) for k in ("risk_pct", "classification", "tasks_at_risk", "total_delay_exposure_days",
                                  "lessons_used")}


def analysis(token, user_id, memory=True):
    s = SESSIONS[token]
    on = assess(user_id, s["tasks"], True)
    off = assess(user_id, s["tasks"], False)
    rep = on if memory else off
    off_by_id = {r["task_id"]: r["risk_pct"] for r in off["tasks"]}
    compare = {"on": _short(on["overall"]), "off": _short(off["overall"]),
               "tasks": [{"task": r["task_name"], "on": r["risk_pct"], "off": off_by_id.get(r["task_id"], 0),
                          "cite": f"{r['matches'][0]['lesson_id']} v{r['matches'][0]['version']}" if r["matches"] else ""}
                         for r in on["tasks"][:6]]}
    overall = dict(rep["overall"])
    if not memory:
        overall["note"] = "Memory off: retrieval disabled, no past lessons were consulted, so nothing can be flagged."
    return {"token": token, "file": s["file"], "summary": s["summary"], "ambiguities": s["ambiguities"],
            "memory": memory, "overall": overall, "risks": _top(rep), "hidden": rep.get("hidden_by_policy", 0),
            "compare": compare, "heat": heat_points(user_id, s["tasks"], rep, memory),
            "units": unit_risk(s["tasks"], rep)}


def analyze_file(data: bytes, name: str, user_id: str, memory=True):
    parsed = schedule_parser.parse(data, name)
    tasks = [t for t in parsed["tasks"] if t.get("start") and t.get("end")]
    if not tasks:
        raise ValueError("Could not find task names with start and end times in this file.")
    try:  # saving a baseline is a planner/lead action; read-only roles still get the analysis
        tasks = schedules.save_baseline(user_id, Path(name).stem.replace("_", " "), tasks)["tasks"]
    except governance.PermissionDenied:
        pass
    token = uuid.uuid4().hex[:12]
    SESSIONS[token] = {"tasks": tasks, "file": name, "summary": parsed["summary"],
                       "ambiguities": [a["message"] if not a.get("row") else f"Row {a['row']}: {a['message']}"
                                       for a in parsed.get("ambiguities", [])]}
    return analysis(token, user_id, memory)


# ---------------------------------------------------------------- governance views
LESSON_KEYS = ("lesson_id", "version", "status", "title", "issue", "recommendation", "unit", "equipment", "category",
               "delay_days", "sensitivity", "created_by", "approved_by", "change_reason")


def lesson_row(l):
    row = {k: l.get(k) for k in LESSON_KEYS}
    row["days_to_expiry"] = governance.days_to_expiry(l)
    return row


def lessons_view(user_id):
    v = governance.visible_lessons(user_id, include_drafts=True)
    rows = [lesson_row(l) for l in v["lessons"]]
    order = {"draft": 0, "approved": 1}
    rows.sort(key=lambda r: (order.get(r["status"], 2), r["lesson_id"]))
    return {"lessons": rows, "hidden": v["hidden_count"], "can": sorted(governance.ACTIONS[_role(user_id)])}


def audit_view(user_id, limit=25):
    lead = "history_all" in governance.ACTIONS[_role(user_id)]
    rows = [e for e in governance.audit_log(400) if lead or e.get("user_id") == user_id][:limit]
    return {"entries": [{k: e.get(k) for k in ("ts", "user_id", "role", "action", "lesson_id", "version", "allowed",
                                                "detail")} for e in rows], "scope": "everyone" if lead else "you"}


def llm_status():
    provider = getattr(config, "LLM_PROVIDER", "ollama")
    if provider in ("anthropic", "claude"):  # newer agent/: Claude API instead of a local model
        import os as _os
        return {"mode": config.LLM_MODE, "provider": "anthropic", "model": getattr(config, "ANTHROPIC_MODEL", "Claude"),
                "reachable": config.LLM_MODE != "fallback" and bool(_os.getenv("ANTHROPIC_API_KEY"))}
    info = {"mode": config.LLM_MODE, "provider": "ollama", "model": config.OLLAMA_MODEL, "reachable": False}
    if config.LLM_MODE == "fallback":
        return info
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=1.5) as r:
            names = [m.get("name") for m in json.loads(r.read()).get("models", [])]
        info["reachable"] = True
        info["installed"] = config.OLLAMA_MODEL in names or any(n and n.split(":")[0] == config.OLLAMA_MODEL for n in names)
    except Exception:
        pass
    return info


def status():
    return {"data_source": config.DATA_SOURCE, "embeddings": embed_mode(), "llm": llm_status(),
            "can_reset": config.DATA_SOURCE != "mongo"}


EDITABLE = ("title", "issue", "recommendation", "delay_days", "unit", "category", "sensitivity")


def lesson_action(path, data, user_id):
    lid = data.get("lesson_id")
    if path == "/api/lesson/add":
        f = {k: data.get(k) for k in EDITABLE if data.get(k) not in (None, "")}
        doc = governance.add_lesson(user_id, f)
        return {"ok": f"Added {doc['lesson_id']} as a draft. It expires in {config.DRAFT_EXPIRY_DAYS} days unless a lead approves it."}
    if path == "/api/lesson/approve":
        d = governance.approve(user_id, lid)
        return {"ok": f"Approved {lid} v{d['version']}. It is now used in risk assessments."}
    if path == "/api/lesson/correct":
        changes = {k: v for k, v in (data.get("changes") or {}).items() if k in EDITABLE and v not in (None, "")}
        if "delay_days" in changes:
            changes["delay_days"] = float(changes["delay_days"])
        d = governance.correct(user_id, lid, changes, data.get("reason", ""))
        return {"ok": f"Corrected {lid}: v{d['version']} is current, v{d['version'] - 1} is kept as superseded."}
    if path == "/api/lesson/forget":
        governance.forget(user_id, lid, confirm=bool(data.get("confirm")), reason=data.get("reason", ""))
        return {"ok": f"Forgot {lid}. Retrieval will never return it again."}
    raise KeyError(path)


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=_json_default).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, e, code=400):
        msg = str(e) or e.__class__.__name__
        if isinstance(e, KeyError):
            msg = f"Not found: {msg.strip(chr(39))}"
        self._send(code, {"error": msg})

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        user_id, memory = _user(q.get("user")), _bool(q.get("memory"))
        api = {
            "/api/heat": lambda: {"heat": heat_points(user_id, memory=memory)},
            "/api/sample": lambda: analyze_file(SAMPLE.read_bytes(), SAMPLE.name, user_id, memory),
            "/api/lessons": lambda: lessons_view(user_id),
            "/api/audit": lambda: audit_view(user_id, int(q.get("limit", 25))),
            "/api/history": lambda: {"versions": [lesson_row(l) for l in governance.history(user_id, q.get("lesson_id", ""))]},
            "/api/status": status,
        }
        if url.path in api:
            try:
                with LOCK:
                    return self._send(200, api[url.path]())
            except governance.PermissionDenied as e:
                return self._err(e, 403)
            except Exception as e:
                return self._err(e)
        path = (HERE / (url.path.lstrip("/") or "index.html")).resolve()
        if HERE not in path.parents and path != HERE or not path.is_file() or path.suffix == ".py":
            return self._send(404, b"Not found", "text/plain")
        self._send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if url.path == "/api/ask":  # the LLM can be slow, so only the risk lookup holds the lock
                data = json.loads(body or b"{}")
                user_id, memory, token = _user(data.get("user")), _bool(data.get("memory")), data.get("token")
                if token not in SESSIONS:
                    return self._err("Upload a schedule first.")
                tasks = SESSIONS[token]["tasks"]
                with LOCK:
                    rep = assess(user_id, tasks, memory)
                    recs = recommender.recommend(user_id, tasks, rep)
                a = chat.ask(user_id, data.get("question", ""), tasks, rep, recs)
                return self._send(200, {"answer": a["answer"], "lessons_cited": a.get("lessons_cited", []),
                                        "source": a.get("source", "fallback"), "memory": memory})
            with LOCK:
                if url.path == "/api/analyze":  # raw file bytes in the body, ?name=file.pdf&user=planner_07
                    return self._send(200, analyze_file(body, q.get("name", "upload.csv"), _user(q.get("user")),
                                                        _bool(q.get("memory"))))
                data = json.loads(body or b"{}")
                user_id, memory = _user(data.get("user")), _bool(data.get("memory"))
                if url.path.startswith("/api/lesson/"):
                    return self._send(200, lesson_action(url.path, data, user_id))
                if url.path == "/api/reset":
                    if config.DATA_SOURCE == "mongo":
                        return self._err("Reset only works on mock data. Reseed Atlas with data/seed_governed.py.")
                    store.reset()
                    return self._send(200, {"ok": "Demo data restored to the seed lessons."})
                token = data.get("token")
                if token not in SESSIONS:
                    return self._err("Upload a schedule first.")
                if url.path == "/api/reassess":
                    return self._send(200, analysis(token, user_id, memory))
                self._send(404, {"error": "unknown endpoint"})
        except governance.PermissionDenied as e:
            self._err(e, 403)
        except Exception as e:  # parse problems, refused actions etc. go back to the page as a readable message
            self._err(e)

    def log_message(self, fmt, *args):
        pass


def make_server(port: int = 8000, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Build the server without starting it (tests can use port 0 and serve_forever in a thread)."""
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    s = status()
    llm = s["llm"]
    chat_mode = (f"{'Claude' if llm['provider'] == 'anthropic' else 'Ollama'} {llm['model']}" if llm["reachable"] else
                 "rule-based fallback (LLM_MODE=fallback)" if llm["mode"] == "fallback" else
                 "rule-based fallback (ANTHROPIC_API_KEY not set)" if llm["provider"] == "anthropic" else
                 f"rule-based fallback (Ollama not reachable at {config.OLLAMA_URL})")
    print(f"Outage Router on http://localhost:{port}  (Ctrl+C to stop)")
    print(f"  data: {s['data_source']}   embeddings: {s['embeddings']}   chat: {chat_mode}")
    if s["data_source"] == "mongo" and s["embeddings"] != "minilm":
        print("  WARNING: Atlas lessons use MiniLM vectors but sentence-transformers is not installed here, "
              "so matches will be meaningless. Install it or use DATA_SOURCE=mock.")
    make_server(port).serve_forever()
