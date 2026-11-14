"""Settings from env vars, or a .env file in agent/ or the repo root (real env vars win)."""
import os
from pathlib import Path


def _load_dotenv():
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
            val = val.split(" #")[0].strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()

DATA_SOURCE = os.getenv("DATA_SOURCE", "mock").lower()          # mock | mongo
MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("DB_NAME") or os.getenv("MONGODB_DB", "outage_agent")
LESSONS = os.getenv("LESSONS_COLLECTION", "lessons")
AUDIT = os.getenv("AUDIT_COLLECTION", "audit_log")
SCHEDULES = os.getenv("SCHEDULES_COLLECTION", "schedules")
LESSON_VECTOR_INDEX = os.getenv("LESSON_VECTOR_INDEX", "lesson_vector_index")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "25"))
LLM_MODE = os.getenv("LLM_MODE", "auto").lower()                # auto | ollama | fallback

EMBEDDINGS = os.getenv("EMBEDDINGS", "auto").lower()            # auto | minilm | hash
EMBED_DIMS = 384

DRAFT_EXPIRY_DAYS = int(os.getenv("DRAFT_EXPIRY_DAYS", "30"))
FORGET_POLICY = os.getenv("FORGET_POLICY", "tombstone").lower() # tombstone | redact
