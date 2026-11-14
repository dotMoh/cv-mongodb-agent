"""Outage Router server: serves the page in this folder and exposes a tiny JSON API over agent/.

Run from the repo root:   python frontend/server.py      then open http://localhost:8000
Standard library only (plus whatever agent/ needs). It only calls existing agent/ functions.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import uuid
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # repo root, so `import agent` works
from agent import chat, governance, recommender, risk, schedule_parser, schedules  # noqa: E402

USERS = {"planner_07": "Planner", "contractor_02": "Contractor", "lead_01": "Lead"}
SAMPLE = HERE / "sample" / "u4_outage_24h.csv"
# Illustrative positions for the station's units on the Lake Ontario shore (lat, lon).
UNIT_COORDS = {"U1": (43.8128, -79.0742), "U2": (43.8113, -79.0706), "U3": (43.8098, -79.0668),
               "U4": (43.8084, -79.0631), "U5": (43.8069, -79.0594)}
CAT_OFFSET = {"tooling": (0.0005, 0.0004), "permits": (-0.0004, 0.0005), "access": (0.0004, -0.0005),
              "resources": (-0.0005, -0.0003), "parts": (0.0001, 0.0008), "weather": (0.0008, -0.0001),
              "sequencing": (-0.0008, 0.0001), "rework": (-0.0001, -0.0008)}
SESSIONS: dict[str, dict] = {}  # token -> {"tasks", "file", "summary", "ambiguities"}


def _user(u):
    return u if u in USERS else "planner_07"


def heat_points(user_id, tasks=None, report=None):
    """[[lat, lon, weight 0..1, label]] from approved lessons the role may see, plus risky planned tasks."""
    pts = []
    for l in governance.visible_lessons(user_id)["lessons"]:
        d = float(l.get("delay_days") or 0)
        if l.get("status") == "approved" and l.get("unit") in UNIT_COORDS and d > 0:
            la, lo = UNIT_COORDS[l["unit"]]
            dla, dlo = CAT_OFFSET.get(l.get("category"), (0, 0))
            pts.append([la + dla, lo + dlo, min(1.0, 0.3 + d / 2), f"{l['unit']}: {l['title']} ({d:g} d)"])
    if tasks and report:
        rmap = {r["task_id"]: r["risk_pct"] for r in report["tasks"]}
        for t in tasks:
            if rmap.get(t["id"]) and t.get("unit") in UNIT_COORDS:
                la, lo = UNIT_COORDS[t["unit"]]
                pts.append([la, lo, rmap[t["id"]] / 100, f"Planned: {t['name']} ({rmap[t['id']]}% risk)"])
    return pts


def analysis(token, user_id):
    s = SESSIONS[token]
    rep = risk.assess(user_id, s["tasks"])
    top = []
    for r in [r for r in rep["tasks"] if r["risk_pct"] > 0][:5]:
        m = r["matches"][0] if r["matches"] else None
        top.append({"task": r["task_name"], "risk_pct": r["risk_pct"], "classification": r["classification"],
                    "delay_days": r["delay_exposure_days"], "lessons": len(r["matches"]),
                    "cite": f"{m['lesson_id']} v{m['version']}: {m['title']}" if m else "",
                    "mitigation": r["mitigation"]})
    return {"token": token, "file": s["file"], "summary": s["summary"], "ambiguities": s["ambiguities"],
            "overall": rep["overall"], "risks": top, "hidden": rep.get("hidden_by_policy", 0),
            "heat": heat_points(user_id, s["tasks"], rep)}


def analyze_file(data: bytes, name: str, user_id: str):
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
    return analysis(token, user_id)


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
        self.end_headers()
        self.wfile.write(data)

    def _err(self, e, code=400):
        self._send(code, {"error": str(e) or e.__class__.__name__})

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/heat":
            return self._send(200, {"heat": heat_points(_user(q.get("user")))})
        if url.path == "/api/sample":
            try:
                return self._send(200, analyze_file(SAMPLE.read_bytes(), SAMPLE.name, _user(q.get("user"))))
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
            if url.path == "/api/analyze":  # raw file bytes in the body, ?name=file.pdf&user=planner_07
                return self._send(200, analyze_file(body, q.get("name", "upload.csv"), _user(q.get("user"))))
            data = json.loads(body or b"{}")
            token, user_id = data.get("token"), _user(data.get("user"))
            if token not in SESSIONS:
                return self._err("Upload a schedule first.")
            if url.path == "/api/reassess":
                return self._send(200, analysis(token, user_id))
            if url.path == "/api/ask":
                tasks = SESSIONS[token]["tasks"]
                rep = risk.assess(user_id, tasks)
                a = chat.ask(user_id, data.get("question", ""), tasks, rep, recommender.recommend(user_id, tasks, rep))
                return self._send(200, {"answer": a["answer"], "lessons_cited": a.get("lessons_cited", [])})
            self._send(404, {"error": "unknown endpoint"})
        except governance.PermissionDenied as e:
            self._err(e, 403)
        except Exception as e:  # parse problems etc. go back to the page as a readable message
            self._err(e)

    def log_message(self, fmt, *args):
        pass


def make_server(port: int = 8000, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Build the server without starting it (tests can use port 0 and serve_forever in a thread)."""
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Outage Router on http://localhost:{port}  (Ctrl+C to stop)")
    make_server(port).serve_forever()
