"""Role policy, versioned lessons and the audit log. Every action, allowed or denied, is audited."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config
from .store import get_store

USERS = {"planner_07": "planner", "contractor_02": "contractor", "lead_01": "lead"}

# Which sensitivities each role may read, and which actions it may take.
READ_POLICY = {
    "planner": {"public", "internal"},
    "contractor": {"public"},
    "lead": {"public", "internal", "restricted"},
}
ACTIONS = {
    "planner": {"read", "add", "upload_schedule", "decide_recommendation", "generate_lessons"},
    "contractor": {"read"},
    "lead": {"read", "add", "approve", "correct", "forget", "history_all", "upload_schedule",
             "decide_recommendation", "generate_lessons"},
}
LESSON_FIELDS = ("job_type", "unit", "equipment", "title", "issue", "impact", "recommendation",
                 "category", "delay_days", "sensitivity", "allowed_roles", "evidence", "outage_id")


class PermissionDenied(Exception):
    """Raised after the denied attempt has been written to the audit log."""


def now_utc() -> datetime:
    """Naive UTC, matching what PyMongo returns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(dt):
    """Normalize to naive UTC (name kept for brevity)."""
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def role_of(user_id: str) -> str:
    if user_id not in USERS and user_id != "system":
        raise PermissionDenied(f"unknown user {user_id}")
    return USERS.get(user_id, "system")


def audit(user_id: str, action: str, allowed: bool = True, lesson_id=None, version=None, detail: str = "", now=None):
    get_store().audit_insert({
        "ts": _aware(now) or now_utc(), "user_id": user_id, "role": USERS.get(user_id, "system"),
        "action": action, "lesson_id": lesson_id, "version": version, "allowed": allowed, "detail": detail,
    })


def audit_log(limit: int = 200) -> list[dict]:
    """Newest first."""
    return get_store().audit_find(limit)


def _require(user_id: str, permission: str, action: str, lesson_id=None, version=None):
    role = role_of(user_id)
    if permission not in ACTIONS.get(role, set()):
        audit(user_id, action, allowed=False, lesson_id=lesson_id, version=version,
              detail=f"role '{role}' may not {action}")
        raise PermissionDenied(f"{role} may not {action}")
    return role


def can_read(role: str, lesson: dict) -> bool:
    return lesson.get("sensitivity", "internal") in READ_POLICY.get(role, set()) and \
        role in (lesson.get("allowed_roles") or ["planner", "contractor", "lead"])


def policy_filter(role: str) -> dict:
    """Mongo-style filter for approved lessons this role may read (used by vector search)."""
    return {"status": "approved", "sensitivity": {"$in": sorted(READ_POLICY[role])}, "allowed_roles": role}


def _latest(lesson_id: str) -> dict | None:
    versions = get_store().lessons_find({"lesson_id": lesson_id})
    return max(versions, key=lambda d: d["version"]) if versions else None


def _current_versions() -> list[dict]:
    """Latest version of every lesson."""
    latest = {}
    for d in get_store().lessons_find({}):
        if d["lesson_id"] not in latest or d["version"] > latest[d["lesson_id"]]["version"]:
            latest[d["lesson_id"]] = d
    return list(latest.values())


def _visible_drafts(user_id: str, role: str, lesson: dict) -> bool:
    return role == "lead" or (role == "planner" and lesson.get("created_by") == user_id)


# ------------------------------------------------------------------ reads
def visible_lessons(user_id: str, include_drafts: bool = False, include_superseded: bool = False) -> dict:
    """Lessons table. hidden_count = approved lessons this role cannot see."""
    role = role_of(user_id)
    store = get_store()
    approved = [d for d in _current_versions() if d["status"] == "approved"]
    visible = [d for d in approved if can_read(role, d)]
    hidden = len(approved) - len(visible)
    if include_drafts and role != "contractor":
        visible += [d for d in _current_versions() if d["status"] == "draft"
                    and _visible_drafts(user_id, role, d) and (role == "lead" or can_read(role, d))]
    if include_superseded:
        visible += [d for d in store.lessons_find({"status": "superseded"}) if can_read(role, d)]
    visible.sort(key=lambda d: (d["lesson_id"], d["version"]))
    if hidden:
        audit(user_id, "retrieve_denied", allowed=False, detail=f"{hidden} restricted lessons hidden by policy")
    return {"lessons": visible, "hidden_count": hidden}


