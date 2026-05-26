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


DEFAULTS: dict[str, Any] = {
    "display_tz": "UTC",
    "out_dir": "demo_out",
    "ltm_path": "demo_ltm.db",
    "llm_enabled": False,
    "llm_backend": "Local (Ollama)",
    "llm_url": "http://localhost:11434",
    "llm_model": "gpt-oss:20b",
    "llm_timeout": 120.0,
}


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

    Display-only settings (timezone, paths used by the UI) are NOT pushed
    here -- the caller wires those into session_state and presentation
    explicitly.
    """
    os.environ["CLINITRACE_LLM"] = "live" if values.get("llm_enabled") else "stub"
    if values.get("llm_url"):
        os.environ["CLINITRACE_OLLAMA_URL"] = str(values["llm_url"])
    if values.get("llm_model"):
        os.environ["CLINITRACE_OLLAMA_MODEL"] = str(values["llm_model"])
    if values.get("llm_timeout") is not None:
        os.environ["CLINITRACE_OLLAMA_TIMEOUT"] = str(values["llm_timeout"])
