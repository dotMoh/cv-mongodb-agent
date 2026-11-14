"""Outage Router: simple Streamlit page (frontend track).

Run from the repo root:  streamlit run frontend/app.py
Upload a schedule (CSV, Excel, or a PDF containing a schedule table), see the overall
risk, the major risks, a heatmap of past failure zones, and ask questions about the risks.
Uses the backend `agent/` package from the repo root (or frontend/stub_agent if it is missing).
The previous control-room layout is kept in frontend/control_room_app.py.
"""
from __future__ import annotations

import html
import io
import os
import re
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODULES = ["chat", "governance", "recommender", "risk", "schedule_parser", "schedules", "store"]
REAL_READY = all((ROOT / "agent" / f"{m}.py").exists() for m in MODULES)
USE_STUB = os.environ.get("AGENT_IMPL", "auto") == "stub" or (os.environ.get("AGENT_IMPL") != "real" and not REAL_READY)
sys.path.insert(0, str(HERE / "stub_agent") if USE_STUB else str(ROOT))
import agent  # noqa: E402
from agent import chat, governance, recommender, risk, schedule_parser, schedules  # noqa: E402

GREEN, GREEN_DARK, GREEN_LIGHT, BLACK, GREY = "#00843d", "#005a2b", "#e6f4ea", "#111111", "#5f6368"
SAMPLE = HERE / "sample" / "u4_outage_24h.csv"
USERS = {"planner_07": "Planner", "contractor_02": "Contractor", "lead_01": "Lead"}
# Illustrative positions for the station's units on the Lake Ontario shore (lat, lon).
UNIT_COORDS = {"U1": (43.8128, -79.0742), "U2": (43.8113, -79.0706), "U3": (43.8098, -79.0668),
               "U4": (43.8084, -79.0631), "U5": (43.8069, -79.0594)}
CAT_OFFSET = {"tooling": (0.0005, 0.0004), "permits": (-0.0004, 0.0005), "access": (0.0004, -0.0005),
              "resources": (-0.0005, -0.0003), "parts": (0.0001, 0.0008), "weather": (0.0008, -0.0001),
              "sequencing": (-0.0008, 0.0001), "rework": (-0.0001, -0.0008)}

