"""Seed the memories collection with fictional outage lessons and build indexes.

  python seed.py            # drop + insert + indexes
  python seed.py --dry-run  # print sample docs, no DB or model needed
  python seed.py --export sample_memories.json  # mock data for backend/frontend, no DB
"""
import argparse
import asyncio
import json

from db import MEMORIES, close_client, get_db
from seed_data import generate_lessons


def _jsonable(doc: dict) -> dict:
    return json.loads(json.dumps(doc, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)))


async def seed(n: int) -> None:
    from create_indexes import create_indexes
    from embeddings import embed_many

    lessons = generate_lessons(n)
    print(f"Embedding {len(lessons)} lessons with all-MiniLM-L6-v2...")
    vectors = embed_many([d["content"] for d in lessons])
    for doc, vec in zip(lessons, vectors):
        doc["embedding"] = vec

    coll = get_db()[MEMORIES]
    await coll.delete_many({})  # keep the collection so the search index survives reseeds
    result = await coll.insert_many(lessons)
    print(f"Inserted {len(result.inserted_ids)} documents into '{MEMORIES}'.")
    await create_indexes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=60, help="number of historical lessons")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export", metavar="PATH")
    args = parser.parse_args()

    if args.dry_run or args.export:
        lessons = [_jsonable(d) for d in generate_lessons(args.n)]
        if args.export:
            with open(args.export, "w") as f:
                json.dump(lessons, f, indent=2)
            print(f"Wrote {len(lessons)} docs to {args.export}")
        else:
            for d in lessons[:5]:
                print(json.dumps(d, indent=2))
            print(f"... {len(lessons)} total")
        return

    async def run():
        try:
            await seed(args.n)
        finally:
            await close_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
