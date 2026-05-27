"""Settings persistence for the Streamlit UI.

Loads and saves a small JSON file (``.clinitrace_settings.json``) in the
current working directory so user preferences survive a Streamlit restart.

The store handles only UI display preferences and LLM dispatcher config -- it
does NOT touch the audit trail, LTM, or any pipeline state. Everything here
is purely cosmetic / dispatch configuration.

Why a flat JSON file (not env vars only):
  - env vars are per-process; restarting Streamlit loses them
  - a config file is auditable and editable outside the UI
  - small enough that the user can grep it in support requests

Why CWD-relative (not ~/.clinitrace):
  - matches the rest of the app (out_dir, ltm_path are CWD-relative)
  - lets a study lead keep different settings per study folder
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_FILE_NAME = ".clinitrace_settings.json"


# Canonical labels for the LLM backend selector. Used by both this
# module and the Settings UI; kept in sync so a value saved on disk
# matches a radio option exactly.
BACKEND_OLLAMA = "Local (Ollama)"
BACKEND_OPENAI = "OpenAI API"
BACKEND_OPTIONS = (BACKEND_OLLAMA, BACKEND_OPENAI)


DEFAULTS: dict[str, Any] = {
    "display_tz": "UTC",
    "out_dir": "demo_out",
    "ltm_path": "demo_ltm.db",
    "llm_enabled": False,
    # Backend selector: "Local (Ollama)" or "OpenAI API".
    "llm_backend": BACKEND_OLLAMA,
    # Ollama-specific (used when llm_backend == BACKEND_OLLAMA).
    "llm_url": "http://localhost:11434",
    "llm_model": "gpt-oss:20b",
    "llm_timeout": 120.0,
    # OpenAI-specific (used when llm_backend == BACKEND_OPENAI). The API
    # key itself is read from CLINITRACE_OPENAI_KEY (env-only by design)
    # and is NEVER persisted to .clinitrace_settings.json — that's why
    # there's no "openai_api_key" entry here.
    "openai_model": "gpt-5-mini",
    "openai_timeout": 60.0,
}


def is_cloud_demo() -> bool:
    """True when the app is running on Streamlit Community Cloud (or any
    environment that explicitly opts into cloud-demo mode).

    Detection precedence (first that matches wins):

      1. ``CLINITRACE_CLOUD_DEMO`` env var set to a truthy value. Easiest
         to set on Streamlit Cloud — just add it under Settings > Secrets
         on share.streamlit.io and it appears as an env var to the app.

      2. Streamlit's own ``IS_RUNNING_IN_STREAMLIT_CLOUD`` hint, if
         present (set by the Cloud runtime in some images).

      3. The presence of the canonical Cloud mount path ``/mount/src``,
         which is where share.streamlit.io extracts the repo.

    Why a function and not a module-level constant: env vars can change
    between worker restarts on Cloud, and tests need to be able to
    monkeypatch without re-importing the module.
    """
    if os.environ.get("CLINITRACE_CLOUD_DEMO", "").lower() in ("1", "true", "yes", "on"):
        return True
    if os.environ.get("IS_RUNNING_IN_STREAMLIT_CLOUD"):
        return True
    return bool(Path("/mount/src").exists())


def config_path() -> Path:
    return Path.cwd() / CONFIG_FILE_NAME


def load() -> dict[str, Any]:
    """Return settings merged with defaults. Missing file -> defaults."""
    out = dict(DEFAULTS)
    p = config_path()
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            out.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    return out


def save(values: dict[str, Any]) -> Path:
    """Write only known keys to the config file. Returns the file path."""
    to_save = {k: values[k] for k in DEFAULTS if k in values}
    p = config_path()
    p.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
    return p


def reset() -> Path | None:
    """Delete the config file (return to defaults). Returns deleted path or
    None if no file existed."""
    p = config_path()
    if p.exists():
        p.unlink()
        return p
    return None


def hard_reset_summary(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a preview of what hard_reset() would do given the user's selections.

    Looks at the configured out_dir and ltm_path (current values, not
    defaults — otherwise the preview can lie about which file the user is
    actually about to lose). Returns a dict keyed by category:

        {
          "settings_file": {"path": ..., "exists": bool, "size": int},
          "ltm_db":        {"path": ..., "exists": bool, "size": int},
          "task_history":  {"path": ..., "exists": bool,
                            "runs": int, "size": int},
        }

    No filesystem mutation here — caller previews, then calls hard_reset.
    """
    ltm_path = Path(values.get("ltm_path") or DEFAULTS["ltm_path"])
    out_dir = Path(values.get("out_dir") or DEFAULTS["out_dir"])
    cfg = config_path()

    def _size(p: Path) -> int:
        try:
            return p.stat().st_size if p.exists() else 0
        except OSError:
            return 0

    def _dir_stats(p: Path) -> tuple[int, int]:
        if not p.exists() or not p.is_dir():
            return (0, 0)
        runs = 0
        total = 0
        for child in p.iterdir():
            if child.is_dir() and child.name.startswith("run-"):
                runs += 1
            try:
                for f in child.rglob("*") if child.is_dir() else [child]:
                    if f.is_file():
                        total += f.stat().st_size
            except OSError:
                continue
        return (runs, total)

    runs_count, runs_size = _dir_stats(out_dir)
    return {
        "settings_file": {
            "path": cfg, "exists": cfg.exists(), "size": _size(cfg),
        },
        "ltm_db": {
            "path": ltm_path, "exists": ltm_path.exists(), "size": _size(ltm_path),
        },
        "task_history": {
            "path": out_dir,
            "exists": out_dir.exists(),
            "runs": runs_count,
            "size": runs_size,
        },
    }


