"""Read an outage schedule (CSV / XLSX / XLS) with whatever column names it uses.

Never invents values: anything missing or assumed is listed in `ambiguities` for the user to confirm.
"""
from __future__ import annotations

import difflib
import io
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

FIELDS = ["id", "name", "start", "end", "duration", "unit", "contractor", "equipment", "discipline",
          "predecessors", "critical", "milestone", "permit", "date"]

SYNONYMS = {
    "id": ["activity id", "task id", "id", "act id", "activity code", "task code", "wbs", "wbs code",
           "task no", "task number", "ref", "code", "no", "task"],
    "name": ["name", "task name", "activity name", "activity", "activity description", "task description",
             "description", "work description", "title", "job", "task"],
    "start": ["start", "begin", "start date", "start time", "planned start", "early start", "start datetime",
              "baseline start", "from", "start date time"],
    "end": ["finish", "end", "end date", "end time", "planned finish", "early finish", "finish date",
            "finish time", "baseline finish", "to", "end date time", "finish date time"],
    "duration": ["duration", "dur", "duration hrs", "duration hours", "hours", "hrs", "original duration",
                 "planned duration", "duration h", "duration days"],
    "unit": ["unit", "unit no", "plant", "area", "location", "system"],
    "contractor": ["contractor", "resp contractor", "responsible", "responsible contractor", "team", "crew",
                   "resource", "resources", "company", "vendor", "owner", "assigned to"],
    "equipment": ["equipment", "equip", "equip tag", "equipment tag", "tag", "asset", "component", "kks"],
    "discipline": ["discipline", "trade", "work type", "craft", "type", "department"],
    "predecessors": ["predecessors", "predecessor", "pred", "preds", "depends on", "dependencies",
                     "dependency", "after"],
    "critical": ["critical", "critical path", "on critical path", "cp", "is critical"],
    "milestone": ["milestone", "ms", "is milestone"],
    "permit": ["permit", "work permit", "permit no", "wp", "isolation", "isolation permit"],
    "date": ["date", "day", "shift date", "work date"],
}

TIME_ONLY = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})(?::(\d{2}))?\s*$")
DAY_TIME = re.compile(r"^\s*day\s*(\d+)\D+(\d{1,2})[:.](\d{2})\s*$", re.I)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", str(s).lower()).strip()


def map_columns(columns: list[str]) -> dict:
    """Best column for each field: exact synonym, then containment, then fuzzy. One column per field."""
    scores = []
    for col in columns:
        n = _norm(col)
        for field, syns in SYNONYMS.items():
            for i, syn in enumerate(syns):
                if n == syn:
                    s = 1.0 - i * 0.01
                elif re.search(rf"\b{re.escape(syn)}\b", n) and len(syn) > 2:
                    s = 0.8 - i * 0.01
                else:
                    r = difflib.SequenceMatcher(None, n, syn).ratio()
                    s = (r - 0.2) if r >= 0.85 else 0
                if s > 0:
                    scores.append((s, field, col))
    scores.sort(key=lambda x: -x[0])
    mapping, used = {f: None for f in FIELDS}, set()
    for s, field, col in scores:
        if mapping[field] is None and col not in used:
            mapping[field] = col
            used.add(col)
    return mapping


def _llm_mapping(columns, sample_rows) -> dict | None:
    from . import llm

    prompt = (f"Columns: {columns}\nFirst rows: {sample_rows}\nMap each of these fields to one column name "
              f"or null: {FIELDS}. Reply as a JSON object field -> column.")
    res = llm.chat("You map outage schedule spreadsheet columns to fields. JSON only.", prompt, as_json=True, timeout=15)
    if not isinstance(res, dict):
        return None
    return {f: (res.get(f) if res.get(f) in columns else None) for f in FIELDS}


def _read(file, filename):
    import pandas as pd

    if isinstance(file, (str, Path)) and not (isinstance(file, str) and "\n" in file):
        path = Path(file)
        filename = filename or path.name
        data = path.read_bytes()
    else:
        data = file.encode() if isinstance(file, str) else file
    ext = Path(filename or "upload.csv").suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(io.BytesIO(data), dtype=object)
    if ext == ".pdf":
        raise ValueError("PDF schedules are not supported yet; export the Gantt to CSV or Excel")
    text = data.decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(text), dtype=str, sep=None, engine="python", keep_default_na=False)


def _blank(v) -> bool:
    if v is None:
        return True
    try:
        import pandas as pd

        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip() == ""


