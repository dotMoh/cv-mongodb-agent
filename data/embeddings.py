"""Local, offline text embeddings with all-MiniLM-L6-v2 (384 dims, normalized).

EMBEDDINGS=hash gives a crude 384-dim bag-of-words vector with no torch or model
download. Only for testing plumbing; seed and query must use the same mode.
"""
import hashlib
import math
import os
import re
from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMS = 384
MODE = os.environ.get("EMBEDDINGS", "minilm")


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def _hash_embed(text: str) -> list[float]:
    v = [0.0] * DIMS
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIMS] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(text: str) -> list[float]:
    if MODE == "hash":
        return _hash_embed(text)
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_many(texts: list[str]) -> list[list[float]]:
    if MODE == "hash":
        return [_hash_embed(t) for t in texts]
    return _model().encode(texts, normalize_embeddings=True, batch_size=32).tolist()
