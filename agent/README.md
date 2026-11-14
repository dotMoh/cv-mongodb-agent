# agent/: Governed OPEX memory logic (Person B)

Pure Python, imported by the Streamlit app. Contract: `plan/governed-memory-contracts.md`.

```powershell
pip install -r agent/requirements.txt
python -m agent.demo          # full scenario in the terminal, from the repo root
```
Defaults: `DATA_SOURCE=mock` (in-memory, seeded from `data/seed_lessons.json`), `LLM_MODE=auto` (Ollama, falls back to rules),
`EMBEDDINGS=auto` (MiniLM if installed, else lexical). For Atlas set `DATA_SOURCE=mongo` and `MONGODB_URI` in `.env`.

| Module | What it does |
|---|---|
| `governance` | users/roles, read policy, add (draft, 30-day expiry), approve, correct (new version), forget, history, audit log |
| `schedule_parser` | CSV/XLSX with any column names → tasks; midnight roll-over; critical path; ambiguities list |
| `risk` | per-task repeat risk %, delay exposure, similarity, confidence, knock-on; `NO_MATCH_MESSAGE` |
| `recommender` | Gantt changes (move earlier, milestone, prerequisite, contingency); `apply()` saves a new version; `compare()` for the two-Gantt view |
| `schedules` | baseline (v1, immutable) and versions |
| `lesson_gen` | planned vs actual → draft lessons with evidence and duplicate hints |
| `chat` | answers questions from the report (Ollama, rule-based fallback) |
| `store` | mock and MongoDB storage |

Scores are indicative: repeat probability = 1 − ∏(1 − 0.85·similarity) over matched approved lessons (similarity ≥ 0.55);
off-critical-path tasks ×0.6; accepted changes reduce a task's risk by a fixed estimate per change type;
overall = mean of the three riskiest critical-path tasks.
