# Frontend (Person C)

Single page: task box, role and plant pickers, schedule, memories used, Leaflet failure heatmap, and a "Teach the agent" box that calls `/learn` and then re-plans.

## Run
```
cd frontend
python3 -m http.server 5500
```
Open http://localhost:5500. Leaflet is vendored in `vendor/`, so only the map tiles need internet.

## Switch from mock to the real backend (one line)
In `app.js`, line 3: `const API_BASE = null;` -> `const API_BASE = "http://localhost:8000";`
The badge in the top right shows "mock data" or "live: <url>".

Backend needs CORS on (FastAPI):
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

## Response shapes the page expects (Person B: match these)
`POST /plan {task, role, plant_id}` returns:
```json
{
  "schedule": [
    {"step": "Reduce power and shut down", "start": "2027-06-28", "end": "2027-06-29",
     "note": "Moved 1 week earlier to avoid peak intake temperatures (m1)", "shifted": true}
  ],
  "memories_used": [
    {"_id": "m1", "content": "July 2024 Unit 3 outage slipped 6 days: ...", "score": 0.87,
     "location": {"type": "Point", "coordinates": [-79.07, 43.81]},
     "metadata": {"status": "active", "temperature_celsius": 31}}
  ],
  "heat_points": [[43.81, -79.07, 0.9]]
}
```
- `heat_points` are `[lat, lng, intensity 0..1]`. Note this is lat first, the opposite of GeoJSON. The page also accepts `{lat, lng, weight}` or GeoJSON points, so either works.
- `schedule` can also be a list of plain strings if the LLM output is messy. `task`/`name` and `reason` are accepted as aliases for `step` and `note`.
- `_id` must be a string (use `str(doc["_id"])`); `{"$oid": ...}` also works.
- `shifted: true` draws the step with a red edge (changed because of a memory).

`POST /learn {content, plant_id, corrects_id?}` returns anything JSON, e.g. `{"ok": true, "id": "..."}`. The page re-runs `/plan` right after.

Plant ids follow the data thread: unit-1, unit-3 (default), unit-5.

## Demo script (works on mock today)
1. Task "Plan July maintenance outage for Unit 3", role Planner, Generate plan. Shutdown moves to late June, citing the July 2024 overheating delay (mock-july-overheat).
2. Teach: "Intake chiller retrofit done in 2025: July intake temps now safe for full outage", Corrects memory = m1, Save. Page re-plans: m1 shows as corrected, new lesson is top memory, and the original July window comes back.
