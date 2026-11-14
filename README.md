# Outage Router

A governed-memory agent for power-station outage planning (MongoDB Hackathon, Track 2: Governed Memory).

Upload an outage schedule (CSV, Excel or PDF). Outage Router compares each task with lessons learned from past outages, which are stored in MongoDB Atlas. It flags tasks likely to repeat a past delay, recommends schedule changes, and answers questions with cited lessons. The memory is governed: lessons are versioned, drafts need approval, corrections never overwrite history, forgotten lessons are purged, sensitive fields are redacted by role, and every change is audited.

## The problem
Outage schedules repeat the same mistakes, such as tooling not on site, late permits or scaffold clashes, because past lessons sit in reports nobody reads at planning time. An AI memory can help, but only if people can trust it: it needs to know which lesson is current, who approved it, what each role may see, and how to forget something.

## MongoDB Atlas features used
| Feature | Where | What it does |
|---|---|---|
| **Atlas Vector Search** (`$vectorSearch`, index `lesson_vector_index`, 384-dim cosine, all-MiniLM-L6-v2) | `agent/store.py` `lessons_search` | Finds approved lessons similar to each schedule task, with pre-filters on `status`, `sensitivity`, `allowed_roles` and `unit` |
| **`$graphLookup`** over `links.lesson_id` (index `links_lesson_id`) | `agent/store.py` `lessons_graph`, `agent/governance.py` `lesson_chain` | Lesson graph: from the seed lessons found by vector search, follows `caused_by` / `led_to` / `same_root_cause` links up to 2 hops (`restrictSearchWithMatch` keeps only approved lessons) |
| **Redaction `$set` stage** in the aggregation pipeline | `agent/store.py` `_redact_stages` | Replaces sensitive fields with `[restricted]` inside Atlas, right after `$vectorSearch` / `$graphLookup`, so redacted text never reaches the LLM or the page |
| **Versioned documents** with a unique index `{lesson_id: 1, version: -1}` | `agent/governance.py` `correct` | A correction inserts a new version and marks the old one `superseded`. Nothing is overwritten |
| **TTL index** `ttl_purge_at` on `purge_at` | `agent/governance.py` `forget` | A forgotten lesson becomes a tombstone that Atlas deletes automatically (`FORGET_PURGE_MINUTES`, 5 for the demo) |
| **Draft expiry** (index `{status: 1, expires_at: 1}`) | `agent/governance.py` `expire_drafts` | Unapproved drafts expire after 30 days and are logged rather than silently deleted |
| **`audit_log` collection** | `agent/governance.py` `audit` | Records adds, approvals, corrections, forgets, recommendation decisions, redactions and every blocked attempt |
| **`schedules` collection** | `agent/schedules.py` | The baseline schedule is immutable; accepted recommendations create new versions |

## Roles
| User | Role | Can do |
|---|---|---|
| `planner_07` | Planner | Read all approved lessons, add draft lessons, accept or reject recommendations. Sees `[restricted]` on restricted lessons |
| `contractor_02` | Contractor | Read only. Sees `[restricted]` in place of evidence, internal notes, outage id and link notes on internal and restricted lessons |
| `lead_01` | Lead | Everything: approve, correct (reason required, creates a new version), forget, and full history |

A blocked action (for example, a contractor clicking Approve) is refused with a 403 and logged in red in the audit log.

## What makes it different
- **Governed memory, not just RAG.** Only approved, current lesson versions are used as evidence. Drafts, superseded, forgotten and expired lessons never are.
- **Memory On vs Off.** The same schedule is scored with and without lessons, so you can see what memory adds.
- **Cited, sectioned answers.** Each answer has four sections (Relevant Lessons; What The Conclusion Does or Does Not Show; Recommended Mitigations; Lessons Cited), with lessons cited as `L-xxxx vN`. Answers can reason over lesson chains from `$graphLookup`.
- **Honest risk.** Scores are labelled as indicative. With no similar lesson the score is 0% and the agent says so, and it never invents lessons or numbers.
- **Field-level redaction in the pipeline.** Every role gets the same risk score, but sensitive fields are redacted in Atlas before they leave the database.
- **Always works.** The LLM is optional: Claude (Anthropic API), local Ollama, or a rule-based fallback with the same sectioned layout.

## How to run
Requirements: Python 3.11+.
```
pip install -r agent/requirements.txt
pip install sentence-transformers anthropic   # MiniLM embeddings + optional Claude chat
```
Copy `.env.example` to `.env` and fill it in. Never commit `.env`.
```
MONGODB_URI=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/
DATA_SOURCE=mongo
EMBEDDINGS=minilm
LLM_MODE=auto
LLM_PROVIDER=anthropic          # or ollama
ANTHROPIC_API_KEY=...           # only if LLM_PROVIDER=anthropic
```
Seed Atlas (lessons, links, indexes, demo data), then start the app:
```
python data/seed_governed.py
python dev.py live              # http://localhost:8000
```
For **mock mode** (no Atlas, no LLM, in-memory seed data), run `python dev.py`. Run the tests with `python dev.py test`.

Optional switches: `OPEN_READS` (1 = every role reads every approved lesson), `REDACTION` (1 = field redaction on), `LOG_READS` (0 = do not log reads), `FORGET_PURGE_MINUTES`, `ANTHROPIC_MODEL`.

## Demo tips
1. As **planner**, load the sample schedule. The heat exchanger tube inspection is flagged as high risk, citing lesson L-0007 (tooling not on site on a past outage).
2. Toggle **Memory off**, and the risk drops to 0% because no experience was consulted.
3. Ask "What is the biggest risk?" to get a sectioned answer with cited lessons and the lesson chain.
4. Switch to **contractor**: the score is the same, the evidence shows `[restricted]`, and Approve is refused and logged.
5. As **lead**, correct L-0007 (with a reason) to create a new version, then forget a lesson and watch the audit log show when Atlas TTL will purge it.

Reseed Atlas (`python data/seed_governed.py`) before a fresh demo, because demo actions change the shared data.

## Repository
- `agent/`: the governed-memory agent (store, governance, schedule parser, risk, recommender, lesson graph, chat, LLM)
- `frontend/`: the Outage Router page (HTML/CSS/JS) and `server.py`
- `data/`: seed data, Atlas seeding and index scripts
- `tests/governed/`: pytest suite, run in mock mode

## Limitations
- Redaction is applied in the aggregation pipeline by the app. It is not a MongoDB database role, view or field-level encryption, so a client with direct database access would see everything.
- Users and roles are fixed demo accounts with no authentication.
- Risk percentages are indicative similarity scores, not a validated statistical model.
- When Claude is used, the question and the risk summary are sent to the Anthropic API. Lessons and access control stay in MongoDB.
