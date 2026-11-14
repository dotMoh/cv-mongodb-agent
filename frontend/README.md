# Outage Router (frontend)

Plain HTML, CSS and JavaScript page, served by a small Python server (`server.py`, standard library) that calls the `agent/` package. No Streamlit, no CDN, no internet needed. `agent/` is not changed.

- upload an outage schedule (PDF with a schedule table, Excel, or CSV), or "Use sample schedule"
- overall outage risk %, top five major risks with mitigations
- **Memory on / off** switch in the header, plus a side-by-side "memory on vs. memory off" score for the same schedule
  (off = retrieval disabled, so no lessons are consulted)
- **Station heatmap**: 2D mock-up of four reactor units (U1 to U4) with a yellow-to-red heat layer from past lesson delays
  and this schedule's task risk; hover for details
- question box about the risks (answer shows whether it came from a language model or the rule-based fallback)
- **Memory governance**: lessons table with Approve (drafts), Correct (new version with a required reason), Forget
  (click twice), History, and Add a lesson (draft). Buttons the role may not use are refused and audited.
- **Audit log**: leads see every action; other roles see their own
- "Viewing as" Planner / Contractor / Lead

## Run (Windows PowerShell, from the repo root)
```powershell
python -m pip install pandas openpyxl pdfplumber pymongo
python frontend/server.py
```
Open http://localhost:8000. Set `$env:PORT="8080"` first to use another port.
The first lines printed show the data source, search mode and chat mode.

- Mock data (default) is in memory: "Reset demo data" restores the seed lessons.
- `DATA_SOURCE=mongo` writes approve / correct / forget to Atlas. Needs sentence-transformers (MiniLM) on that machine.
- Generated chat answers: set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in `.env` (and `python -m pip install anthropic`).
  Without a key the chat uses the rule-based fallback. Each answer shows which one wrote it.

## API (JSON)
GET `/api/sample?user=&memory=1`, `/api/heat`, `/api/lessons?user=`, `/api/audit?user=`, `/api/history?user=&lesson_id=`, `/api/status`
POST `/api/analyze?name=&user=&memory=` (raw file body), `/api/reassess`, `/api/ask`, `/api/lesson/add`, `/api/lesson/approve`,
`/api/lesson/correct`, `/api/lesson/forget`, `/api/reset`

## Files
- `index.html`, `style.css`, `app.js`: the page
- `server.py`: serves the page and the API
- `sample/`: CSV, Excel and PDF versions of the U4 24 h sample outage
