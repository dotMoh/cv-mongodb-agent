"""Seed the Track 2 governed-memory collections and build their indexes.

    python seed_governed.py                 # wipe + seed lessons/audit_log, clear schedules, build indexes
    python seed_governed.py --export seed_lessons.json   # no DB: JSON for the mock store
    python seed_governed.py --check         # print counts per status/sensitivity, no DB

Reads MONGODB_URI from the environment or the repo-root .env (see db.py).
Collections follow plan/governed-memory-contracts.md.
"""
import argparse
import json
import time
from collections import Counter

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.operations import SearchIndexModel

import db  # loads .env
from embeddings import embed_many
from governed_seed_data import build_seed, embed_text

LESSON_INDEX = "lesson_vector_index"
LESSON_INDEX_DEF = {
    "fields": [
        {"type": "vector", "path": "embedding", "numDimensions": 384, "similarity": "cosine"},
        {"type": "filter", "path": "status"},
        {"type": "filter", "path": "sensitivity"},
        {"type": "filter", "path": "allowed_roles"},
        {"type": "filter", "path": "unit"},
        {"type": "filter", "path": "job_type"},
    ]
}


def _strip(doc):
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def create_indexes(dbh, wait=True):
    lessons = dbh.lessons
    lessons.create_index([("lesson_id", ASCENDING), ("version", DESCENDING)], unique=True, name="lesson_version")
    lessons.create_index([("status", ASCENDING), ("expires_at", ASCENDING)], name="status_expiry")
    # Forgotten docs can carry purge_at; Atlas deletes them then. Drafts are NOT TTL'd (expiry is audited).
    lessons.create_index([("purge_at", ASCENDING)], expireAfterSeconds=0, name="ttl_purge_at")
    dbh.audit_log.create_index([("ts", DESCENDING)], name="ts_desc")
    dbh.audit_log.create_index([("lesson_id", ASCENDING), ("ts", DESCENDING)], name="lesson_ts")
    dbh.schedules.create_index([("schedule_id", ASCENDING), ("version", ASCENDING)], unique=True, name="schedule_version")
    dbh.outage_actuals.create_index([("outage_id", ASCENDING), ("task_id", ASCENDING)], name="outage_task")
    print("Created standard indexes on lessons, audit_log, schedules, outage_actuals.")

    existing = {ix["name"] for ix in lessons.list_search_indexes()}
    if LESSON_INDEX in existing:
        lessons.update_search_index(LESSON_INDEX, LESSON_INDEX_DEF)
        print(f"Updated vector index '{LESSON_INDEX}'.")
    else:
        lessons.create_search_index(SearchIndexModel(definition=LESSON_INDEX_DEF, name=LESSON_INDEX, type="vectorSearch"))
        print(f"Requested vector index '{LESSON_INDEX}'.")
    if wait:
        print("Waiting for the vector index to become queryable...")
        start = time.time()
        while time.time() - start < 300:
            ix = list(lessons.list_search_indexes(LESSON_INDEX))
            if ix and ix[0].get("queryable"):
                print("Vector index is ready.")
                return
            time.sleep(5)
        print("Still building after 5 minutes; check Atlas > Search & Vector Search.")


def seed():
    data = build_seed()
    lessons = data["lessons"]
    to_embed = [d for d in lessons if d["status"] != "forgotten"]
    print(f"Embedding {len(to_embed)} lesson versions...")
    for d, v in zip(to_embed, embed_many([embed_text(d) for d in to_embed])):
        d["embedding"] = v

    client = MongoClient(db.MONGODB_URI)
    dbh = client[db.DB_NAME]
    if "lessons" not in dbh.list_collection_names():
        dbh.create_collection("lessons")
    for name in ("lessons", "audit_log", "schedules", "outage_actuals"):
        dbh[name].delete_many({})  # keep collections so the search index survives reseeds

    ids = {}
    for d in lessons:
        res = dbh.lessons.insert_one(_strip(d))
        if "_link" in d:
            ids[d["_link"]] = res.inserted_id
    for d in lessons:
        if "_supersedes" in d:
            new_id, old_id = ids[d["_link"]], ids[d["_supersedes"]]
            dbh.lessons.update_one({"_id": new_id}, {"$set": {"supersedes": old_id}})
            dbh.lessons.update_one({"_id": old_id}, {"$set": {"superseded_by": new_id}})
    dbh.audit_log.insert_many(data["audit_log"])
    print(f"Inserted {len(lessons)} lesson versions and {len(data['audit_log'])} audit entries.")
    create_indexes(dbh)
    client.close()


def check():
    data = build_seed()
    ls = data["lessons"]
    print("status:", dict(Counter(d["status"] for d in ls)))
    appr = [d for d in ls if d["status"] == "approved"]
    print("approved by sensitivity:", dict(Counter(d["sensitivity"] for d in appr)))
    print("approved by unit:", dict(Counter(d["unit"] for d in appr)))
    print("contractor sees", sum(d["sensitivity"] == "public" for d in appr), "approved; hidden",
          sum(d["sensitivity"] != "public" for d in appr))
    print("audit entries:", len(data["audit_log"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--export", metavar="PATH")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        return check()
    if a.export:
        data = build_seed()
        data["lessons"] = [_strip(d) for d in data["lessons"]]
        with open(a.export, "w") as f:
            json.dump(data, f, indent=2, default=lambda o: o.isoformat())
        print(f"Wrote {len(data['lessons'])} lessons and {len(data['audit_log'])} audit entries to {a.export}")
        return
    seed()


if __name__ == "__main__":
    main()