def hard_reset(
    *,
    clear_settings: bool,
    clear_ltm: bool,
    clear_history: bool,
    ltm_path: str | Path | None,
    out_dir: str | Path | None,
) -> list[str]:
    """Perform the actual deletes. Returns a list of plain-language strings
    describing what was removed (one per category that ran). Safe to call
    with all flags False — that returns an empty list and touches nothing.

    Each branch is wrapped so a failure in one (e.g. permission denied on
    the LTM file because a Streamlit thread still has it open) does not
    block the others. Errors surface in the returned strings.
    """
    import shutil

    actions: list[str] = []

    if clear_settings:
        try:
            removed = reset()
            actions.append(
                f"Removed settings file ({removed.name})."
                if removed is not None
                else "Settings file did not exist; nothing to remove."
            )
        except OSError as exc:
            actions.append(f"Could not remove settings file: {exc}.")

    if clear_ltm and ltm_path is not None:
        p = Path(ltm_path)
        if p.exists():
            try:
                p.unlink()
                actions.append(f"Removed LTM database ({p.name}).")
            except OSError as exc:
                actions.append(f"Could not remove LTM database: {exc}.")
        else:
            actions.append("LTM database did not exist; nothing to remove.")

    if clear_history and out_dir is not None:
        p = Path(out_dir)
        if p.exists() and p.is_dir():
            removed_dirs = 0
            errs: list[str] = []
            for child in list(p.iterdir()):
                # Only remove run-* subdirectories. Anything else in out_dir
                # (e.g. a README) is user data and should not be touched.
                if child.is_dir() and child.name.startswith("run-"):
                    try:
                        shutil.rmtree(child)
                        removed_dirs += 1
                    except OSError as exc:
                        errs.append(f"{child.name}: {exc}")
            if errs:
                actions.append(
                    f"Removed {removed_dirs} task run(s); could not remove "
                    f"{len(errs)} ({errs[0]}{'…' if len(errs) > 1 else ''})."
                )
            else:
                actions.append(f"Removed {removed_dirs} task run(s).")
        else:
            actions.append("Task-history directory did not exist; nothing to remove.")

    return actions


def apply_to_environment(values: dict[str, Any]) -> None:
    """Push LLM-related settings into env vars so the dispatcher sees them.

    All Ollama-specific AND all OpenAI-specific env vars are written
    every call — the dispatcher's backend selector (CLINITRACE_LLM_BACKEND)
    decides which set is actually consulted. Writing both keeps Settings
    page edits to the "non-active" backend persistent across mode flips.

    Notably absent: CLINITRACE_OPENAI_KEY. The API key is env-only by
    design (never persisted to .clinitrace_settings.json), so this
    function doesn't manage it — set it in your shell rc, or on
    Streamlit Cloud via Settings -> Secrets.

    Display-only settings (timezone, paths used by the UI) are NOT pushed
    here -- the caller wires those into session_state and presentation
    explicitly.
    """
    os.environ["CLINITRACE_LLM"] = "live" if values.get("llm_enabled") else "stub"

    # Backend selector. The dispatcher reads this to pick which client
    # module handles chat_json. Default "ollama" preserves existing
    # behavior for callers that don't touch the new selector.
    backend_label = values.get("llm_backend", BACKEND_OLLAMA)
    backend_env = "openai" if backend_label == BACKEND_OPENAI else "ollama"
    os.environ["CLINITRACE_LLM_BACKEND"] = backend_env

    # Ollama-specific env vars.
    if values.get("llm_url"):
        os.environ["CLINITRACE_OLLAMA_URL"] = str(values["llm_url"])
    if values.get("llm_model"):
        os.environ["CLINITRACE_OLLAMA_MODEL"] = str(values["llm_model"])
    if values.get("llm_timeout") is not None:
        os.environ["CLINITRACE_OLLAMA_TIMEOUT"] = str(values["llm_timeout"])

    # OpenAI-specific env vars (model + timeout only; key is env-only).
    if values.get("openai_model"):
        os.environ["CLINITRACE_OPENAI_MODEL"] = str(values["openai_model"])
    if values.get("openai_timeout") is not None:
        os.environ["CLINITRACE_OPENAI_TIMEOUT"] = str(values["openai_timeout"])


def openai_api_key_present() -> bool:
    """True iff CLINITRACE_OPENAI_KEY is set to a non-empty value.

    Settings UI uses this to render a 'key detected' badge without ever
    displaying the key itself. Cloud-demo unlock logic uses it to decide
    whether to permit the LLM toggle on share.streamlit.io.
    """
    return bool(os.environ.get("CLINITRACE_OPENAI_KEY", "").strip())


def any_live_backend_available() -> bool:
    """True when at least one live backend has the necessary credentials.

    - Ollama needs a reachable URL; on the cloud demo it almost certainly
      doesn't have one (no localhost), so we treat Ollama as "available
      only when not on cloud". Locally, Ollama is always treated as
      available (the user is expected to run `ollama serve` if they want
      live mode).
    - OpenAI needs CLINITRACE_OPENAI_KEY in env.

    Used by the Settings UI to gate the LLM-enable toggle on the cloud
    demo: if NO backend has credentials, the toggle stays locked.
    """
    if openai_api_key_present():
        return True
    # Local dev: assume the user can spin up Ollama if they want to.
    return not is_cloud_demo()
