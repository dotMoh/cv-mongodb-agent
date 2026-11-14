"""The uploaded schedule is an immutable baseline: accept/reject/modify always make a new version."""
import copy

import pytest

governance = pytest.importorskip("agent.governance", reason="agent.governance not built yet")
recommender = pytest.importorskip("agent.recommender", reason="agent.recommender not built yet")
risk = pytest.importorskip("agent.risk", reason="agent.risk not built yet")
schedules = pytest.importorskip("agent.schedules", reason="agent.schedules not built yet")
from gm_helpers import DAY0, PLANNER, ROOT, task


SAMPLE = ROOT / "data" / "samples" / "u4_outage_24h.csv"


def tasks():
    """The demo schedule (it is known to produce recommendations), else a tiny synthetic one."""
    if SAMPLE.exists():
        from agent import schedule_parser
        return schedule_parser.parse(SAMPLE)["tasks"]
    return [
        task("T1", "Isolate U4 heat exchanger", DAY0, 2, critical=True),
        task("T2", "U4 heat exchanger tube inspection tooling access", DAY0.replace(hour=8), 8, predecessors=["T1"], critical=True),
        task("T3", "Return U4 to service", DAY0.replace(hour=16), 4, predecessors=["T2"], critical=True),
    ]


def snapshot(schedule):
    return copy.deepcopy([dict(t) for t in schedule["tasks"]])


@pytest.fixture
def baseline():
    return schedules.save_baseline(PLANNER, "U4 24h outage (test)", tasks())


def recs_for(base):
    report = risk.assess(PLANNER, base["tasks"])
    recs = recommender.recommend(PLANNER, base["tasks"], report)
    if SAMPLE.exists():
        assert recs, "the demo schedule must produce at least one recommendation"
    return recs


def test_baseline_saved_as_version_1(baseline):
    assert baseline["version"] == 1 and baseline["is_baseline"] is True
    assert baseline["parent_version"] is None


@pytest.mark.parametrize("decision", ["accept", "reject", "modify"])
def test_decisions_never_touch_baseline(baseline, decision):
    before = snapshot(schedules.get(baseline["schedule_id"], version=1))
    recs = recs_for(baseline)
    if not recs:
        pytest.skip("no recommendations for the test schedule with hash embeddings")
    rec = recs[0]
    choice = {"accept": "accept", "reject": "reject",
              "modify": {"modify": {"proposed": rec["proposed"]}}}[decision]
    new = recommender.apply(PLANNER, baseline["schedule_id"], {rec["rec_id"]: choice})

    assert new["version"] > 1 and new["is_baseline"] is False
    assert new["parent_version"] is not None
    assert snapshot(schedules.get(baseline["schedule_id"], version=1)) == before, "baseline was mutated"
    assert schedules.versions(baseline["schedule_id"])[0]["version"] == 1
    action = {"accept": "rec_accept", "reject": "rec_reject", "modify": "rec_modify"}[decision]
    assert any(e["action"] == action for e in governance.audit_log(limit=20)), f"{action} not audited"


def test_accept_changes_only_the_new_version(baseline):
    recs = recs_for(baseline)
    if not recs:
        pytest.skip("no recommendations for the test schedule with hash embeddings")
    new = recommender.apply(PLANNER, baseline["schedule_id"], {r["rec_id"]: "accept" for r in recs})
    assert new["applied_recommendations"]
    assert schedules.get(baseline["schedule_id"], version=1)["applied_recommendations"] == []


def test_caller_task_list_not_mutated():
    mine = tasks()
    before = copy.deepcopy(mine)
    base = schedules.save_baseline(PLANNER, "aliasing check", mine)
    recs = recs_for(base)
    if recs:
        recommender.apply(PLANNER, base["schedule_id"], {r["rec_id"]: "accept" for r in recs})
    assert mine == before, "save_baseline must copy, not keep a reference to the caller's list"
