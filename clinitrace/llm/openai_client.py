"""OpenAI chat client. Same public interface as clinitrace.llm.client
(the Ollama client) so the dispatcher can swap between them without
caring which one is selected.

Endpoint, model, and timeout are configurable via env vars:

  CLINITRACE_OPENAI_KEY      required for live calls (NEVER hard-coded
                              and NEVER persisted to .clinitrace_settings.json;
                              env-only by design)
  CLINITRACE_OPENAI_MODEL    default "gpt-5-mini"
  CLINITRACE_OPENAI_TIMEOUT  default 60 (seconds)
  CLINITRACE_OPENAI_BASE_URL optional — for OpenAI-compatible endpoints
                              (Azure, Together.ai, Groq, local llama.cpp).
                              Leave unset for canonical OpenAI.

JSON output:
  We request ``response_format={"type": "json_object"}``. OpenAI requires
  the word "JSON" to appear somewhere in the prompt for this mode to
  fire; the SR / CG / triage / augmentation prompts in dispatcher.py
  all do that already, so the contract is satisfied.

Error model:
  All failure modes (missing key, network error, malformed response,
  unparseable JSON) surface as OpenAIError. The dispatcher catches it
  and falls back to the stub equivalent — fail-open, same posture as
  the Ollama client.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("clinitrace.llm.openai")


class OpenAIError(RuntimeError):
    """Raised on any failure during an OpenAI chat completion."""


def _config() -> tuple[str | None, str, float, str | None]:
    """Read configuration from env. Returns (key, model, timeout, base_url).

    Key is None when the env var is unset — caller decides whether that's
    a hard error (live call requested but no key) or fine (stub mode).
    """
    key = os.environ.get("CLINITRACE_OPENAI_KEY") or None
    model = os.environ.get("CLINITRACE_OPENAI_MODEL", "gpt-5-mini")
    timeout = float(os.environ.get("CLINITRACE_OPENAI_TIMEOUT", "60"))
    base_url = os.environ.get("CLINITRACE_OPENAI_BASE_URL") or None
    return key, model, timeout, base_url


def model_name() -> str:
    """Return the configured model name (for audit logging)."""
    return _config()[1]


def has_api_key() -> bool:
    """Cheap check the Settings UI uses to render the 'key detected' badge
    without ever displaying the key itself.
    """
    return _config()[0] is not None


def chat_json(system: str, user: str) -> dict[str, Any]:
    """Send a system+user message pair to OpenAI with JSON output mode.

    Returns the parsed JSON object the model produced.
    Raises OpenAIError on any failure (missing key, transport, parse).

    Why we lazy-import openai inside the function:
      - Keeps the package's import graph free of openai when only Ollama
        is used (so users without an OpenAI key never load the SDK).
      - openai's module-level setup is non-trivial (~200ms first import);
        delaying it until first call keeps Streamlit's startup fast.
    """
    key, model, timeout, base_url = _config()
    if not key:
        raise OpenAIError(
            "CLINITRACE_OPENAI_KEY environment variable is not set. "
            "Set it locally in your shell (or on Streamlit Cloud under "
            "Settings -> Secrets) before calling OpenAI."
        )

    try:
        # Lazy import — see docstring.
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OpenAIError(
            "The 'openai' Python package is not installed in this "
            "environment. Add it via `uv pip install openai` or include "
            f"it in pyproject.toml. ({exc})"
        ) from exc

    try:
        client = OpenAI(api_key=key, timeout=timeout, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # JSON-output mode. Note that OpenAI requires the word "JSON"
            # to appear in the prompt; all CliniTrace system prompts do.
            response_format={"type": "json_object"},
            # temperature=0 for reproducibility — same posture as the
            # Ollama client (which sends "temperature": 0.0).
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — openai raises many subclasses
        raise OpenAIError(f"OpenAI API call failed: {exc}") from exc

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise OpenAIError(
            f"OpenAI response shape unexpected: {response!r}"
        ) from exc
    if not content:
        raise OpenAIError("OpenAI returned an empty content string.")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAIError(
            f"OpenAI content was not parseable JSON: {content[:200]!r}"
        ) from exc
