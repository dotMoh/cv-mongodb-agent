"""Live demo of MongoDB TTL purging forgotten lessons.

    python show_ttl.py               # show the TTL index and every doc waiting to be purged
    python show_ttl.py --arm 2       # schedule purge of all forgotten lessons in 2 minutes, then watch
    python show_ttl.py --watch       # watch until Atlas deletes the pending docs

How it works: the lessons collection has a TTL index `ttl_purge_at` ({purge_at: 1},
expireAfterSeconds: 0). Atlas's TTL monitor runs about every 60 seconds and deletes any
document whose purge_at is in the past. Only forgotten lessons get purge_at, so the audit
log keeps the record of the forget while the lesson content leaves the database for good.
Drafts are never TTL-deleted, because their expiry must be audited by the app.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

import db  # loads .env


def now():
    return datetime.now(timezone.utc)


def pending(coll):
    return list(coll.find({"purge_at": {"$exists": True}},
                          {"lesson_id": 1, "version": 1, "status": 1, "purge_at": 1}).sort("purge_at", 1))


def show(coll):
    ttl = [ix for ix in coll.list_indexes() if "expireAfterSeconds" in ix]
    for ix in ttl:
        print(f"TTL index {ix['name']}: key {dict(ix['key'])}, expireAfterSeconds={ix['expireAfterSeconds']}")
    docs = pending(coll)
    if not docs:
        print("No documents waiting to be purged.")
    for d in docs:
        pa = d["purge_at"].replace(tzinfo=timezone.utc)
        left = (pa - now()).total_seconds()
        when = f"in {left/60:.1f} min" if left > 0 else f"due {-left:.0f}s ago (TTL monitor runs about every 60s)"
        print(f"  {d['lesson_id']} v{d['version']} [{d['status']}] purge_at {pa:%H:%M:%S} UTC, {when}")
    return docs


def watch(coll):
    print("Watching. Refresh Atlas Data Explorer with filter {purge_at: {$exists: true}} to see the same.")
    while True:
        docs = pending(coll)
        if not docs:
            print(f"{now():%H:%M:%S} all purged by Atlas TTL.")
            return
        for d in docs:
            left = (d["purge_at"].replace(tzinfo=timezone.utc) - now()).total_seconds()
            print(f"{now():%H:%M:%S} {d['lesson_id']} v{d['version']} still present, "
                  f"{'purges in %.0fs' % left if left > 0 else 'waiting for TTL monitor'}")
        time.sleep(15)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arm", type=float, metavar="MINUTES")
    p.add_argument("--watch", action="store_true")
    a = p.parse_args()
    client = MongoClient(db.MONGODB_URI)
    coll = client[db.DB_NAME].lessons
    if a.arm is not None:
        at = now() + timedelta(minutes=a.arm)
        n = coll.update_many({"status": "forgotten"}, {"$set": {"purge_at": at}}).modified_count
        print(f"Scheduled {n} forgotten lesson version(s) to be purged at {at:%H:%M:%S} UTC.")
        if n:
            client[db.DB_NAME].audit_log.insert_one({
                "ts": now(), "user_id": "lead_01", "role": "lead", "action": "purge_scheduled", "lesson_id": None,
                "version": None, "allowed": True, "detail": f"{n} forgotten lesson(s) purge at {at:%H:%M} UTC by TTL"})
    show(coll)
    if a.arm is not None or a.watch:
        watch(coll)


if __name__ == "__main__":
    main()
