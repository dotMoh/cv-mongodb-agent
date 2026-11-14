"""Text similarity. MiniLM (all-MiniLM-L6-v2, normalized, 384d) when installed, else a
lexical fallback so mock mode and CI work without torch."""
from __future__ import annotations

import hashlib
import math
import re

from . import config

_model = None
_mode = None

STOP = set("a an the of to on in at for and or with by from is was were be as it its this that into before after during".split())
SYNONYMS = {
    "hx": ["heat", "exchanger"], "exch": ["exchanger"], "insp": ["inspection"], "inspect": ["inspection"],
    "inspections": ["inspection"], "tools": ["tooling"], "tool": ["tooling"], "ect": ["eddy", "current"],
    "bfp": ["boiler", "feed", "pump"], "loto": ["lockout", "isolation"], "isolations": ["isolation"],
    "permits": ["permit"], "scaffolding": ["scaffold"], "tubes": ["tube"], "valves": ["valve"],
    "pumps": ["pump"], "gen": ["generator"], "prep": ["preparation"], "cond": ["condenser"],
}


def _load():
    global _model, _mode
    if _mode:
        return
    if config.EMBEDDINGS in ("auto", "minilm"):
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            _mode = "minilm"
            return
        except Exception as e:
            if config.EMBEDDINGS == "minilm":
                raise
            print(f"[agent.embeddings] MiniLM unavailable ({e}); using lexical similarity")
    _mode = "lexical"


def mode() -> str:
    _load()
    return _mode


def tokens(text: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if t in STOP or t.isdigit():   # equipment numbers like 401 are unit-specific noise
            continue
        out.update(SYNONYMS.get(t, [t]))
    return out


def embed(text: str) -> list[float]:
    """Vector for storage/search. In lexical mode returns a hashed bag of words (only used by Mongo)."""
    _load()
    if _mode == "minilm":
        return _model.encode(text, normalize_embeddings=True).tolist()
    vec = [0.0] * config.EMBED_DIMS
    for t in tokens(text):
        vec[int(hashlib.md5(t.encode()).hexdigest(), 16) % config.EMBED_DIMS] += 1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def similarity(query: str, doc_text: str, doc_vec=None, query_vec=None, idf: dict | None = None) -> float:
    """MiniLM: cosine. Lexical: IDF-weighted share of the query's words found in the document,
    so common words (unit names, "inspection") count for less than specific ones ("probe", "tooling")."""
    _load()
    if _mode == "minilm":
        return cosine(query_vec or embed(query), doc_vec or embed(doc_text))
    q, d = tokens(query), tokens(doc_text)
    if not q:
        return 0.0
    w = (lambda t: idf.get(t, max(idf.values()) if idf else 1.0)) if idf else (lambda t: 1.0)
    total = sum(w(t) for t in q)
    return sum(w(t) for t in q & d) / total if total else 0.0


def idf_table(texts: list[str]) -> dict:
    n = len(texts) or 1
    df = {}
    for t in texts:
        for tok in tokens(t):
            df[tok] = df.get(tok, 0) + 1
    return {tok: math.log(1 + n / c) for tok, c in df.items()}


def threshold() -> float:
    """Minimum similarity for a lesson to count as a match."""
    return 0.55
