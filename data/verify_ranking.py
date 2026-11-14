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
# Candidate wordings for the demo's /learn lesson; the first that passes is the one to use.
CORRECTIONS = [
    "Unit 3 July maintenance outage update: intake chiller retrofit finished in 2025, so July cooling water temperatures and heat waves no longer delay Unit 3 outages.",
    "Plan Unit 3 July outages normally now: the 2025 intake chiller retrofit fixed the cooling water overheating that delayed the July 2024 Unit 3 outage.",
    "Intake chiller retrofit done in 2025: July intake temps now safe for full outage",
]


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
    print(f"\nOverheating memory in top 3 before: {'PASS' if ok_before else 'FAIL'}")

    best = None
    for i, text in enumerate(CORRECTIONS, 1):
        trial = docs + [{"plant_id": PLANT, "content": text, "demo_key": "(new chiller lesson)",
                         "embedding": embed(text),
                         "metadata": {"status": "active", "access_level": ["planner", "safety_officer", "grid_operator"]}}]
        after = top(trial, qv)
        keys_after = [d.get("demo_key") for _, d in after]
        ok = "mock-july-overheat" not in keys_after and "(new chiller lesson)" in keys_after[:2]
        show(f"After /learn with wording {i}: {'PASS' if ok else 'FAIL'}", after)
        if ok and best is None:
            best = text

    if best:
        print(f"\nUSE THIS /learn TEXT IN THE DEMO:\n  {best}")
    else:
        print("\nNo wording ranked in the top 2. Paste this output into the thread.")
    return 0 if ok_before and best else 1


if __name__ == "__main__":
    sys.exit(main())
