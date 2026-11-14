"""Check the demo ranking with the real MiniLM model. No database needed.

    python verify_ranking.py

Mimics the backend's search (same plant_id, status active, role allowed, top 5
by cosine) over the seed data in memory, before and after the /learn correction.
Exit code 0 = the July overheating memory ranks for the demo query and the
chiller lesson replaces it after correction.
"""
import sys

from embeddings import embed, embed_many
from seed_data import generate_lessons

QUERY = "Plan July maintenance outage for Unit 3"
PLANT, ROLE, TOP_K = "unit-3", "planner", 5
CORRECTION = "Intake chiller retrofit done in 2025: July intake temps now safe for full outage"


def top(docs, qv):
    pool = [d for d in docs if d["plant_id"] == PLANT and d["metadata"]["status"] == "active"
            and ROLE in d["metadata"]["access_level"]]
    scored = sorted(((sum(a * b for a, b in zip(qv, d["embedding"])), d) for d in pool),
                    key=lambda x: -x[0])
    return scored[:TOP_K]


def show(title, rows):
    print(f"\n{title}")
    for rank, (score, d) in enumerate(rows, 1):
        print(f"  {rank}. {score:.3f}  {d.get('demo_key') or '':20} {d['content'][:70]}")


def main() -> int:
    docs = generate_lessons()
    for d, v in zip(docs, embed_many([d["content"] for d in docs])):
        d["embedding"] = v
    qv = embed(QUERY)

    before = top(docs, qv)
    show(f"Before correction: '{QUERY}'", before)
    keys = [d.get("demo_key") for _, d in before]
    ok_before = "mock-july-overheat" in keys[:3]

    for d in docs:
        if d.get("demo_key") == "mock-july-overheat":
            d["metadata"]["status"] = "corrected"
    docs.append({"plant_id": PLANT, "content": CORRECTION, "demo_key": "(new chiller lesson)",
                 "embedding": embed(CORRECTION),
                 "metadata": {"status": "active", "access_level": ["planner", "safety_officer", "grid_operator"]}})
    after = top(docs, qv)
    show("After /learn correction", after)
    keys_after = [d.get("demo_key") for _, d in after]
    ok_after = "mock-july-overheat" not in keys_after and "(new chiller lesson)" in keys_after[:3]

    print(f"\nOverheating memory in top 3 before: {'PASS' if ok_before else 'FAIL'}")
    print(f"Chiller lesson in top 3 after, old one gone: {'PASS' if ok_after else 'FAIL'}")
    return 0 if ok_before and ok_after else 1


if __name__ == "__main__":
    sys.exit(main())
