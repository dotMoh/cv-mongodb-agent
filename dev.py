"""Cross-platform runner (Windows PowerShell, macOS, Linux).

  python dev.py          Streamlit app (streamlit run frontend/app.py) on mock data: no Atlas, no Ollama
  python dev.py live     same app, loads .env (Atlas + Ollama)
  python dev.py test     test suite, then the demo script in mock mode
Ctrl-C stops it.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable  # the venv's python if you activated one
MOCK = {"DATA_SOURCE": "mock", "LLM_MODE": "fallback", "EMBEDDINGS": "hash"}


def load_env(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ[key.strip()] = value


def test():
    code = subprocess.call([PY, "-m", "pytest", "-rs"], cwd=ROOT)
    if (ROOT / "agent" / "demo.py").exists() and (ROOT / "data" / "samples" / "u4_outage_24h.csv").exists():
        print("--- demo smoke run (agent.demo, mock mode) ---")
        demo = subprocess.call([PY, "-m", "agent.demo"], cwd=ROOT, env=dict(os.environ, **MOCK),
                               stdout=subprocess.DEVNULL)
        print("demo OK" if demo == 0 else "demo FAILED")
        code = code or demo
    return code


def streamlit(mode):
    if mode == "live":
        env_file = ROOT / ".env"
        if not env_file.exists():
            sys.exit("No .env. Copy .env.example to .env and fill in MONGODB_URI.")
        load_env(env_file)
    else:
        os.environ.update({k: os.environ.get(k, v) if k != "DATA_SOURCE" else v for k, v in MOCK.items()})
    app = ROOT / "frontend" / "app.py"
    if not app.exists():
        sys.exit("No frontend/app.py yet (the Streamlit app). Pull the latest main.")
    print(f"Streamlit on http://localhost:8501  (DATA_SOURCE={os.environ.get('DATA_SOURCE')}, LLM_MODE={os.environ.get('LLM_MODE', 'auto')})")
    try:
        return subprocess.call([PY, "-m", "streamlit", "run", str(app), "--server.port", "8501"], cwd=ROOT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "mock"
    if mode == "test":
        sys.exit(test())
    if mode in ("mock", "live"):
        sys.exit(streamlit(mode))
    sys.exit(__doc__)