def _to_dt(v, base: date | None):
    """Returns (datetime | None, time_only: bool)."""
    if _blank(v):
        return None, False
    if isinstance(v, datetime):
        return v.replace(tzinfo=None, microsecond=0), False
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime().replace(tzinfo=None), False
    if isinstance(v, time):
        return datetime.combine(base or date.today(), v), True
    s = str(v).strip()
    m = DAY_TIME.match(s)
    if m:
        d0 = base or date.today()
        return datetime.combine(d0 + timedelta(days=int(m.group(1)) - 1), time(int(m.group(2)) % 24, int(m.group(3)))), False
    m = TIME_ONLY.match(s)
    if m:
        return datetime.combine(base or date.today(), time(int(m.group(1)) % 24, int(m.group(2)))), True
    import pandas as pd

    try:
        dt = pd.to_datetime(s, dayfirst=bool(re.match(r"^\d{1,2}/\d{1,2}/\d{4}", s) and int(s.split("/")[0]) > 12))
        return dt.to_pydatetime().replace(tzinfo=None), False
    except Exception:
        return None, False


def _to_hours(v, header: str) -> float | None:
    if _blank(v):
        return None
    s = str(v).strip().lower()
    m = re.match(r"^(\d+):(\d{2})$", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    m = re.match(r"^([\d.]+)\s*(h|hr|hrs|hours|d|day|days|m|min|mins)?$", s)
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2) or ("d" if "day" in (header or "").lower() else "h")
    return n * 24 if u.startswith("d") else n / 60 if u.startswith("m") else n


def _truthy(v) -> bool | None:
    if _blank(v):
        return None
    return str(v).strip().lower() in ("y", "yes", "true", "1", "x", "critical", "cp")


def _split_preds(v) -> list[str]:
    if _blank(v):
        return []
    out = []
    for part in re.split(r"[,;|]+|\s{2,}", str(v)):
        part = part.strip()
        if not part:
            continue
        # "A12FS+2h" or "A12 SS" -> "A12"
        part = re.sub(r"\s*(FS|SS|FF|SF)([+-].*)?$", "", part, flags=re.I).strip()
        if re.fullmatch(r"\d+\.0", part):
            part = part[:-2]
        out.append(part)
    return out


def _cell(row, mapping, field):
    col = mapping.get(field)
    return row.get(col) if col else None


def _critical_path(tasks: list[dict]) -> set[str]:
    """Longest chain: from the latest-finishing task, walk back through the driving (latest-ending) predecessor."""
    by_id = {t["id"]: t for t in tasks}
    timed = [t for t in tasks if t["end"] is not None]
    if not timed:
        return set()
    project_end = max(t["end"] for t in timed)
    crit = set()
    stack = [t for t in timed if t["end"] == project_end]
    while stack:
        t = stack.pop()
        if t["id"] in crit:
            continue
        crit.add(t["id"])
        preds = [by_id[p] for p in t["predecessors"] if p in by_id and by_id[p]["end"] is not None]
        if preds:
            latest = max(p["end"] for p in preds)
            stack += [p for p in preds if p["end"] == latest]
    return crit


