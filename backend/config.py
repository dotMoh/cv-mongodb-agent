"""All settings come from environment variables (or a .env file you export)."""
import os
from pathlib import Path


def _load_dotenv():
    """Read KEY=VALUE lines from backend/.env and the repo-root .env (works on Windows, no deps).
    Variables already set in the environment win."""
    here = Path(__file__).resolve().parent
    for path in (here / ".env", here.parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()

# Data layer: "mock" (in-memory, no DB needed) or "mongo" (Atlas, Person A's data).
DATA_SOURCE = os.getenv("DATA_SOURCE", "mock").lower()
MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("DB_NAME") or os.getenv("MONGODB_DB", "outage_agent")
COLLECTION = os.getenv("COLLECTION", "memories")
VECTOR_INDEX = os.getenv("VECTOR_INDEX", "vector_index")

# LLM: local Ollama. If it is slow or down, /plan falls back to a rule-based planner.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "25"))
LLM_MODE = os.getenv("LLM_MODE", "auto").lower()  # auto | ollama | fallback

# Embeddings: "minilm" (sentence-transformers all-MiniLM-L6-v2) or "hash" (no deps, demo only).
EMBEDDINGS = os.getenv("EMBEDDINGS", "auto").lower()  # auto | minilm | hash
EMBED_DIMS = 384

TOP_K = int(os.getenv("TOP_K", "5"))
