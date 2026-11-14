# Governed Memory: shared contracts (v1.1, 2026-11-14 12:35; implemented in agent/)

Track 2: Governed Memory. Python + Streamlit + MongoDB. Owner of this file: backend thread (Person B).
Streamlit (`app.py`, frontend thread) imports the `agent/` package directly. No HTTP needed.
Everything below works on an in-memory mock store (`DATA_SOURCE=mock`) so the UI can be built now; `DATA_SOURCE=mongo` uses Atlas.

## Users and roles
| user_id | role | sees (approved lessons) | can |
|---|---|---|---|
| `planner_07` | planner | sensitivity `public`, `internal` | read, add (saved as draft), see own drafts |
| `contractor_02` | contractor | sensitivity `public` only | read only; UI shows "N restricted lessons hidden by policy" |
| `lead_01` | lead | all (`public`, `internal`, `restricted`) | read, approve, correct, forget, history, all drafts |

`agent.governance.USERS` = `{"planner_07": "planner", "contractor_02": "contractor", "lead_01": "lead"}`.
A lesson can also narrow access with `allowed_roles` (default: all three).

## MongoDB collections (db `outage_agent`)

### `lessons` (one document per version, never overwritten)
```json
{
  "_id": "ObjectId",
  "lesson_id": "L-0007",          // stable across versions
  "version": 2,
  "job_type": "Heat exchanger inspection",
  "unit": "U3",
  "equipment": "HX-301",
  "title": "Tooling access delayed HX tube inspection",
  "issue": "Eddy current tooling not on site at isolation; inspection start slipped.",
  "impact": "2.5 day delay",
  "recommendation": "Confirm tooling availability before isolation.",
  "category": "tooling",          // tooling | permits | access | resources | parts | weather | sequencing | rework | other
  "delay_days": 2.5,
  "sensitivity": "internal",      // public | internal | restricted
  "allowed_roles": ["planner", "contractor", "lead"],
  "status": "approved",           // draft | approved | superseded | forgotten | expired
  "source": "seed",               // seed | manual | auto_generated
  "evidence": [{"type": "outage_record", "ref": "2024-U3-spring", "detail": "planned 8h, actual 68h"}],
  "outage_id": "2024-U3-spring",
  "created_by": "lead_01", "created_at": "ISODate",
  "approved_by": "lead_01", "approved_at": "ISODate",
  "expires_at": null,             // drafts: created_at + 30 days
  "supersedes": "ObjectId|null", "superseded_by": "ObjectId|null",
  "change_reason": "string|null",
  "embedding": [384 floats]       // all-MiniLM-L6-v2, normalized, of embed_text(lesson)
}
```
`embed_text(lesson)` = `f"{job_type}. {unit} {equipment}. {title}. {issue}. {recommendation}"`.

Indexes (data thread):
- Vector index `lesson_vector_index` on `embedding` (384, cosine) with filter fields `status`, `sensitivity`, `allowed_roles`, `unit`.
- `{lesson_id: 1, version: -1}` unique; `{status: 1, expires_at: 1}`.
- No TTL delete on drafts: expiry must be audited, so `governance.expire_drafts()` marks them `expired` and logs it. (Optional TTL on `purge_at` for forgotten docs.)

Retrieval for risk scoring = `status == "approved"` AND role policy. Superseded, forgotten, expired, and draft lessons are never used as evidence.

### `audit_log`
```json
{"ts": "ISODate", "user_id": "contractor_02", "role": "contractor", "action": "retrieve_denied",
 "lesson_id": "L-0004", "version": 1, "allowed": false, "detail": "restricted lesson hidden by policy"}
```
Actions: `retrieve`, `retrieve_denied`, `add`, `approve`, `correct`, `forget`, `expire`, `auto_generate`, `rec_accept`, `rec_reject`, `rec_modify`, `schedule_upload`, `schedule_version`, plus any action with `allowed: false` when a role tries something it may not do.

