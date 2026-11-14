"""Ollama client (stdlib only). Every caller has a rule-based fallback, so failures return None."""
from __future__ import annotations

import json
import urllib.request

from . import config

_last_error = None


def available() -> bool:
    return config.LLM_MODE != "fallback"


def chat(system: str, user: str, as_json: bool = False, timeout: float | None = None):
    """Returns the reply text (or parsed JSON), or None if Ollama is off, slow or broken."""
    global _last_error
    if not available():
        return None
    body = {"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(f"{config.OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.OLLAMA_TIMEOUT) as r:
            text = json.loads(r.read())["message"]["content"]
        return json.loads(text) if as_json else text
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"[:200]
        if config.LLM_MODE == "ollama":
            raise
        return None


def last_error():
    return _last_error