def retrieve(user_id: str, query: str, k: int = 5, unit: str | None = None, min_similarity: float | None = None,
             log: bool = True) -> dict:
    """Semantic search over approved lessons the user may read. Returns lessons with "similarity"."""
    from .embeddings import threshold

    role = role_of(user_id)
    store = get_store()
    thr = threshold() if min_similarity is None else min_similarity
    flt = policy_filter(role)
    if unit:
        flt["unit"] = unit
    hits = [dict(d, similarity=s) for d, s in store.lessons_search(query, k, flt) if s >= thr]
    # What would have matched without the role policy (to report hidden lessons honestly).
    all_flt = {"status": "approved", **({"unit": unit} if unit else {})}
    hidden = [d for d, s in store.lessons_search(query, k + 10, all_flt) if s >= thr and not can_read(role, d)]
    if log:
        for d in hits:
            audit(user_id, "retrieve", lesson_id=d["lesson_id"], version=d["version"], detail=f"query: {query[:80]}")
        for d in hidden:
            audit(user_id, "retrieve_denied", allowed=False, lesson_id=d["lesson_id"], version=d["version"],
                  detail=f"{d['sensitivity']} lesson hidden by policy")
    return {"lessons": hits, "hidden_count": len(hidden), "hidden_ids": [d["lesson_id"] for d in hidden]}


def history(user_id: str, lesson_id: str) -> list[dict]:
    """All versions, oldest first. Lead sees any lesson; others only lessons they may read."""
    role = role_of(user_id)
    versions = sorted(get_store().lessons_find({"lesson_id": lesson_id}), key=lambda d: d["version"])
    if not versions:
        raise KeyError(lesson_id)
    if role != "lead" and not can_read(role, versions[-1]):
        audit(user_id, "history", allowed=False, lesson_id=lesson_id, detail="lesson hidden by policy")
        raise PermissionDenied("lesson hidden by policy")
    return versions


# ------------------------------------------------------------------ writes
def _next_lesson_id() -> str:
    nums = [int(d["lesson_id"].split("-")[1]) for d in get_store().lessons_find({}) if d["lesson_id"].startswith("L-")]
    return f"L-{(max(nums) if nums else 0) + 1:04d}"


def add_lesson(user_id: str, fields: dict, now=None, source: str = "manual", action: str = "add") -> dict:
    """New lessons are drafts that expire after DRAFT_EXPIRY_DAYS unless approved."""
    _require(user_id, "add", action)
    if not (fields.get("title") or fields.get("issue")):
        raise ValueError("a lesson needs a title or issue")
    now = _aware(now) or now_utc()
    doc = {k: fields.get(k) for k in LESSON_FIELDS}
    doc.update({
        "lesson_id": _next_lesson_id(), "version": 1, "status": "draft", "source": source,
        "title": fields.get("title") or fields.get("issue")[:80],
        "sensitivity": fields.get("sensitivity") or "internal",
        "allowed_roles": fields.get("allowed_roles") or ["planner", "contractor", "lead"],
        "delay_days": float(fields.get("delay_days") or 0), "category": fields.get("category") or "other",
        "evidence": fields.get("evidence") or [], "created_by": user_id, "created_at": now,
        "approved_by": None, "approved_at": None, "expires_at": now + timedelta(days=config.DRAFT_EXPIRY_DAYS),
        "supersedes": None, "superseded_by": None, "change_reason": None,
    })
    if "duplicates" in fields:
        doc["duplicates"] = fields["duplicates"]
    _id = get_store().lessons_insert(doc)
    audit(user_id, action, lesson_id=doc["lesson_id"], version=1, detail=doc["title"], now=now)
    return dict(doc, _id=_id)


