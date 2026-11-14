"""LLM client. Provider is LLM_PROVIDER: "ollama" (default, stdlib HTTP) or "anthropic" (Claude API,
needs `pip install anthropic` and ANTHROPIC_API_KEY in .env). Every caller has a rule-based fallback,
so failures return None (unless LLM_MODE is "ollama"/"anthropic", i.e. strict)."""
from __future__ import annotations

import json
import re
import urllib.request

from . import config

_last_error = None
_client = None


def available() -> bool:
    return config.LLM_MODE != "fallback"


def provider() -> str:
    return "anthropic" if config.LLM_PROVIDER in ("anthropic", "claude") else "ollama"


def chat(system: str, user: str, as_json: bool = False, timeout: float | None = None):
    """Returns the reply text (or parsed JSON), or None if the LLM is off, slow or broken."""
    global _last_error
    if not available():
        return None
    try:
        if provider() == "anthropic":
            return _anthropic(system, user, as_json, timeout)
        return _ollama(system, user, as_json, timeout)
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"[:200]
        if config.LLM_MODE in ("ollama", "anthropic", "strict"):
            raise
        return None


def _ollama(system, user, as_json, timeout):
    body = {"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(f"{config.OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout or config.OLLAMA_TIMEOUT) as r:
        text = json.loads(r.read())["message"]["content"]
    return json.loads(text) if as_json else text


def _get_client():
    global _client
    if _client is None:
        import anthropic  # optional dependency, imported only when this provider is chosen
        _client = anthropic.Anthropic(timeout=config.ANTHROPIC_TIMEOUT, max_retries=1)  # key from ANTHROPIC_API_KEY
    return _client


def _anthropic(system, user, as_json, timeout):
    if as_json:
        system += "\n\nReply with a single JSON object only, no prose and no code fences."
    client = _get_client()
    if timeout:
        client = client.with_options(timeout=max(timeout, 20.0))
    # Fable 5.2 (and Opus 5.5) always think adaptively; low effort keeps chat answers fast.
    # fallbacks="default": if a safety classifier declines, the API retries on Anthropic's recommended model.
    resp = client.beta.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": config.ANTHROPIC_EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request")
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if not text:
        raise RuntimeError(f"empty reply (stop_reason={resp.stop_reason})")
    if as_json:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0) if m else text)
    return text


def last_error():
    return _last_error
