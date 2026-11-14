"""Check how the real MiniLM model matches sample U4 tasks to seed lessons. No database needed.

    python verify_governed.py

For each task in samples/u4_outage_24h.csv, prints the top lessons a planner and a
contractor can see (approved only, policy applied) with cosine similarity, and how
many score >= 0.55 (the backend's match threshold). The demo needs the HX tube
inspection to match L-0007 for the planner, with 2 to 3 matches (moderate confidence).
"""
import csv
from pathlib import Path

from embeddings import embed, embed_many
from governed_seed_data import build_seed, embed_text

THRESHOLD = 0.55
SEES = {"planner": {"public", "internal"}, "contractor": {"public"}, "lead": {"public", "internal", "restricted"}}


def main():
    lessons = [d for d in build_seed()["lessons"] if d["status"] == "approved"]
    for d, v in zip(lessons, embed_many([embed_text(d) for d in lessons])):
        d["embedding"] = v
    tasks = list(csv.DictReader(open(Path(__file__).parent / "samples" / "u4_outage_24h.csv")))
    focus = {"T08", "T09", "T05", "T12", "T11"}
    for t in tasks:
        q = embed(f"{t['Discipline']}. {t['Unit']} {t['Equipment']}. {t['Task Name']}")
        for role in ("planner", "contractor"):
            scored = sorted(((sum(a * b for a, b in zip(q, d["embedding"])), d) for d in lessons
                             if d["sensitivity"] in SEES[role]), key=lambda x: -x[0])
            n = sum(s >= THRESHOLD for s, _ in scored)
            top = ", ".join(f"{d['lesson_id']} {s:.2f}" for s, d in scored[:3])
            if t["Task ID"] in focus or role == "planner":
                print(f"{t['Task ID']} {t['Task Name'][:38]:38} {role:10} matches>={THRESHOLD}: {n}  top: {top}")
    print("\nDemo check: T09 (U4 HX tube inspection) for planner should list L-0007 near the top with 2+ matches.")


if __name__ == "__main__":
    main()
