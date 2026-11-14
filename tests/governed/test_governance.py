"""Role rules for the governed OPEX memory. Every denial must be refused AND logged."""
from datetime import datetime, timedelta

import pytest

governance = pytest.importorskip("agent.governance", reason="agent.governance not built yet")
PermissionDenied = governance.PermissionDenied
from gm_helpers import CONTRACTOR, LEAD, NEW_LESSON, PLANNER, audit_latest


def any_approved(user=LEAD, sensitivity=None):
    lessons = governance.visible_lessons(user)["lessons"]
    for l in lessons:
        if l["status"] == "approved" and (sensitivity is None or l["sensitivity"] == sensitivity):
            return l
    pytest.skip(f"seed data has no approved {sensitivity or ''} lesson")


def retrieved_ids(user, query, k=50):
    return {l["lesson_id"] for l in governance.retrieve(user, query, k=k)["lessons"]}


def query_for(lesson):
    return f"{lesson['job_type']} {lesson['unit']} {lesson['title']} {lesson['issue']}"


# ---------------------------------------------------------------- contractor: read only, denials logged
@pytest.mark.parametrize("action", ["add", "approve", "correct", "forget"])
def test_contractor_write_actions_denied_and_logged(action):
    target = any_approved()["lesson_id"]
    calls = {
        "add": lambda: governance.add_lesson(CONTRACTOR, dict(NEW_LESSON)),
        "approve": lambda: governance.approve(CONTRACTOR, target),
        "correct": lambda: governance.correct(CONTRACTOR, target, {"title": "x"}, reason="test"),
        "forget": lambda: governance.forget(CONTRACTOR, target, confirm=True),
    }
    with pytest.raises(PermissionDenied):
        calls[action]()
    entry = governance.audit_log(limit=1)[0]
    assert entry["user_id"] == CONTRACTOR and entry["allowed"] is False, entry
    assert entry["role"] == "contractor"


def test_contractor_denied_action_changes_nothing():
    target = any_approved()
    with pytest.raises(PermissionDenied):
        governance.forget(CONTRACTOR, target["lesson_id"], confirm=True)
    assert target["lesson_id"] in retrieved_ids(LEAD, query_for(target))


def test_contractor_sees_only_public_and_hidden_count():
    seen = governance.visible_lessons(CONTRACTOR)
    assert all(l["sensitivity"] == "public" for l in seen["lessons"])
    assert all("contractor" in l.get("allowed_roles", ["contractor"]) for l in seen["lessons"])
    total = len(governance.visible_lessons(LEAD)["lessons"])
    assert seen["hidden_count"] == total - len(seen["lessons"]), "hidden_count drives 'N restricted lessons hidden by policy'"


def test_contractor_restricted_retrieval_is_logged_as_denied():
    restricted = any_approved(sensitivity="restricted")
    res = governance.retrieve(CONTRACTOR, query_for(restricted), k=50)
    assert restricted["lesson_id"] not in {l["lesson_id"] for l in res["lessons"]}
    assert audit_latest(governance, user_id=CONTRACTOR, action="retrieve_denied", allowed=False)


def test_planner_never_sees_restricted():
    for l in governance.visible_lessons(PLANNER)["lessons"]:
        assert l["sensitivity"] in ("public", "internal")


# ---------------------------------------------------------------- planner: drafts with 30-day expiry
def test_planner_add_is_draft_with_30_day_expiry():
    now = datetime(2027, 1, 10, 9, 0)
    lesson = governance.add_lesson(PLANNER, dict(NEW_LESSON), now=now)
    assert lesson["status"] == "draft"
    assert lesson["version"] == 1
    assert lesson["created_by"] == PLANNER
    assert abs(lesson["expires_at"] - (now + timedelta(days=30))) < timedelta(minutes=1)
    assert audit_latest(governance, user_id=PLANNER, action="add", allowed=True)


def test_drafts_are_never_used_for_retrieval():
    lesson = governance.add_lesson(PLANNER, dict(NEW_LESSON))
    assert lesson["lesson_id"] not in retrieved_ids(LEAD, query_for(lesson))


@pytest.mark.parametrize("action", ["approve", "forget"])
def test_planner_cannot_approve_or_forget(action):
    target = any_approved(sensitivity="public")["lesson_id"]
    with pytest.raises(PermissionDenied):
        if action == "approve":
            governance.approve(PLANNER, target)
        else:
            governance.forget(PLANNER, target, confirm=True)
    assert governance.audit_log(limit=1)[0]["allowed"] is False