### `schedules` (baseline is immutable, each change makes a new version)
```json
{"_id": "ObjectId", "schedule_id": "OUT-2027-U4", "version": 1, "name": "U4 24h outage",
 "is_baseline": true, "parent_version": null, "created_by": "planner_07", "created_at": "ISODate",
 "applied_recommendations": [], "tasks": [Task, ...]}
```

## Python API (`agent/`)
Importable without Streamlit, Atlas or Ollama: `DATA_SOURCE=mock` (default) uses an in-memory seeded store, `LLM_MODE=fallback` skips Ollama, `EMBEDDINGS=hash` skips MiniLM. Tests call `agent.store.reset()` to restore the seed data between tests. `PermissionDenied` is `agent.governance.PermissionDenied`.
All functions take `user_id` (one of the three) and write audit entries themselves. Datetimes are Python `datetime`; Streamlit can pass them straight to Plotly.

### Task (dict)
```python
{"id": "T12", "name": "U4 heat exchanger tube inspection", "start": datetime, "end": datetime,
 "duration_hours": 8.0, "unit": "U4", "contractor": "Acme NDT", "equipment": "HX-401",
 "discipline": "Mechanical", "predecessors": ["T11"], "critical": True, "milestone": False,
 "permit": "WP-221" | None, "source_row": 14}
```

### `agent.schedule_parser`
- `parse(file_bytes: bytes | str | Path, filename: str | None = None) -> ParseResult` (alias `parse_schedule`; a path is read from disk) (CSV, XLSX/XLS; PDF is a stretch goal)
- `apply_mapping(raw_df, mapping: dict, day0: date | None = None) -> ParseResult` (re-run after the user edits the mapping)
- `ParseResult = {"tasks": [Task], "mapping": {field: column|None}, "columns": [str], "raw": DataFrame, "ambiguities": [{"task_id", "row", "field", "message"}], "summary": {"tasks": int, "critical": int, "span_hours": float, "crosses_midnight": int}}`
- Mapping fields: `id, name, start, end, duration, unit, contractor, equipment, discipline, predecessors, critical, milestone, permit`. Column names are matched fuzzily (synonyms, then Ollama if available). Times like `22:00` to `06:00` roll over midnight. Missing values are listed in `ambiguities`, never invented.
- `critical` is computed from the dependency graph (longest path) when the file has no critical column.

### `agent.governance`
- `retrieve(user_id, query: str, k=5, unit=None) -> {"lessons": [Lesson + "similarity"], "hidden_count": int}` (approved + policy only; audits `retrieve` and `retrieve_denied`)
- `visible_lessons(user_id, include_drafts=False) -> {"lessons": [Lesson], "hidden_count": int}`
- `add_lesson(user_id, fields: dict, now=None) -> Lesson` (status `draft`, expires in 30 days; contractor gets `PermissionDenied`)
- `approve(user_id, lesson_id) -> Lesson` (lead only)
- `correct(user_id, lesson_id, changes: dict, reason: str) -> Lesson` (lead only; new version, old one `superseded`)
- `forget(user_id, lesson_id, confirm: bool) -> None` (lead only; status `forgotten`, excluded from retrieval)
- `history(user_id, lesson_id) -> [Lesson]` (all versions, oldest first)
- `audit_log(limit=200) -> [AuditEntry]` (newest first)
- `expire_drafts(now=None) -> int` (`now` injectable for tests; drafts with `expires_at <= now` become `expired`)
- `PermissionDenied(Exception)`: always raised **after** the denied attempt is logged.

