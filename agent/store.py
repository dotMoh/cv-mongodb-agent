"""Storage. DATA_SOURCE=mock (default): in-memory, seeded, no network. DATA_SOURCE=mongo: Atlas.

Everything above this module uses: lessons_find / lessons_insert / lessons_update / lessons_search,
audit_insert / audit_find, schedules_insert / schedules_find, reset().
Documents come back as plain dicts with "_id" as a string and no "embedding".
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .embeddings import embed, idf_table, mode as embed_mode, similarity
from .seed_lessons import embed_text, seed_docs


def _match(doc: dict, query: dict) -> bool:
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_match(doc, q) for q in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in" and not (any(v in arg for v in val) if isinstance(val, list) else val in arg):
                    return False
                if op == "$nin" and (any(v in arg for v in val) if isinstance(val, list) else val in arg):
                    return False
                if op == "$ne" and val == arg:
                    return False
                if op == "$lte" and not (val is not None and val <= arg):
                    return False
                if op == "$exists" and (val is not None) != arg:
                    return False
        elif isinstance(val, list) and not isinstance(cond, list):
            if cond not in val:
                return False
        elif val != cond:
            return False
    return True


def _public(doc: dict) -> dict:
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k != "embedding"}
    out["_id"] = str(doc["_id"])
    return out


SEED_JSON = Path(__file__).resolve().parent.parent / "data" / "seed_lessons.json"
DATE_KEYS = ("created_at", "approved_at", "expires_at", "ts", "forgotten_at", "purge_at", "corrected_at")


def _dates(doc: dict) -> dict:
    for k in DATE_KEYS:
        v = doc.get(k)
        if isinstance(v, str) and v:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            doc[k] = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    return doc


def load_seed() -> tuple[list[dict], list[dict]]:
    """The data thread's seed (data/seed_lessons.json) so mock and Atlas match; else the built-in list."""
    if SEED_JSON.is_file():
        raw = json.loads(SEED_JSON.read_text(encoding="utf-8"))
        lessons = [_dates({k: v for k, v in d.items() if k not in ("_id", "embedding")}) for d in raw.get("lessons", [])]
        audit = [_dates(dict(e)) for e in raw.get("audit_log", [])]
        return lessons, audit
    return seed_docs(), []


class MockStore:
    def __init__(self):
        self.reset()

    def reset(self):
        self.lessons, self.audit, self.schedules = [], [], []
        lessons, audit = load_seed()
        for d in lessons:
            self.lessons_insert(d)
        # Link versions: v(n).superseded_by -> v(n+1), v(n+1).supersedes -> v(n)
        by_key = {(d["lesson_id"], d["version"]): d for d in self.lessons}
        for (lid, ver), d in by_key.items():
            nxt = by_key.get((lid, ver + 1))
            if nxt:
                d["superseded_by"] = d.get("superseded_by") or nxt["_id"]
                nxt["supersedes"] = nxt.get("supersedes") or d["_id"]
        self.audit = audit

    # lessons
    def lessons_insert(self, doc: dict) -> str:
        doc = copy.deepcopy(doc)
        doc["_id"] = doc.get("_id") or uuid.uuid4().hex[:24]
        if embed_mode() == "minilm" and "embedding" not in doc:
            doc["embedding"] = embed(embed_text(doc))
        self.lessons.append(doc)
        return doc["_id"]

    def lessons_update(self, _id: str, fields: dict) -> None:
        for d in self.lessons:
            if d["_id"] == _id:
                d.update(copy.deepcopy(fields))
                if embed_mode() == "minilm" and any(k in fields for k in ("title", "issue", "recommendation", "job_type")):
                    d["embedding"] = embed(embed_text(d))
                return
        raise KeyError(_id)

    def lessons_find(self, query: dict | None = None) -> list[dict]:
        return [_public(d) for d in self.lessons if _match(d, query or {})]

    def lessons_search(self, text: str, k: int, query: dict) -> list[tuple[dict, float]]:
        qv = embed(text) if embed_mode() == "minilm" else None
        idf = None if qv else idf_table([embed_text(d) for d in self.lessons])
        hits = [(d, similarity(text, embed_text(d), d.get("embedding"), qv, idf)) for d in self.lessons if _match(d, query)]
        hits.sort(key=lambda h: h[1], reverse=True)
        return [(_public(d), round(s, 3)) for d, s in hits[:k]]


    def lessons_graph(self, restrict: dict, max_depth: int = 1, seed_ids=None, text=None, k: int = 3):
        """Seeds (by lesson_id, or by vector search on text) plus lessons reachable over `links`, like $graphLookup."""
        if text:
            seeds = [d for d, _ in self.lessons_search(text, k, restrict)]
        else:
            seeds = [_public(d) for d in self.lessons if d["lesson_id"] in (seed_ids or []) and _match(d, restrict)]
        allowed = {d["lesson_id"]: d for d in self.lessons if _match(d, restrict)}
        out = []
        for seed in seeds:
            seen, frontier, chain = {seed["lesson_id"]}, [seed], []
            for hops in range(max_depth + 1):
                nxt = []
                for node in frontier:
                    for ln in node.get("links") or []:
                        lid = ln.get("lesson_id")
                        if lid in allowed and lid not in seen:
                            seen.add(lid)
                            doc = dict(_public(allowed[lid]), hops=hops)
                            chain.append(doc)
                            nxt.append(doc)
                frontier = nxt
            out.append(dict(seed, chain=chain))
        return out

    # audit
    def audit_insert(self, entry: dict) -> None:
        self.audit.append(copy.deepcopy(entry))

    def audit_find(self, limit: int = 200) -> list[dict]:
        ordered = sorted(enumerate(self.audit), key=lambda ie: (ie[1].get("ts") or datetime.min, ie[0]), reverse=True)
        return [copy.deepcopy(e) for _, e in ordered[:limit]]

    # schedules
    def schedules_insert(self, doc: dict) -> str:
        doc = copy.deepcopy(doc)
        doc["_id"] = uuid.uuid4().hex[:24]
        self.schedules.append(doc)
        return doc["_id"]

    def schedules_find(self, query: dict) -> list[dict]:
        return [_public(d) for d in self.schedules if _match(d, query)]


