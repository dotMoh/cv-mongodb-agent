# Backend (Person B): Outage Planning Agent API

FastAPI + async PyMongo. Works today with **no database and no Ollama** (mock memories + rule-based planner), so the frontend can integrate right away.

## Run
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" "pymongo>=4.10" httpx    # fast install
pip install sentence-transformers                                 # MiniLM (needed for real Atlas search)
uvicorn main:app --reload --port 8000
```
Open http://localhost:8000/docs to try the endpoints. CORS is open (`*`), so the frontend on :5500 can call it.

## Settings (env vars)
| Var | Default | Meaning |
|---|---|---|
| `DATA_SOURCE` | `mock` | `mongo` switches to Atlas (Person A's data) |
| `MONGODB_URI` | | Atlas connection string |
| `DB_NAME` / `COLLECTION` / `VECTOR_INDEX` | `outage_agent` / `memories` / `vector_index` (DB also read from `MONGODB_DB`) | match Person A's names |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `llama3.1:8b` | local LLM |
| `OLLAMA_TIMEOUT` | `25` | seconds before falling back to rule-based planner |
| `LLM_MODE` | `auto` | `auto` (Ollama, fallback on error), `ollama`, `fallback` (demo-safe, instant) |
| `EMBEDDINGS` | `auto` | `minilm`, or `hash` (no torch, mock only) |

Swap to Atlas: `DATA_SOURCE=mongo MONGODB_URI="mongodb+srv://..." uvicorn main:app --port 8000`

## Endpoints
- `POST /plan {task, role, plant_id}` -> `{schedule, memories_used, heat_points, summary, adjustments, source, llm_error, elapsed_ms}`
  - schedule step: `{step, phase, start, end, duration_days, risk, note, shifted}`
  - memories_used: memory docs without `embedding`, plus `_id`/`id` (string) and `score`
  - heat_points: `[lat, lng, intensity 0..1]` (lat first, Leaflet.heat order)
  - `source` is `ollama` or `fallback`
- `POST /learn {content, plant_id, corrects_id?, access_level?, temperature_celsius?, location?, ttl_days?}` -> `{ok, id, corrected_id, status}`. Inserts the lesson (embedded) and sets the old one's `metadata.status = "corrected"` so search stops returning it.
- `GET /memories?plant_id=` debug list, `GET /health`, `POST /reset` (mock only: restores seed data to rerun the demo).

Roles are normalized: "Safety Officer" -> `safety_officer`.

## Demo (verified on mock)
1. `/plan` "Plan July maintenance outage for Unit 3" (Planner, unit-3): start moves from July 5 to **June 14, 2027**, maintenance gets +3 buffer days, citing `mock-july-overheat`.
2. `/learn` "Intake chiller retrofit done in 2025: July intake temps now safe for full outage", `corrects_id: "mock-july-overheat"`.
3. `/plan` again: start is back to **July 5**, the old memory is corrected, the chiller lesson is top memory.
Rerun with `POST /reset`. If Ollama is slow on stage, start with `LLM_MODE=fallback`; the rule planner gives the same demo beat deterministically.

## For Person A (data)
- Embed `content` with `sentence-transformers/all-MiniLM-L6-v2`, normalized, 384 dims (same model as `/plan` queries).
- Vector index on `embedding` (cosine) must declare these **filter** fields: `plant_id`, `metadata.status`, `metadata.access_level`.
- Access levels are lowercase: `planner`, `safety_officer`, `grid_operator`.
- If your hybrid query differs, replace only `MongoStore.search()` in `memory_store.py`; keep returning dicts with `_id` string and `score`, no embedding.

## Files
`main.py` routes · `memory_store.py` mock + Mongo data layer · `planner.py` Ollama prompt + rule-based fallback · `embeddings.py` · `config.py`
