"""Risk scores must be backed by real, visible, approved lessons, or say so honestly."""
import pytest

governance = pytest.importorskip("agent.governance", reason="agent.governance not built yet")
risk = pytest.importorskip("agent.risk", reason="agent.risk not built yet")
from gm_helpers import CONTRACTOR, DAY0, LEAD, PLANNER, task

NONSENSE = task("Z1", "Repaint visitor centre parking lot lines in blue", DAY0, 3, unit="Admin")
NO_MATCH = "No sufficiently similar historical outage lessons found."


def all_lesson_versions():
    """lesson_id -> {version: status}, from the lead's full view of history."""
    out = {}
    for l in governance.visible_lessons(LEAD, include_drafts=True)["lessons"]:
        out[l["lesson_id"]] = {v["version"]: v for v in governance.history(LEAD, l["lesson_id"])}
    return out


def seed_like_tasks():
    """Tasks built from real seed lessons so something should match."""
    lessons = [l for l in governance.visible_lessons(LEAD)["lessons"] if l["status"] == "approved"][:4]
    return [task(f"S{i}", f"{l['unit']} {l['job_type']} {l['title']}", DAY0, 6, unit=l["unit"], critical=i == 0)
            for i, l in enumerate(lessons)]


def test_no_match_message_constant():
    assert risk.NO_MATCH_MESSAGE == NO_MATCH


def test_no_matches_gives_message_and_no_evidence():
    report = risk.assess(PLANNER, [NONSENSE])
    tr = report["tasks"][0]
    assert tr["message"] == NO_MATCH
    assert tr["evidence"] == [] and tr["matches"] == []
    assert tr["risk_pct"] == 0
    assert tr["similarity"] in (None, 0, 0.0)
    assert report["overall"]["tasks_at_risk"] == 0


def test_every_cited_lesson_is_real_approved_and_visible():
    tasks = seed_like_tasks() + [NONSENSE]
    versions = all_lesson_versions()
    for user, allowed in ((PLANNER, {"public", "internal"}), (CONTRACTOR, {"public"}), (LEAD, {"public", "internal", "restricted"})):
        report = risk.assess(user, tasks)
        for tr in report["tasks"]:
            if tr["matches"]:
                assert tr["message"] is None
                assert tr["evidence"], "matches need evidence"
            for m in tr["matches"]:
                assert m["lesson_id"] in versions, f"invented lesson {m['lesson_id']}"
                v = versions[m["lesson_id"]][m["version"]]
                assert v["status"] == "approved", f"{m['lesson_id']} v{m['version']} is {v['status']}"
                assert v["sensitivity"] in allowed, f"{user} was shown a {v['sensitivity']} lesson"
                assert m["similarity"] >= 0.55


def test_confidence_labels_match_evidence_count():
    report = risk.assess(LEAD, seed_like_tasks() + [NONSENSE])
    for tr in report["tasks"]:
        n = len(tr["matches"])
        if n == 0:
            continue
        expected = "indicative" if n < 2 else "moderate" if n <= 3 else "supported"
        assert tr["confidence"] == expected, tr


def test_scores_are_percentages():
    report = risk.assess(LEAD, seed_like_tasks())
    assert 0 <= report["overall"]["risk_pct"] <= 100
    for tr in report["tasks"]:
        assert 0 <= tr["risk_pct"] <= 100
        assert tr["delay_exposure_days"] is None or tr["delay_exposure_days"] >= 0
    pcts = [tr["risk_pct"] for tr in report["tasks"]]
    assert pcts == sorted(pcts, reverse=True)


def test_forgotten_lesson_disappears_from_risk_evidence():
    tasks = seed_like_tasks()
    before = risk.assess(LEAD, tasks)
    cited = {m["lesson_id"] for tr in before["tasks"] for m in tr["matches"]}
    if not cited:
        pytest.skip("nothing matched the seed-like tasks with hash embeddings")
    gone = sorted(cited)[0]
    governance.forget(LEAD, gone, confirm=True)
    after = risk.assess(LEAD, tasks)
    assert gone not in {m["lesson_id"] for tr in after["tasks"] for m in tr["matches"]}


def test_contractor_hidden_count_reported():
    report = risk.assess(CONTRACTOR, seed_like_tasks())
    assert isinstance(report["hidden_by_policy"], int) and report["hidden_by_policy"] >= 0
