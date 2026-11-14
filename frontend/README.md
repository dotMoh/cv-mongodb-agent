# Outage Router (frontend)

Plain HTML, CSS and JavaScript page, served by a tiny Python server that calls the `agent/` package. No Streamlit. `agent/` is not changed.

- upload an outage schedule (PDF with a schedule table, Excel, or CSV), or "Use sample schedule"
- overall outage risk %, with the top five major risks and their mitigations
- heatmap of past failure zones (Leaflet, OpenStreetMap tiles need internet)
- question box about the risks
- "Viewing as" Planner / Contractor / Lead (lessons are filtered by role)

## Run (Windows PowerShell, from the repo root, venv active)
```powershell
pip install -r agent/requirements.txt -r frontend/requirements.txt
python frontend/server.py
```
Open http://localhost:8000. Set `$env:PORT="8080"` first to use another port.

## Files
- `index.html`, `style.css`, `app.js`: the page
- `server.py`: serves the page and the JSON API (`/api/analyze`, `/api/sample`, `/api/reassess`, `/api/ask`, `/api/heat`)
- `vendor/`: Leaflet and leaflet.heat, so the page works without a CDN
- `sample/`: CSV, Excel and PDF versions of the U4 24 h sample outage