def apply_mapping(raw, mapping: dict, day0: date | None = None) -> dict:
    """Build tasks from a raw DataFrame and a field->column mapping (re-run after the user edits it)."""
    mapping = {f: mapping.get(f) for f in FIELDS}
    ambiguities = []
    rows = raw.to_dict("records")
    day0 = day0 or date.today()
    tasks, prev_start, seen = [], None, set()

    for i, row in enumerate(rows):
        if all(_blank(v) for v in row.values()):
            continue
        rid = _cell(row, mapping, "id")
        tid = str(rid).strip() if not _blank(rid) else f"T{i + 1}"
        if re.fullmatch(r"\d+\.0", tid):
            tid = tid[:-2]
        if _blank(rid):
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "id", "level": "info",
                                "message": f"No task ID; using {tid}."})
        if tid in seen:
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "id", "level": "warning",
                                "message": f"Duplicate task ID {tid}."})
        seen.add(tid)
        name = _cell(row, mapping, "name")
        name = str(name).strip() if not _blank(name) else None
        if not name:
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "name", "level": "warning",
                                "message": "Task has no name."})
            name = f"(unnamed task {tid})"

        base = None
        dval = _cell(row, mapping, "date")
        if not _blank(dval):
            bdt, _ = _to_dt(dval, None)
            if bdt:
                base = bdt.date()
            elif re.fullmatch(r"\d+", str(dval).strip()):
                base = day0 + timedelta(days=int(str(dval).strip()) - 1)
        start, s_time_only = _to_dt(_cell(row, mapping, "start"), base or day0)
        end, e_time_only = _to_dt(_cell(row, mapping, "end"), (start.date() if start else base or day0))
        preds = _split_preds(_cell(row, mapping, "predecessors"))

        if start and s_time_only and base is None:
            # Times without dates: keep the sequence moving forward across midnight.
            pred_ends = [t["end"] for t in tasks if t["id"] in preds and t["end"]]
            floor = max(pred_ends) if pred_ends else None
            while (floor and start < floor) or (prev_start and start < prev_start - timedelta(hours=12)):
                start += timedelta(days=1)
            if end and e_time_only:
                end = datetime.combine(start.date(), end.time())
        if start is None and not _blank(_cell(row, mapping, "start")):
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "start", "level": "warning",
                                "message": f"Could not read start '{_cell(row, mapping, 'start')}'."})
        elif start is None:
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "start", "level": "warning",
                                "message": "No start time."})

        dur = _to_hours(_cell(row, mapping, "duration"), mapping.get("duration") or "")
        if start and end and end <= start and e_time_only:
            end += timedelta(days=1)
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "end", "level": "info",
                                "message": "End time is before start; assumed it finishes after midnight."})
        if start and end is None and dur is not None:
            end = start + timedelta(hours=dur)
        if end is None:
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "end", "level": "warning",
                                "message": "No end time or duration; please confirm."})
        if start and end and end < start:
            ambiguities.append({"task_id": tid, "row": i + 1, "field": "end", "level": "warning",
                                "message": "Ends before it starts."})
        duration = round((end - start).total_seconds() / 3600, 2) if start and end else dur

        unit = _cell(row, mapping, "unit")
        contractor = _cell(row, mapping, "contractor")
        equipment = _cell(row, mapping, "equipment")
        discipline = _cell(row, mapping, "discipline")
        permit = _cell(row, mapping, "permit")
        crit = _truthy(_cell(row, mapping, "critical"))
        ms = _truthy(_cell(row, mapping, "milestone"))
        unit = None if _blank(unit) else str(unit).strip()
        if unit is None:
            m = re.search(r"\bU\s?(\d)\b", name, re.I)
            if m:
                unit = f"U{m.group(1)}"
            else:
                ambiguities.append({"task_id": tid, "row": i + 1, "field": "unit", "level": "info",
                                    "message": "No unit given."})
        if re.fullmatch(r"\d+", unit or ""):
            unit = f"U{unit}"
        tasks.append({
            "id": tid, "name": name, "start": start, "end": end, "duration_hours": duration,
            "unit": unit, "contractor": None if _blank(contractor) else str(contractor).strip(),
            "equipment": None if _blank(equipment) else str(equipment).strip(),
            "discipline": None if _blank(discipline) else str(discipline).strip(),
            "predecessors": preds, "critical": crit, "milestone": bool(ms) or (duration == 0),
            "permit": None if _blank(permit) else str(permit).strip(), "source_row": i + 1,
        })
        if start:
            prev_start = start

    ids = {t["id"] for t in tasks}
    for t in tasks:
        for p in t["predecessors"]:
            if p not in ids:
                ambiguities.append({"task_id": t["id"], "row": t["source_row"], "field": "predecessors",
                                    "level": "warning", "message": f"Predecessor {p} is not in the schedule."})
    if mapping.get("critical") is None or all(t["critical"] is None for t in tasks):
        crit = _critical_path(tasks)
        for t in tasks:
            t["critical"] = t["id"] in crit
    else:
        for t in tasks:
            t["critical"] = bool(t["critical"])

    timed = [t for t in tasks if t["start"] and t["end"]]
    span = (max(t["end"] for t in timed) - min(t["start"] for t in timed)).total_seconds() / 3600 if timed else 0
    for f in ("name", "start"):
        if mapping.get(f) is None:
            ambiguities.insert(0, {"task_id": None, "row": None, "field": f, "level": "warning",
                                   "message": f"No column found for '{f}'; please choose one in the mapping."})
    return {
        "tasks": tasks, "mapping": mapping, "columns": list(raw.columns), "raw": raw, "ambiguities": ambiguities,
        "summary": {"tasks": len(tasks), "critical": sum(t["critical"] for t in tasks), "span_hours": round(span, 2),
                    "crosses_midnight": sum(1 for t in timed if t["end"].date() > t["start"].date())},
    }


def parse(file, filename: str | None = None, day0: date | None = None, use_llm: bool = True) -> dict:
    """file: bytes, a path, or CSV text. Returns ParseResult (see contract)."""
    raw = _read(file, filename)
    raw.columns = [str(c).strip() for c in raw.columns]
    mapping = map_columns(list(raw.columns))
    if use_llm and (mapping["name"] is None or mapping["start"] is None):
        guess = _llm_mapping(list(raw.columns), raw.head(3).to_dict("records"))
        if guess:
            mapping = {f: mapping[f] or guess.get(f) for f in FIELDS}
    return apply_mapping(raw, mapping, day0=day0)


parse_schedule = parse
