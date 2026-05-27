"""LLM dispatch layer.

Only SR and CG call this. Mode is selected by env var CLINITRACE_LLM:

  - "stub" (default): deterministic fixture-driven responses. Used by CI,
    headless demo runs, and any reviewer without an Ollama install.
  - "live":            calls a local Ollama server. Endpoint, model, and
    timeout are configurable via env vars (see llm.client).

Public surface:
  call_sr_ambiguity(entry) -> SrAmbiguityFinding | None
  call_cg_normalize(entry, body_cls) -> CgResult
  current_mode() -> "stub" | "live"
"""

from clinitrace.llm.dispatcher import (
    CgResult,
    SrAmbiguityFinding,
    call_cg_normalize,
    call_sr_ambiguity,
    current_mode,
)

__all__ = [
    "CgResult",
    "SrAmbiguityFinding",
    "call_cg_normalize",
    "call_sr_ambiguity",
    "current_mode",
]
