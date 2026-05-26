"""Minimal Ollama HTTP client. Uses stdlib only (no httpx/requests dep).

Endpoint, model, and timeout are configurable via env vars:

  CLINITRACE_OLLAMA_URL    default http://localhost:11434
  CLINITRACE_OLLAMA_MODEL  default gpt-oss:20b
  CLINITRACE_OLLAMA_TIMEOUT default 120 (seconds)

The client always requests `format=json` so the model emits parseable JSON.
A parse failure surfaces as OllamaError; the dispatcher decides whether to
fall back to a stub-equivalent path.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns malformed JSON."""


def _config() -> tuple[str, str, float]:
    url = os.environ.get("CLINITRACE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("CLINITRACE_OLLAMA_MODEL", "gpt-oss:20b")
    timeout = float(os.environ.get("CLINITRACE_OLLAMA_TIMEOUT", "120"))
    return url, model, timeout


def chat_json(system: str, user: str) -> dict[str, Any]:
    """Send a system+user message pair to Ollama with format=json. Returns the
    parsed JSON response object. Raises OllamaError on transport or parse
    failure.
    """
    url, model, timeout = _config()
    endpoint = f"{url}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.0},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OllamaError(f"Ollama transport error at {endpoint}: {exc}") from exc

    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Ollama response was not JSON: {body[:200]!r}") from exc

    message = envelope.get("message", {})
    content = message.get("content", "")
    if not content:
        raise OllamaError(f"Ollama response had empty content: {envelope!r}")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaError(
            f"Ollama content was not parseable JSON: {content[:200]!r}"
        ) from exc


def model_name() -> str:
    """Return the configured model name (for audit logging)."""
    return _config()[1]