st.set_page_config(page_title="Outage Router", layout="wide", initial_sidebar_state="collapsed")
st.markdown(f"""
<style>
html, body, .stApp, .stApp *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded) {{
  font-family: "Helvetica Neue", Arial, sans-serif; }}
.stApp {{ background: #f4f6f5; color: {BLACK}; }}
header[data-testid="stHeader"] {{ display: none; }}
.block-container {{ padding: 0 1.4rem 1.5rem 1.4rem; max-width: 100%; }}
.bar {{ background: {BLACK}; color: #fff; margin: 0 -1.4rem 18px -1.4rem; padding: 14px 28px; display: flex;
        align-items: center; gap: 24px; border-bottom: 4px solid {GREEN}; }}
.bar .name {{ font-size: 30px; font-weight: 700; letter-spacing: .01em; }}
.bar .name span {{ color: {GREEN}; }}
.bar .tag {{ color: #cfd8d3; font-size: 15px; flex: 1; text-align: center; }}
.bar .mode {{ background: {GREEN_LIGHT}; color: {GREEN_DARK}; border-radius: 12px; padding: 3px 12px; font-size: 13px; font-weight: 700; }}
div[data-testid="stColumn"] > div {{ background: #fff; border-radius: 10px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
h3 {{ margin-top: 0 !important; color: {BLACK}; }}
.big {{ font-size: 72px; font-weight: 800; line-height: 1; color: {BLACK}; }}
.cls {{ display: inline-block; margin-left: 10px; padding: 3px 12px; border-radius: 4px; font-weight: 700; font-size: 15px; vertical-align: middle; }}
.cls.High {{ background: {BLACK}; color: #fff; }}
.cls.Medium {{ background: {GREEN}; color: #fff; }}
.cls.Low, .cls.None {{ background: {GREEN_LIGHT}; color: {GREEN_DARK}; }}
.muted {{ color: {GREY}; font-size: 14px; }}
.risk {{ border: 1px solid #dfe5e1; border-left: 5px solid {GREEN}; border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; }}
.risk.High {{ border-left-color: {BLACK}; }}
.risk .top {{ display: flex; justify-content: space-between; gap: 10px; font-weight: 700; }}
.risk .pct {{ white-space: nowrap; }}
.meter {{ height: 6px; background: {GREEN_LIGHT}; border-radius: 3px; margin: 6px 0; }}
.meter div {{ height: 6px; background: {GREEN}; border-radius: 3px; }}
.risk.High .meter div {{ background: {BLACK}; }}
.answer {{ background: {GREEN_LIGHT}; border-radius: 6px; padding: 12px 14px; white-space: pre-wrap; color: {BLACK}; }}
.stButton > button[kind="primary"] {{ background: {GREEN}; border-color: {GREEN}; color: #fff; }}
.stButton > button[kind="primary"]:hover {{ background: {GREEN_DARK}; border-color: {GREEN_DARK}; }}
</style>
""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("user_id", "planner_07")


def esc(x):
    return html.escape("" if x is None else str(x))


# ---------------- schedule input ----------------
def pdf_to_csv_bytes(data: bytes) -> bytes:
    """Pull the largest table out of a PDF schedule (exported Gantt/task list) and return it as CSV."""
    import pdfplumber
    best = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables() or []:
                rows = [[(c or "").strip() for c in r] for r in tbl if r and any(c for c in r)]
                if len(rows) > len(best):
                    best = rows
            if not best:  # text layout without ruling lines: split on runs of 2+ spaces
                lines = [re.split(r"\s{2,}", ln.strip()) for ln in (page.extract_text() or "").splitlines()]
                lines = [ln for ln in lines if len(ln) >= 4]
                if len(lines) > len(best):
                    best = lines
    if len(best) < 2:
        raise ValueError("No schedule table found in the PDF. Export the Gantt chart's task table, or upload Excel/CSV.")
    width = len(best[0])
    df = pd.DataFrame([r[:width] + [""] * (width - len(r)) for r in best[1:]], columns=best[0])
    return df.to_csv(index=False).encode()


def load(data: bytes, name: str):
    try:
        parsed = schedule_parser.parse(data, name)  # the agent reads PDF, Excel and CSV
    except Exception:
        if not name.lower().endswith(".pdf"):
            raise
        data, name = pdf_to_csv_bytes(data), name[:-4] + ".csv"  # fallback for older agent versions
        parsed = schedule_parser.parse(data, name)
    tasks = [t for t in parsed["tasks"] if t.get("start") and t.get("end")]
    if not tasks:
        raise ValueError("Could not find task names with start and end times in this file.")
    base = schedules.save_baseline(ss.user_id, Path(name).stem.replace("_", " "), tasks)
    ss.update(schedule_id=base["schedule_id"], tasks=base["tasks"], parsed=parsed, file_name=name, answer=None)


def analysis():
    key = (ss.user_id, ss.get("schedule_id"))
    if ss.get("_akey") != key:
        rep = risk.assess(ss.user_id, ss.tasks)
        ss._akey, ss._rep, ss._recs = key, rep, recommender.recommend(ss.user_id, ss.tasks, rep)
    return ss._rep, ss._recs


# ---------------- header ----------------
mode = "sample data" if USE_STUB or getattr(getattr(agent, "config", None), "DATA_SOURCE", "mock") == "mock" else "live data"
st.markdown(f"""<div class="bar"><div class="name">Outage <span>Router</span></div>
<div class="tag">Routes your outage plan around the failures of past outages</div><div class="mode">{mode}</div></div>""",
            unsafe_allow_html=True)

c1, c2, c3 = st.columns([1, 1.15, 1.25], gap="medium")

# ---------------- left: upload + risk % ----------------
with c1:
    st.markdown("### Outage schedule")
    up = st.file_uploader("Gantt chart export or worksheet (PDF, Excel, CSV)", type=["pdf", "xlsx", "xls", "csv"])
    if up is not None and ss.get("file_name") not in (up.name, up.name[:-4] + ".csv"):
        try:
            load(up.getvalue(), up.name)
            st.rerun()
        except Exception as e:  # show any parse problem plainly
            st.error(str(e))
    if st.button("Use sample schedule"):
        load(SAMPLE.read_bytes(), SAMPLE.name)
        st.rerun()

    if ss.get("tasks"):
        rep, recs = analysis()
        o = rep["overall"]
        s = ss.parsed["summary"]
        st.markdown(f"<div class='muted'>{esc(ss.file_name)}: {s['tasks']} tasks, {s['critical']} on the critical path, "
                    f"{s['span_hours']:g} h</div>", unsafe_allow_html=True)
        if ss.parsed.get("ambiguities"):
            with st.expander(f"{len(ss.parsed['ambiguities'])} items need checking"):
                for a in ss.parsed["ambiguities"]:
                    st.markdown(f"- {('Row ' + str(a['row']) + ': ') if a.get('row') else ''}{esc(a['message'])}")
        st.markdown("### Outage risk")
        st.markdown(f"<span class='big'>{o['risk_pct']}%</span><span class='cls {esc(o['classification'])}'>"
                    f"{esc(str(o['classification']).upper())}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='muted'>{o['tasks_at_risk']} tasks at risk, about {o['total_delay_exposure_days']:g} days of "
                    f"delay exposure. Confidence: {esc(o['confidence'])}. "
                    f"{esc(o.get('note') or 'An indicative estimate from similar past lessons, not a validated statistical model.')}</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<div class='muted'>Upload a schedule to see its risk.</div>", unsafe_allow_html=True)

    labels = list(USERS.values())
    who = st.selectbox("Viewing as", labels, index=list(USERS).index(ss.user_id),
                       help="Lessons are filtered by role. Contractors see fewer lessons.")
    uid = list(USERS)[labels.index(who)]
    if uid != ss.user_id:
        ss.user_id, ss.answer = uid, None
        st.rerun()

# ---------------- middle: major risks + questions ----------------
with c2:
    st.markdown("### Major risks")
    if not ss.get("tasks"):
        st.markdown("<div class='muted'>No schedule loaded.</div>", unsafe_allow_html=True)
    else:
        top = [r for r in rep["tasks"] if r["risk_pct"] > 0][:5]
        if not top:
            st.markdown("<div class='risk'>No sufficiently similar historical outage lessons found.</div>", unsafe_allow_html=True)
        for r in top:
            m = r["matches"][0] if r["matches"] else None
            cite = f"{m['lesson_id']} v{m['version']}: {m['title']}" if m else ""
            st.markdown(f"""<div class="risk {esc(r['classification'])}">
<div class="top"><span>{esc(r['task_name'])}</span><span class="pct">{r['risk_pct']}%</span></div>
<div class="meter"><div style="width:{r['risk_pct']}%"></div></div>
<div class="muted">{r['delay_exposure_days']:g} d possible delay · {len(r['matches'])} past lesson{'s' if len(r['matches']) != 1 else ''} · {esc(cite)}</div>
<div style="margin-top:4px">{esc(r['mitigation'])}</div></div>""", unsafe_allow_html=True)
        if rep.get("hidden_by_policy"):
            st.markdown(f"<div class='muted'>{rep['hidden_by_policy']} restricted lessons hidden for this role.</div>",
                        unsafe_allow_html=True)

        st.markdown("### Ask about the risks")
        q = st.text_area("Question", placeholder="e.g. Could the U4 inspection be affected by previous U3 tooling delays?",
                         label_visibility="collapsed", height=90)
        if st.button("Ask", type="primary") and q.strip():
            with st.spinner("Checking past outages..."):
                ss.answer = chat.ask(ss.user_id, q, ss.tasks, rep, recs)
        if ss.get("answer"):
            a = ss.answer
            st.markdown(f"<div class='answer'>{esc(a['answer'])}</div>", unsafe_allow_html=True)
            if a.get("lessons_cited"):
                st.markdown(f"<div class='muted'>Lessons cited: {esc(', '.join(map(str, a['lessons_cited'])))}</div>",
                            unsafe_allow_html=True)

# ---------------- right: heatmap ----------------
with c3:
    st.markdown("### Past failure zones")
    vis = governance.visible_lessons(ss.user_id)
    pts = []
    for l in vis["lessons"]:
        if l["status"] == "approved" and l.get("unit") in UNIT_COORDS and float(l.get("delay_days") or 0) > 0:
            la, lo = UNIT_COORDS[l["unit"]]
            dla, dlo = CAT_OFFSET.get(l.get("category"), (0, 0))
            pts.append({"lat": la + dla, "lon": lo + dlo, "w": float(l["delay_days"]),
                        "what": f"{l['unit']}: {l['title']} ({l['delay_days']:g} d)"})
    if ss.get("tasks"):
        rmap = {r["task_id"]: r["risk_pct"] for r in rep["tasks"]}
        for t in ss.tasks:
            if rmap.get(t["id"]) and t.get("unit") in UNIT_COORDS:
                la, lo = UNIT_COORDS[t["unit"]]
                pts.append({"lat": la, "lon": lo, "w": rmap[t["id"]] / 40, "what": f"Planned: {t['name']} ({rmap[t['id']]}% risk)"})
    if pts:
        df = pd.DataFrame(pts)
        dens = getattr(px, "density_map", None)
        kw = {"map_style": "open-street-map"} if dens else {"mapbox_style": "open-street-map"}
        fig = (dens or px.density_mapbox)(df, lat="lat", lon="lon", z="w", radius=40, hover_name="what",
                                         hover_data={"lat": False, "lon": False, "w": False},
                                         center={"lat": 43.8098, "lon": -79.0668}, zoom=13.4, height=520,
                                         color_continuous_scale=[[0, "rgba(0,132,61,0)"], [0.35, "#7ccf8f"],
                                                                 [0.7, GREEN], [1, BLACK]], **kw)
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
    st.markdown("<div class='muted'>Darker means more delay in past outages, plus the risk on tasks in this schedule. "
                "Unit positions are illustrative.</div>", unsafe_allow_html=True)
