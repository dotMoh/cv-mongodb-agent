# Data layer (Person A): agent memory in MongoDB

Seeds fictional outage lessons, builds the indexes, and provides the search, heatmap and learn functions.

## Setup
```bash
cd data
pip install -r requirements.txt          # pymongo + sentence-transformers (pulls torch, a few minutes)
export MONGODB_URI="mongodb+srv://USER:PASS@cluster.xxxx.mongodb.net"
python seed.py                           # clears memories, inserts 70 docs, builds indexes, waits for vector index
```
The first run downloads all-MiniLM-L6-v2 from Hugging Face (about 90 MB), then it works offline.

Offline alternative to Atlas (same vector search):
```bash
docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:8.0
export MONGODB_URI="mongodb://localhost:27017/?directConnection=true"
```

No-DB helpers: `python seed.py --dry-run` prints sample docs; `python seed.py --export sample_memories.json` writes mock data.

## Names (agreed with backend and frontend)
| Setting | Value |
|---|---|
| DB / collection | `outage_agent` / `memories` (env `DB_NAME` or `MONGODB_DB`, `COLLECTION`) |
| Vector index | `vector_index` (env `VECTOR_INDEX`) |
| Plant ids | `unit-1`, `unit-2`, `unit-3` (demo unit), `unit-5` |
| Roles | `planner`, `safety_officer`, `grid_operator` |
| Embeddings | all-MiniLM-L6-v2, 384 dims, normalized, cosine |

## What's in the data
- 8 fixed demo memories with the same text as the backend mock, tagged `demo_key` (e.g. `mock-july-overheat` on unit-3).
- 60 generated lessons (cooling, grid, staffing, parts, safety, weather) with delays, temperatures and GeoJSON points. Hot-weather lessons are kept off unit-3 so correcting the July overheating memory visibly changes the plan.
- 2 temporary constraints with `metadata.expires_at`, deleted automatically by the TTL index after 14 and 30 days.

## Indexes
- Vector Search `vector_index`: `embedding` plus filter fields `plant_id`, `category`, `metadata.access_level`, `metadata.status`, `metadata.temperature_celsius`.
- TTL on `metadata.expires_at` (`expireAfterSeconds: 0`), 2dsphere on `location`, compound `plant_id + metadata.status`.

If the driver can't create the search index on your cluster tier, create it in Atlas UI > Search & Vector Search > JSON editor with `VECTOR_INDEX_DEFINITION` from `create_indexes.py`.

## Functions (`memory_store.py`, all async)
- `hybrid_search(query, role, plant_id=None, radius_km=50, min_temperature=None, categories=None, limit=5)`: `$vectorSearch` with role/status/temperature/category pre-filters, then a `$geoWithin` match around the plant (so neighbouring units count). `$vectorSearch` can't filter by location itself, which is why geo comes second. Returns docs with `_id`, `id`, `score`, no embedding.
- `heat_points(plant_id=None)`: `[[lat, lng, intensity 0..1], ...]` from `delay_days`, ready for Leaflet.heat.
- `learn(content, plant_id, corrects_id=None, ...)`: embeds and inserts a lesson; `corrects_id` (ObjectId string or a `demo_key`) marks the old one `metadata.status: "corrected"` so search skips it.

The backend's own `MongoStore.search()` also works on this data (filters by exact `plant_id`). Use `hybrid_search` if you want the geo radius and temperature filters.

## Tested
On `mongodb-atlas-local:8.0` with stand-in hash embeddings (Hugging Face was blocked in the test environment): seeding, all indexes, role and temperature filters, geo radius, heat points, and `learn` hiding the corrected memory all worked, and the backend's `/plan` and `/learn` ran against it. Search *ranking* with real MiniLM is not yet verified; run `python seed.py` once on a laptop and check that "Plan July maintenance outage for Unit 3" returns the July overheating memory.