class MongoStore:
    def __init__(self):
        from pymongo import MongoClient

        self.db = MongoClient(config.MONGODB_URI)[config.DB_NAME]
        self.lessons = self.db[config.LESSONS]
        self.audit = self.db[config.AUDIT]
        self.schedules = self.db[config.SCHEDULES]

    @staticmethod
    def _oid(_id):
        from bson import ObjectId

        return ObjectId(_id) if ObjectId.is_valid(str(_id)) else _id

    def reset(self):
        raise NotImplementedError("reset() is mock-only; reseed Atlas with the data scripts")

    def lessons_insert(self, doc: dict) -> str:
        doc = copy.deepcopy(doc)
        doc.pop("_id", None)
        doc["embedding"] = embed(embed_text(doc))
        return str(self.lessons.insert_one(doc).inserted_id)

    def lessons_update(self, _id: str, fields: dict) -> None:
        fields = dict(fields)
        if any(k in fields for k in ("title", "issue", "recommendation", "job_type")):
            cur = self.lessons.find_one({"_id": self._oid(_id)}, {"embedding": 0}) or {}
            fields["embedding"] = embed(embed_text({**cur, **fields}))
        self.lessons.update_one({"_id": self._oid(_id)}, {"$set": fields})

    def lessons_find(self, query: dict | None = None) -> list[dict]:
        return [_public(d) for d in self.lessons.find(query or {}, {"embedding": 0})]

    def lessons_search(self, text: str, k: int, query: dict) -> list[tuple[dict, float]]:
        pipeline = [
            {"$vectorSearch": {"index": config.LESSON_VECTOR_INDEX, "path": "embedding",
                               "queryVector": embed(text), "numCandidates": max(100, k * 20),
                               "limit": k, "filter": query}},
            {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
        ]
        out = []
        for d in self.lessons.aggregate(pipeline):
            # Atlas cosine score is (1 + cos) / 2; convert back to cosine so thresholds match mock.
            score = d.pop("score", 0.0)
            out.append((_public(d), round(2 * score - 1, 3)))
        return out


    def lessons_graph(self, restrict: dict, max_depth: int = 1, seed_ids=None, text=None, k: int = 3):
        """$vectorSearch (or $match on ids) for seed lessons, then $graphLookup over links.lesson_id,
        restricted to lessons the role may read."""
        if text:
            first = [{"$vectorSearch": {"index": config.LESSON_VECTOR_INDEX, "path": "embedding",
                                        "queryVector": embed(text), "numCandidates": max(100, k * 20),
                                        "limit": k, "filter": restrict}}]
        else:
            first = [{"$match": {"$and": [restrict, {"lesson_id": {"$in": list(seed_ids or [])}}]}}]
        pipeline = first + [
            {"$graphLookup": {"from": self.lessons.name, "startWith": "$links.lesson_id",
                              "connectFromField": "links.lesson_id", "connectToField": "lesson_id",
                              "as": "chain", "maxDepth": max_depth, "depthField": "hops",
                              "restrictSearchWithMatch": restrict}},
            {"$project": {"embedding": 0, "chain.embedding": 0}},
        ]
        out = []
        for d in self.lessons.aggregate(pipeline):
            chain = [_public(c) for c in d.pop("chain", []) if c.get("lesson_id") != d.get("lesson_id")]
            out.append(dict(_public(d), chain=sorted(chain, key=lambda c: c.get("hops", 0))))
        return out

    def audit_insert(self, entry: dict) -> None:
        self.audit.insert_one(copy.deepcopy(entry))

    def audit_find(self, limit: int = 200) -> list[dict]:
        return [_public(d) for d in self.audit.find().sort("ts", -1).limit(limit)]

    def schedules_insert(self, doc: dict) -> str:
        doc = copy.deepcopy(doc)
        doc.pop("_id", None)
        return str(self.schedules.insert_one(doc).inserted_id)

    def schedules_find(self, query: dict) -> list[dict]:
        return [_public(d) for d in self.schedules.find(query)]


_store = None


def get_store():
    global _store
    if _store is None:
        _store = MongoStore() if config.DATA_SOURCE == "mongo" else MockStore()
    return _store


def reset():
    """Restore seed data (mock only). Tests call this between cases."""
    get_store().reset()
