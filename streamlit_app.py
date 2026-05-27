"""Streamlit Community Cloud entry point.

Streamlit Cloud requires a script *path* to launch (you set "Main file
path" in the deploy form). The canonical CliniTrace launcher lives
inside the package at ``src/clinitrace/ui/streamlit_app.py``, but that
path is awkward for the Cloud deploy form, and it depends on the package
being importable. This wrapper handles both concerns:

  1. Adds ``<repo_root>/src`` to ``sys.path`` so ``import clinitrace``
     resolves whether or not ``pip install -e .`` ran during the Cloud
     build. (Streamlit Cloud DOES read pyproject.toml and install the
     package, but this belt-and-suspenders works around the case where
     the build skips the editable install for any reason.)

  2. Calls the canonical ``main()`` so all the UI logic stays in one
     place inside the package — this wrapper has nothing to maintain
     beyond bootstrapping the import path.

Local dev / CLI path: ``python -m clinitrace ui`` (still works; this
file is the cloud-only entry point).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve src/ relative to THIS file, not the CWD — Streamlit Cloud may
# launch from any working directory.
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from clinitrace.ui.streamlit_app import main  # noqa: E402 — after path setup

main()