def approve(user_id: str, lesson_id: str, now=None) -> dict:
    _require(user_id, "approve", "approve", lesson_id)
    now = _aware(now) or now_utc()
    cur = _latest(lesson_id)
    if not cur:
        raise KeyError(lesson_id)
    if cur["status"] != "draft" or (cur.get("expires_at") and _aware(cur["expires_at"]) <= now):
        audit(user_id, "approve", allowed=False, lesson_id=lesson_id, version=cur["version"],
              detail=f"cannot approve a {cur['status']} lesson" + (" (expired)" if cur["status"] == "draft" else ""))
        if cur["status"] == "draft":
            get_store().lessons_update(cur["_id"], {"status": "expired"})
        raise ValueError(f"only unexpired drafts can be approved (status: {cur['status']})")
    fields = {"status": "approved", "approved_by": user_id, "approved_at": now, "expires_at": None}
    get_store().lessons_update(cur["_id"], fields)
    audit(user_id, "approve", lesson_id=lesson_id, version=cur["version"], now=now)
    return dict(cur, **fields)


def correct(user_id: str, lesson_id: str, changes: dict, reason: str, now=None) -> dict:
    """New version with the changes; the previous version is kept and marked superseded."""
    _require(user_id, "correct", "correct", lesson_id)
    if not reason or not reason.strip():
        audit(user_id, "correct", allowed=False, lesson_id=lesson_id, detail="a reason is required")
        raise ValueError("a reason is required for a correction")
    if isinstance(changes, str):
        changes = {"issue": changes}
    now = _aware(now) or now_utc()
    cur = _latest(lesson_id)
    if not cur or cur["status"] in ("forgotten", "expired", "superseded"):
        raise ValueError(f"lesson {lesson_id} cannot be corrected")
    new = {k: v for k, v in cur.items() if k != "_id"}
    new.update({k: v for k, v in changes.items() if k in LESSON_FIELDS})
    new.update({"version": cur["version"] + 1, "supersedes": cur["_id"], "superseded_by": None,
                "change_reason": reason.strip(), "created_by": user_id, "created_at": now})
    if cur["status"] == "approved":
        new.update({"approved_by": user_id, "approved_at": now})
    new_id = get_store().lessons_insert(new)
    get_store().lessons_update(cur["_id"], {"status": "superseded", "superseded_by": new_id})
    audit(user_id, "correct", lesson_id=lesson_id, version=new["version"], detail=reason.strip(), now=now)
    return dict(new, _id=new_id)


def forget(user_id: str, lesson_id: str, confirm: bool = False, reason: str = "", now=None) -> None:
    """Forgotten lessons are never returned by retrieval. FORGET_POLICY=redact also clears the text."""
    _require(user_id, "forget", "forget", lesson_id)
    if not confirm:
        audit(user_id, "forget", allowed=False, lesson_id=lesson_id, detail="not confirmed")
        raise ValueError("forget requires confirm=True")
    now = _aware(now) or now_utc()
    cur = _latest(lesson_id)
    if not cur:
        raise KeyError(lesson_id)
    fields = {"status": "forgotten", "forgotten_by": user_id, "forgotten_at": now, "change_reason": reason or None}
    if config.FORGET_POLICY == "redact":
        fields.update({"issue": "[redacted]", "recommendation": "[redacted]", "evidence": []})
    get_store().lessons_update(cur["_id"], fields)
    audit(user_id, "forget", lesson_id=lesson_id, version=cur["version"], detail=reason or config.FORGET_POLICY, now=now)


def expire_drafts(now=None) -> int:
    now = _aware(now) or now_utc()
    n = 0
    for d in get_store().lessons_find({"status": "draft"}):
        if d.get("expires_at") and _aware(d["expires_at"]) <= now:
            get_store().lessons_update(d["_id"], {"status": "expired"})
            audit("system", "expire", lesson_id=d["lesson_id"], version=d["version"], detail="draft expired", now=now)
            n += 1
    return n


def days_to_expiry(lesson: dict, now=None) -> int | None:
    if lesson.get("status") != "draft" or not lesson.get("expires_at"):
        return None
    return max(0, (_aware(lesson["expires_at"]) - (_aware(now) or now_utc())).days)