def test_draft_expires_after_30_days_and_is_logged():
    now = datetime(2027, 1, 10, 9, 0)
    lesson = governance.add_lesson(PLANNER, dict(NEW_LESSON), now=now)
    governance.expire_drafts(now=now + timedelta(days=29))  # seed drafts may expire here; ours must not
    assert governance.history(LEAD, lesson["lesson_id"])[-1]["status"] == "draft"
    assert governance.expire_drafts(now=now + timedelta(days=31)) >= 1
    latest = governance.history(LEAD, lesson["lesson_id"])[-1]
    assert latest["status"] == "expired"
    assert audit_latest(governance, action="expire", lesson_id=lesson["lesson_id"])
    with pytest.raises(Exception):
        governance.approve(LEAD, lesson["lesson_id"])  # an expired draft can't be resurrected silently


def test_lead_approval_makes_draft_retrievable():
    lesson = governance.add_lesson(PLANNER, dict(NEW_LESSON))
    approved = governance.approve(LEAD, lesson["lesson_id"])
    assert approved["status"] == "approved" and approved["approved_by"] == LEAD
    assert approved["expires_at"] is None
    assert lesson["lesson_id"] in retrieved_ids(LEAD, query_for(lesson))


# ---------------------------------------------------------------- lead: correct = new version
def test_lead_correct_creates_v2_and_supersedes_v1():
    old = any_approved()
    new = governance.correct(LEAD, old["lesson_id"], {"recommendation": "Stage tooling a full day early."},
                             reason="Tooling vendor changed")
    assert new["version"] == old["version"] + 1
    assert new["status"] == "approved"
    assert new["change_reason"] == "Tooling vendor changed"
    assert new["recommendation"] == "Stage tooling a full day early."

    versions = governance.history(LEAD, old["lesson_id"])
    assert [v["version"] for v in versions] == sorted(v["version"] for v in versions)
    prev = next(v for v in versions if v["version"] == old["version"])
    assert prev["status"] == "superseded", "old version is kept, never overwritten"
    assert prev["recommendation"] == old["recommendation"]
    assert audit_latest(governance, user_id=LEAD, action="correct", lesson_id=old["lesson_id"])

    hits = [l for l in governance.retrieve(LEAD, query_for(old), k=50)["lessons"] if l["lesson_id"] == old["lesson_id"]]
    assert [h["version"] for h in hits] == [new["version"]], "retrieval returns only the current version"


def test_correct_requires_reason():
    old = any_approved()
    with pytest.raises(Exception):
        governance.correct(LEAD, old["lesson_id"], {"title": "x"}, reason="")


# ---------------------------------------------------------------- forget
def test_forgotten_lesson_never_retrieved():
    gone = any_approved()
    governance.forget(LEAD, gone["lesson_id"], confirm=True)
    for user in (LEAD, PLANNER, CONTRACTOR):
        assert gone["lesson_id"] not in retrieved_ids(user, query_for(gone))
        assert gone["lesson_id"] not in {l["lesson_id"] for l in governance.visible_lessons(user)["lessons"]}
    assert audit_latest(governance, user_id=LEAD, action="forget", lesson_id=gone["lesson_id"])


def test_forget_requires_confirmation():
    target = any_approved()
    with pytest.raises(Exception):
        governance.forget(LEAD, target["lesson_id"], confirm=False)
    assert target["lesson_id"] in retrieved_ids(LEAD, query_for(target))


def test_audit_log_newest_first():
    governance.add_lesson(PLANNER, dict(NEW_LESSON))
    with pytest.raises(PermissionDenied):
        governance.add_lesson(CONTRACTOR, dict(NEW_LESSON))
    log = governance.audit_log(limit=10)
    assert log[0]["user_id"] == CONTRACTOR and log[0]["allowed"] is False
    assert [e["ts"] for e in log] == sorted((e["ts"] for e in log), reverse=True)


# ---------------------------------------------------------------- seed data facts (data thread, 2026-11-14)
def require_shared_seed():
    if len(governance.visible_lessons(LEAD)["lessons"]) != 30:
        pytest.skip("mock store is not loading the data thread's 30-lesson seed yet")


def test_seed_counts_for_contractor():
    require_shared_seed()
    seen = governance.visible_lessons(CONTRACTOR)
    assert len(seen["lessons"]) == 18 and seen["hidden_count"] == 12


def test_seed_forgotten_and_drafts_not_retrieved():
    ids = set()
    for q in ("heat exchanger inspection tooling", "valve permit isolation", "scaffold access crane", "pump seal rework"):
        for user in (LEAD, PLANNER, CONTRACTOR):
            ids |= retrieved_ids(user, q)
    assert "L-0034" not in ids, "seed lesson L-0034 is forgotten"
    assert not ids & {"L-0031", "L-0032", "L-0033"}, "seed drafts must not be retrieved"


def test_seed_l0007_is_v2_with_v1_superseded():
    require_shared_seed()
    versions = governance.history(LEAD, "L-0007")
    assert [v["version"] for v in versions][-1] == 2
    assert versions[0]["status"] == "superseded"
