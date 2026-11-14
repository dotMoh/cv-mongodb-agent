"""Query embeddings. Must use the SAME model Person A used to embed the seed data."""
import hashlib
import math
import re

from config import EMBEDDINGS, EMBED_DIMS

_model = None
_mode = None


def _load():
    global _model, _mode
    if _mode:
        return
    if EMBEDDINGS in ("auto", "minilm"):
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            _mode = "minilm"
            return
        except Exception as e:  # not installed or no download
            if EMBEDDINGS == "minilm":
                raise
            print(f"[embeddings] MiniLM unavailable ({e}); using hash embeddings")
    _mode = "hash"


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIMS
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % EMBED_DIMS] += 1.0 if (h >> 8) % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(text: str) -> list[float]:
    _load()
    if _mode == "minilm":
        return _model.encode(text, normalize_embeddings=True).tolist()
    return _hash_embed(text)


def mode() -> str:
    _load()
    return _mode
