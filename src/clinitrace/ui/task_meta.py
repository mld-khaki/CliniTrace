"""Per-run task metadata.

Each run directory may contain a ``task_meta.json`` file with reviewer-
friendly metadata about the run. Today this carries one field -- the
user-supplied task name -- but the schema is intentionally a dict so we
can add more (tags, study identifier, source description) without
breaking back-compat with older runs.

The file is optional. Older runs without a meta file fall back to the
run_id-only label.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clinitrace.presentation import humanize_run_id

META_FILE_NAME = "task_meta.json"


def meta_path(run_dir: Path) -> Path:
    return run_dir / META_FILE_NAME


def load(run_dir: Path) -> dict[str, Any]:
    """Return the meta dict for a run, or {} if absent / unreadable."""
    p = meta_path(run_dir)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(run_dir: Path, values: dict[str, Any]) -> Path:
    """Write the meta dict for a run. Overwrites any existing file."""
    p = meta_path(run_dir)
    p.write_text(json.dumps(values, indent=2), encoding="utf-8")
    return p


def task_name(run_dir: Path) -> str | None:
    """Return the user-supplied task name for a run, or None."""
    meta = load(run_dir)
    name = meta.get("task_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def format_run_label(run_dir: Path) -> str:
    """Reviewer-friendly label for a run: '<task name> -- <local timestamp>'
    if a name exists, otherwise just the humanized run_id.

    Used by all run-selector dropdowns so the user sees their own name AND
    the local-timezone timestamp at the same time.
    """
    base = humanize_run_id(run_dir.name)
    name = task_name(run_dir)
    if name:
        return f"{name} -- {base}"
    return base
