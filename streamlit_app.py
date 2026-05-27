"""Streamlit Community Cloud entry point.

Streamlit Cloud requires a script *path* to launch (you set "Main file
path" in the deploy form). The canonical CliniTrace launcher lives
inside the package at ``clinitrace/ui/streamlit_app.py``, but a path
that deep in the tree is awkward for the deploy form, and it depends on
the package being importable. This thin wrapper handles both concerns:

  1. Adds the repo root to ``sys.path`` so ``import clinitrace``
     resolves whether or not the package was installed via
     ``pip install -e .``. (Streamlit Cloud DOES install from
     pyproject.toml, but the explicit sys.path is a belt-and-suspenders
     fallback if the build skips the editable install for any reason.)

  2. Calls the canonical ``main()`` so all the UI logic stays in one
     place inside the package — this wrapper has nothing to maintain
     beyond the import bootstrap.

Layout note:
  This project uses the **flat** Python layout (clinitrace/ at the repo
  root, not src/clinitrace/). The flat layout is the canonical default
  that every installer (pip, uv, hatch, poetry) understands without
  explicit ``package-dir`` hints. We moved from src/ → flat because
  Streamlit Cloud's `uv` installer was failing pre-build checks on the
  src/ layout.

Local dev / CLI path: ``python -m clinitrace ui`` (still works; this
file is the cloud-only entry point).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add the repo root to sys.path so ``import clinitrace`` resolves even
# when the package isn't installed. Resolved relative to THIS file, not
# the CWD, since Streamlit Cloud can launch from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from clinitrace.ui.streamlit_app import main  # noqa: E402 — after path setup

main()
