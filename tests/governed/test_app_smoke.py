"""HTTP smoke test of the HTML/JS frontend server (frontend/server.py, stdlib only).

Starts the real server on a free port in a thread and drives it with urllib, like the browser does.
"""
import importlib.util
import json
import threading
import urllib.error
import urllib.request

import pytest

from gm_helpers import ROOT

SERVER = ROOT / "frontend" / "server.py"
SAMPLE = ROOT / "frontend" / "sample" / "u4_outage_24h.csv"
NO_MATCH = "No sufficiently similar historical outage lessons found."


@pytest.fixture(scope="module")
def base():
    if not SERVER.exists():
        pytest.skip("frontend/server.py not on this branch")
    spec = importlib.util.spec_from_file_location("frontend_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = mod.make_server(0, "127.0.0.1")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(base, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def jcall(base, path, body=None, raw=None):
    code, _, data = call(base, path, body, raw)
    return code, json.loads(data)


def check_analysis(a):
    for key in ("token", "summary", "ambiguities", "overall", "risks", "hidden", "heat"):
        assert key in a, f"missing {key}"
    assert a["summary"]["tasks"] > 0
    assert 0 <= a["overall"]["risk_pct"] <= 100
    assert len(a["risks"]) <= 5
    for r in a["risks"]:
        assert 0 <= r["risk_pct"] <= 100
    for p in a["heat"]:
        assert len(p) >= 3 and 0 <= p[2] <= 1


def test_index_page(base):
    code, ctype, body = call(base, "/")
    assert code == 200 and "html" in ctype
    assert b"<html" in body.lower()


def test_python_source_not_served(base):
    code, _, _ = call(base, "/server.py")
    assert code == 404


def test_sample_planner(base):
    code, a = jcall(base, "/api/sample?user=planner_07")
    assert code == 200, a
    check_analysis(a)
    assert a["summary"]["crosses_midnight"] >= 1


def test_contractor_sees_less(base):
    _, planner = jcall(base, "/api/sample?user=planner_07")
    code, contractor = jcall(base, "/api/sample?user=contractor_02")
    assert code == 200, contractor
    check_analysis(contractor)
    assert contractor["hidden"] >= planner["hidden"]
    assert contractor["hidden"] > 0, "contractor should have restricted lessons hidden"


def test_upload_csv_and_reassess(base):
    if not SAMPLE.exists():
        pytest.skip("frontend/sample/u4_outage_24h.csv missing")
    code, a = jcall(base, "/api/analyze?name=u4.csv&user=planner_07", raw=SAMPLE.read_bytes())
    assert code == 200, a
    check_analysis(a)
    code, b = jcall(base, "/api/reassess", {"token": a["token"], "user": "lead_01"})
    assert code == 200, b
    check_analysis(b)
    assert b["summary"]["tasks"] == a["summary"]["tasks"]


def test_upload_xlsx_and_pdf(base):
    for path, name in ((ROOT / "data" / "samples" / "u4_outage_24h.xlsx", "u4.xlsx"),
                       (ROOT / "agent" / "samples" / "u4_outage_24h.pdf", "u4.pdf")):
        if not path.exists():
            continue
        code, a = jcall(base, f"/api/analyze?name={name}&user=planner_07", raw=path.read_bytes())
        assert code == 200, (name, a)
        check_analysis(a)


def test_bad_upload_is_400_not_500(base):
    code, a = jcall(base, "/api/analyze?name=junk.csv&user=planner_07", raw=b"\x00\x01 not a schedule")
    assert code in (200, 400), a
    if code == 400:
        assert "error" in a


def test_unknown_token_is_error(base):
    code, a = jcall(base, "/api/reassess", {"token": "nope", "user": "planner_07"})
    assert code in (400, 404), a
    assert "error" in a


def test_ask(base):
    _, a = jcall(base, "/api/sample?user=planner_07")
    code, ans = jcall(base, "/api/ask", {"token": a["token"], "user": "planner_07",
                                         "question": "What are the biggest risks in this outage?"})
    assert code == 200, ans
    assert isinstance(ans["answer"], str) and ans["answer"]
    assert isinstance(ans["lessons_cited"], list)


def test_heat_endpoint(base):
    code, h = jcall(base, "/api/heat?user=planner_07")
    assert code == 200
    assert isinstance(h["heat"], list)