### `agent.risk`
- `assess(user_id, tasks: [Task]) -> RiskReport`
```python
RiskReport = {
  "overall": {"risk_pct": 41, "classification": "Medium", "confidence": "indicative",
              "tasks_at_risk": 3, "total_delay_exposure_days": 4.0, "critical_path_at_risk": True},
  "tasks": [TaskRisk, ...],          # every task, sorted by risk_pct desc
  "hidden_by_policy": 2,             # matching lessons the role could not see
}
TaskRisk = {
  "task_id": "T12", "task_name": "...", "risk_pct": 78, "classification": "High",   # None | Low | Medium | High
  "repeat_probability_pct": 78, "delay_exposure_days": 2.5, "similarity": 0.89,
  "confidence": "indicative",        # indicative (<2 matches) | moderate (2-3) | supported (4+)
  "matches": [{"lesson_id": "L-0007", "version": 2, "title": "...", "similarity": 0.89, "delay_days": 2.5, "category": "tooling"}],
  "explanation": "3 similar lessons; U3 tooling access delayed inspection start by 2.5 days.",
  "mitigation": "Confirm tooling on site before isolation.",
  "knock_on": ["T13", "T15"],        # downstream tasks via predecessors
  "evidence": [...],                 # same list as matches; [] when nothing matched
  "message": None | agent.risk.NO_MATCH_MESSAGE   # "No sufficiently similar historical outage lessons found."
}
```
Scoring (documented in the UI as indicative): matches = approved, visible lessons with similarity >= 0.55. `repeat_probability = 1 - prod(1 - sim_i * 0.85)` over the top 5; delay exposure = similarity-weighted mean of `delay_days`; risk_pct weights critical-path tasks x1.0 and others x0.6. No matches gives 0% and the "No sufficiently similar..." message. Overall risk = mean of the three riskiest critical-path tasks (shown with `overall.note`).

### `agent.recommender`
- `recommend(user_id, tasks: [Task], report: RiskReport) -> [Recommendation]`
- `apply(user_id, schedule_id, decisions: {rec_id: "accept"|"reject"|{"modify": {...}}}, recommendations=None) -> Schedule` (applies to the latest version, saves a new one; baseline untouched; every decision audited as rec_accept / rec_reject / rec_modify). Accepted changes are stored on the task as `mitigations`, so re-running `risk.assess` on the new version shows the reduced risk (`TaskRisk.mitigated = True`).
- `compare(schedule_a, schedule_b) -> [{"task_id", "status": "added"|"changed"|"unchanged", "task", "was"?}]` for the Original vs Recommended Gantt.
- Added tasks have ids like `T09-V` (verification milestone), `T09-P` (prerequisite), `T09-H` (hold point) and `added_by_agent: True`.
```python
Recommendation = {
  "rec_id": "R3", "task_id": "T12", "type": "move_earlier" | "add_contingency" | "add_prerequisite" | "add_milestone" | "resequence",
  "original": {"start": datetime, "end": datetime},
  "proposed": {"start": datetime, "end": datetime} | {"new_task": Task},
  "risk": "Tooling availability (L-0007 v2)",
  "reason": "...", "lessons": [{"lesson_id", "version", "title"}],
  "risk_before_pct": 78, "risk_after_pct": 32, "duration_impact_hours": 4.0,
  "status": "proposed"
}
```

### `agent.schedules`
- `save_baseline(user_id, name, tasks) -> Schedule` · `get(schedule_id, version=None)` · `versions(schedule_id) -> [Schedule]`

### `agent.lesson_gen`
- `generate(user_id, planned: [Task], actuals_file: bytes | [dict], filename=None) -> [Lesson]`
  Actuals = rows with task id or name plus `actual_start`, `actual_end`, optional `delay_cause`. Tasks that overran by >= 25% or 2h become draft lessons (`source: auto_generated`, evidence = planned vs actual), each with `duplicates: [{lesson_id, similarity}]`. They never skip approval.

### `agent.chat`
- `ask(user_id, question, tasks, report, recommendations) -> {"answer": str, "lessons_cited": [...], "source": "ollama"|"fallback"}`

## Demo script (memory changes the plan)
1. Planner uploads `samples/u4_outage_24h.csv`. Risk: U4 HX inspection 78% High, citing L-0007 (U3 tooling).
2. Accept "Move tooling prep to Day 2 + verification milestone": v2 schedule, risk drops.
3. Switch to contractor: restricted lessons hidden, count shown, denied attempts appear in the audit log in red.
4. Lead corrects L-0007 (reason required), which creates v3 and supersedes v2. Re-run risk: the card cites the new version.
5. Upload actuals: an auto-generated draft lesson appears (grey, 30-day expiry), lead approves it, and the next assessment uses it.
