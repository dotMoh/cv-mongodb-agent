# Data layer (Person A)

## Track 2: Governed Memory (current)
Built against `plan/governed-memory-contracts.md`. The backend's `agent/` package owns all reads and writes; this folder owns seeding, indexes and sample files.

```bash
cd data
pip install -r requirements.txt openpyxl pandas
python seed_governed.py          # wipes + seeds lessons and audit_log, clears schedules/outage_actuals, builds indexes
python verify_governed.py        # no DB: shows which lessons the real model matches to each U4 task
python make_samples.py           # regenerates samples/
```

**Seed** (`governed_seed_data.py`, also exported to `seed_lessons.json` for the mock store):
- 30 approved lessons across U1 to U4: 18 public, 8 internal, 4 restricted. Contractor sees 18 and gets "12 hidden by policy".
- Demo lesson **L-0007** (U3 HX tube inspection, tooling, internal, 2.5 days) is at **v2**; v1 (1.5 days) is `superseded`, linked by `supersedes`/`superseded_by`. Lead's live correction makes v3.
- Other HX inspection/tooling lessons: L-0001, L-0002, L-0003, L-0019 (plus restricted L-0012, L-0025 for the lead).
- 3 drafts (L-0031 to L-0033) expiring in 28, 15 and 2 days. 1 forgotten tombstone (L-0034, content removed, no embedding).
- 39 audit entries including 3 denied ones (red rows from the start).

**Lesson graph:** every lesson version has `links: [{lesson_id, type, note}]`, type `caused_by` | `led_to` | `same_root_cause`, stored on both ends (14 edges, 21 docs). Demo chain in 2025-U3-fall: L-0006 permits → L-0005 scaffold → **L-0007** tooling → L-0010 closure across midnight → L-0029 hydrotest; L-0007 shares a root cause with L-0002, L-0003 and restricted L-0012. Index `links_lesson_id`. Tested on local Atlas with `$vectorSearch` then `$graphLookup` (`connectFromField: "links.lesson_id"`, `connectToField: "lesson_id"`, `restrictSearchWithMatch` = policy): planner gets the chain with L-0012 hidden, lead sees all, contractor's chain is empty because every linked lesson is internal or restricted.

**Indexes:** vector `lesson_vector_index` (384, cosine; filters `status`, `sensitivity`, `allowed_roles`, `unit`, `job_type`); unique `{lesson_id, version}`; `{status, expires_at}`; TTL only on `purge_at` (never on drafts); `audit_log {ts: -1}`; unique `schedules {schedule_id, version}`; `outage_actuals {outage_id, task_id}`.

**Score note:** Atlas `vectorSearchScore` for cosine is `(1 + cosine) / 2`, so 0.55 cosine is about 0.775 score. Convert with `cosine = 2 * score - 1` before applying the 0.55 threshold.

**Samples** (`samples/`):
- `u4_outage_24h.csv`: 20 tasks, 2027-03-01 06:00 to 03-02 06:00. T08 "Tooling preparation (eddy current probes)" 15:00 to 16:00 directly before T09 "U4 HX tube inspection" 16:00 to 22:00. Midnight crossings: T10 plugging 22:00 to 00:30, T11 valve overhaul 14:00 to 02:00. T05 scaffold overlaps T04 drain and vent (matches L-0005). T20 is a milestone.
- `u4_outage_24h.xlsx`: same outage, different headers (WBS, Activity Description, Day, Start Time, End Time, Depends On...), time-only columns that roll over midnight, no Critical column, and one ambiguous row (4.13a, no end time or duration).
- `u4_actuals.csv`: task_id, task_name, planned/actual start/end, delay_cause. Two tasks overran on their own duration: T08 (+3h) and T09 (+4h). Downstream tasks start later but keep their durations, so compare durations, not end times.

---

# Track 1 (superseded): outage memories

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
- On `mongodb-atlas-local:8.0`: seeding, all indexes, role and temperature filters, geo radius, heat points, `learn` hiding the corrected memory, and the backend's `/plan` and `/learn` against it.
- Atlas M0 seeded by friend, vector index ready.
- Real MiniLM ranking (`python verify_ranking.py`): the July overheating memory ranks #2 for "Plan July maintenance outage for Unit 3"; after correction the demo lesson ranks #1 (0.633).

## Demo /learn text (use exactly)
> Unit 3 July maintenance outage update: intake chiller retrofit finished in 2025, so July cooling water temperatures and heat waves no longer delay Unit 3 outages.

The original "Intake chiller retrofit done in 2025..." wording does not reach the top 5, so the plan would not change back.
