"""Schedule versions. Version 1 is the immutable baseline; every change saves a new version."""
from __future__ import annotations

import copy
import uuid

from . import governance
from .store import get_store


def _tasks_copy(tasks):
    return [dict(copy.deepcopy(t)) for t in tasks]


def save_baseline(user_id: str, name: str, tasks: list[dict], schedule_id: str | None = None) -> dict:
    governance._require(user_id, "upload_schedule", "schedule_upload")
    doc = {"schedule_id": schedule_id or f"OUT-{uuid.uuid4().hex[:6].upper()}", "version": 1, "name": name,
           "is_baseline": True, "parent_version": None, "created_by": user_id, "created_at": governance.now_utc(),
           "applied_recommendations": [], "decisions": {}, "tasks": _tasks_copy(tasks)}
    doc["_id"] = get_store().schedules_insert(doc)
    governance.audit(user_id, "schedule_upload", detail=f"{doc['schedule_id']} v1: {name} ({len(tasks)} tasks)")
    return copy.deepcopy(doc)


def versions(schedule_id: str) -> list[dict]:
    return sorted(get_store().schedules_find({"schedule_id": schedule_id}), key=lambda d: d["version"])


def get(schedule_id: str, version: int | None = None) -> dict | None:
    vs = versions(schedule_id)
    if not vs:
        return None
    if version is None:
        return vs[-1]
    return next((v for v in vs if v["version"] == version), None)


def save_version(user_id: str, schedule_id: str, tasks: list[dict], parent_version: int, applied: list, decisions: dict) -> dict:
    latest = get(schedule_id)
    doc = {"schedule_id": schedule_id, "version": latest["version"] + 1, "name": latest["name"],
           "is_baseline": False, "parent_version": parent_version, "created_by": user_id,
           "created_at": governance.now_utc(), "applied_recommendations": applied, "decisions": decisions,
           "tasks": _tasks_copy(tasks)}
    doc["_id"] = get_store().schedules_insert(doc)
    governance.audit(user_id, "schedule_version", detail=f"{schedule_id} v{doc['version']} from v{parent_version}; "
                                                         f"{len(applied)} change(s) applied")
    return copy.deepcopy(doc)
