"""Governed-memory app tests (plan/governed-memory-contracts.md).

Runs the agent/ package with no Streamlit, Atlas or Ollama: in-memory store, rule fallbacks, hash embeddings.
If agent/ is not on this branch yet, these tests are skipped instead of failing collection.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
os.environ["DATA_SOURCE"] = "mock"
os.environ["LLM_MODE"] = "fallback"
os.environ["EMBEDDINGS"] = "hash"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if not (ROOT / "agent" / "__init__.py").exists():
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(autouse=True)
def fresh_store():
    try:
        from agent import store
    except ImportError:
        yield
        return
    store.reset()
    yield
