"""Schedule upload: varied column names, CSV and XLSX, midnight crossing, ambiguities flagged not invented."""
from datetime import date, datetime, timedelta

import pytest

schedule_parser = pytest.importorskip("agent.schedule_parser", reason="agent.schedule_parser not built yet")
from gm_helpers import FIXTURES, ROOT

MIDNIGHT_CSV = FIXTURES / "schedule_midnight.csv"
TIMES_ONLY_CSV = FIXTURES / "schedule_times_only.csv"


def by_id(result):
    return {str(t["id"]): t for t in result["tasks"]}


def sample_files():
    """The shared sample schedules (samples/, data/samples/ or agent/samples/), if they exist yet."""
    found = []
    for folder in (ROOT / "samples", ROOT / "data" / "samples", ROOT / "agent" / "samples"):
        if folder.exists():
            found += sorted(p for p in folder.iterdir() if p.suffix.lower() in (".csv", ".xlsx", ".xls"))
    return found


def check_tasks(result):
    assert result["tasks"], "no tasks parsed"
    for t in result["tasks"]:
        assert t["name"]
        if t["start"] is not None and t["end"] is not None:
            assert isinstance(t["start"], datetime) and isinstance(t["end"], datetime)
            assert t["end"] >= t["start"], f"{t['id']} ends before it starts"


def test_maps_unusual_column_names():
    res = schedule_parser.parse(MIDNIGHT_CSV)
    m = res["mapping"]
    assert m["id"] == "Activity ID" and m["name"] == "Activity"
    assert m["start"] == "Begin" and m["end"] == "Finish"
    assert m["predecessors"] == "Predecessors"
    check_tasks(res)


def test_task_crossing_midnight():
    res = schedule_parser.parse(MIDNIGHT_CSV)
    a3 = by_id(res)["A3"]
    assert a3["start"] == datetime(2027, 4, 12, 22, 0)
    assert a3["end"] == datetime(2027, 4, 13, 4, 0)
    assert a3["duration_hours"] == pytest.approx(6.0)
    assert res["summary"]["crosses_midnight"] >= 1


def test_times_without_dates_roll_over_midnight():
    res = schedule_parser.parse(TIMES_ONLY_CSV)
    tasks = by_id(res)
    seal = tasks["2"]
    assert seal["end"] - seal["start"] == timedelta(hours=6), "23:00 to 05:00 is 6 hours, next day"
    assert seal["end"].date() == seal["start"].date() + timedelta(days=1)
    assert tasks["3"]["start"] >= seal["end"], "sequence continues after midnight"


def test_missing_end_is_flagged_not_invented():
    res = schedule_parser.parse(MIDNIGHT_CSV)
    a5 = by_id(res)["A5"]
    flagged = [a for a in res["ambiguities"] if str(a.get("task_id")) == "A5"]
    assert flagged, "missing end time and duration must be listed in ambiguities"
    assert any(a["field"] in ("end", "duration") for a in flagged)
    assert a5["end"] is None, "never invent an end time"


def test_predecessors_and_critical_path():
    res = schedule_parser.parse(MIDNIGHT_CSV)
    t = by_id(res)
    assert t["A2"]["predecessors"] == ["A1"]
    assert t["A3"]["predecessors"] == ["A2"]
    for tid in ("A1", "A2", "A3", "A4"):
        assert t[tid]["critical"] is True, f"{tid} is on the longest chain"
    assert res["summary"]["tasks"] == 5


def test_bytes_with_filename_equals_path():
    from_path = schedule_parser.parse(MIDNIGHT_CSV)
    from_bytes = schedule_parser.parse(MIDNIGHT_CSV.read_bytes(), filename="upload.csv")
    assert [(t["id"], t["start"], t["end"]) for t in from_path["tasks"]] == \
           [(t["id"], t["start"], t["end"]) for t in from_bytes["tasks"]]


def test_xlsx_with_different_headers(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    df = pd.DataFrame({
        "WBS": ["X1", "X2"],
        "Task Name": ["Drain U4 condenser", "Condenser waterbox inspection"],
        "Start Date": [datetime(2027, 4, 12, 21, 0), datetime(2027, 4, 13, 1, 0)],
        "End Date": [datetime(2027, 4, 13, 1, 0), datetime(2027, 4, 13, 9, 0)],
        "Unit": ["U4", "U4"],
        "Predecessor": ["", "X1"],
    })
    path = tmp_path / "gantt_export.xlsx"
    df.to_excel(path, index=False)
    res = schedule_parser.parse(path)
    t = by_id(res)
    assert t["X1"]["end"] == datetime(2027, 4, 13, 1, 0)
    assert t["X1"]["duration_hours"] == pytest.approx(4.0)
    assert t["X2"]["predecessors"] == ["X1"]
    assert res["summary"]["crosses_midnight"] >= 1


def test_apply_mapping_after_user_edit():
    res = schedule_parser.parse(MIDNIGHT_CSV)
    mapping = dict(res["mapping"], contractor=None)  # user says "ignore that column"
    again = schedule_parser.apply_mapping(res["raw"], mapping, day0=date(2027, 4, 12))
    assert all(t["contractor"] in (None, "") for t in again["tasks"])
    assert len(again["tasks"]) == len(res["tasks"])


@pytest.mark.parametrize("path", sample_files() or [None], ids=lambda p: p.name if p else "none")
def test_data_thread_samples_parse(path):
    if path is None:
        pytest.skip("no samples/ folder yet")
    res = schedule_parser.parse(path)
    check_tasks(res)
    assert res["summary"]["tasks"] == len(res["tasks"])


# ---------------------------------------------------------------- the demo samples (data/samples, from make_samples.py)
SAMPLES = ROOT / "data" / "samples"


def test_demo_csv_midnight_tasks():
    path = SAMPLES / "u4_outage_24h.csv"
    if not path.exists():
        pytest.skip("data/samples/u4_outage_24h.csv not generated")
    res = schedule_parser.parse(path)
    t = by_id(res)
    assert len(res["tasks"]) == 20
    for tid in ("T10", "T11"):
        assert t[tid]["end"].date() == t[tid]["start"].date() + timedelta(days=1), f"{tid} crosses midnight"
    assert t["T11"]["duration_hours"] == pytest.approx(12.0)
    assert t["T10"]["duration_hours"] == pytest.approx(2.5)
    assert res["summary"]["crosses_midnight"] >= 2
    assert any(len(x["predecessors"]) >= 2 for x in res["tasks"]), '"T02;T03" splits into two predecessors'


def test_demo_xlsx_day_and_time_columns_and_ambiguous_row():
    path = SAMPLES / "u4_outage_24h.xlsx"
    if not path.exists():
        pytest.skip("data/samples/u4_outage_24h.xlsx not generated")
    pytest.importorskip("openpyxl")
    res = schedule_parser.parse(path)
    t = by_id(res)
    assert res["tasks"], "the 'Outage Plan' sheet should be found"
    amb = t["4.13a"]
    assert amb["end"] is None, "no end and no duration: never invent one"
    assert any(str(a.get("task_id")) == "4.13a" and a["field"] in ("end", "duration") for a in res["ambiguities"])
    assert any(len(x["predecessors"]) >= 2 for x in res["tasks"]), '"4.02, 4.03" splits into two predecessors'
    assert any(x["critical"] for x in res["tasks"]), "critical path computed when the file has no Critical column"
    timed = [x for x in res["tasks"] if x["end"] is not None]
    assert all(x["end"] > x["start"] for x in timed)
