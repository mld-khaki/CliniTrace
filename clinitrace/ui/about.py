"""'About' page content for the CliniTrace Documentation menu.

Renders the page via a single ``render()`` function that mixes Streamlit
primitives:

  - ``st.markdown(html, unsafe_allow_html=True)`` for the prose sections
    and tech-stack table — those are real HTML and Streamlit's markdown
    pipeline handles them cleanly.

  - ``st.code(text, language=None)`` for the repository tree. The previous
    approach (a styled ``<pre>`` inside ``st.markdown``) had its newlines
    collapsed by markdown processing on render — the tree came out as one
    flat run-on line. ``st.code`` preserves whitespace, monospaces the
    font, and adds a copy button for free.

The mixed-primitive approach is a slight break from the
``presentation.GLOSSARY_HTML`` / ``TUTORIAL_HTML`` pattern (which export
a single HTML string), but those two sections are pure prose. The About
page has a code-shaped tree that needs different handling.

Three sections, in render order:
  1. Project overview + author card.
  2. Repository structure walkthrough (with a code-block tree).
  3. Tech stack + architecture decisions.

Editing notes for future maintainers:
  - _LINKEDIN_URL is None by default (LinkedIn row hidden). To add it,
    replace None with a string like "https://www.linkedin.com/in/yourname/"
    and the row appears automatically.
  - Author name + GitHub URL are the two knobs anyone forking the
    project should change. Both are at the top of this file.
  - The repo tree text is a plain string — no HTML — because st.code
    doesn't process HTML. To highlight specific lines, switch the
    `language` argument from None to a sensible filetype hint
    (e.g. 'bash') so the tree gets light syntax colouring.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

log = logging.getLogger("clinitrace.ui.about")


# ---------------------------------------------------------------------------
# Public identity — single source of truth for the About page contact card.
# ---------------------------------------------------------------------------

_AUTHOR_NAME = "Milad Khaki"
_GITHUB_URL = "https://github.com/mld-khaki/CliniTrace"
_LINKEDIN_URL: str | None = None  # set to a URL string to show LinkedIn row

# Author avatar. Resolved relative to THIS file so the path is correct
# regardless of CWD. Set to None to suppress the photo entirely.
# parents[2] is the repo root under the flat layout:
#   <root>/clinitrace/ui/about.py
_AVATAR_PATH: Path | None = (
    Path(__file__).resolve().parents[2] / "docs" / "avatar_milad_khaki.jpg"
)


def _avatar_data_url() -> str | None:
    """Base64-embed the avatar so it ships inline in the HTML.

    Why inline rather than a /static/ URL: Streamlit's static-file
    serving depends on `server.enableStaticServing` and a static/ folder
    next to the entry script. Embedding as a data URL sidesteps both.
    The avatar is ~30 KB, so base64 adds ~10 KB to the About page —
    fine for a page that loads once per session.
    """
    if _AVATAR_PATH is None or not _AVATAR_PATH.exists():
        return None
    try:
        raw = _AVATAR_PATH.read_bytes()
    except OSError as exc:
        log.debug("avatar not loaded (%s): %s", _AVATAR_PATH, exc)
        return None
    # Detect format from magic bytes so we set the right MIME type. PNG
    # starts with \x89PNG, JPEG with \xff\xd8\xff. Default to jpeg.
    if raw.startswith(b"\x89PNG"):
        mime = "image/png"
    else:
        mime = "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _contact_card_html() -> str:
    """Render the author card. Two-column flex layout: avatar on the
    left, name + role + links on the right. Each subcomponent degrades
    gracefully — missing avatar drops the left column, missing LinkedIn
    drops the LinkedIn row.

    Why a flex layout and not a CSS grid: flex with `align-items:center`
    is the simplest cross-browser pattern for "image next to text"
    that handles the case where the right column gets taller (more
    links) without distorting the avatar.
    """
    avatar_url = _avatar_data_url()

    rows: list[tuple[str, str]] = []
    rows.append(("🌐 GitHub", _GITHUB_URL))
    if _LINKEDIN_URL:
        rows.append(("💼 LinkedIn", _LINKEDIN_URL))

    # Build the right-column text block first (we use it whether or not
    # there's an avatar; if no avatar, we just don't wrap it in a flex
    # container).
    right_col_parts = [
        f'<div style="font-size:1.05em;font-weight:600;'
        f'color:#1f1f2a;">{_AUTHOR_NAME}</div>',
        '<div style="color:#6b6b78;font-size:0.9em;'
        'margin-bottom:0.5em;">Author &amp; maintainer</div>',
        '<div style="font-size:0.92em;line-height:1.7;">',
    ]
    for label, url in rows:
        right_col_parts.append(
            f'<div>{label}: <a href="{url}" target="_blank" '
            f'rel="noopener noreferrer">{url}</a></div>'
        )
    right_col_parts.append("</div>")
    right_col_html = "".join(right_col_parts)

    # Card outer styling — unchanged from before.
    card_open = (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;'
        'padding:16px 20px;background:#f9fafb;margin:1em 0;">'
    )
    card_close = "</div>"

    if avatar_url is None:
        # No photo available — fall back to the text-only layout.
        return card_open + right_col_html + card_close

    # Photo present: render as a flex row. The avatar is a fixed-size
    # circle (80px) with a thin border and a subtle shadow. The right
    # column flexes to fill remaining width.
    avatar_html = (
        f'<div style="flex:0 0 auto;margin-right:18px;">'
        f'<img src="{avatar_url}" alt="{_AUTHOR_NAME}" '
        f'style="width:80px;height:80px;border-radius:50%;'
        f'object-fit:cover;border:2px solid #e5e7eb;'
        f'box-shadow:0 1px 3px rgba(0,0,0,0.08);" />'
        f'</div>'
    )
    flex_open = (
        '<div style="display:flex;align-items:center;">'
    )
    return (
        card_open + flex_open + avatar_html
        + '<div style="flex:1 1 auto;">' + right_col_html + '</div>'
        + '</div>' + card_close
    )


# ---------------------------------------------------------------------------
# Section 1 — Project overview
# ---------------------------------------------------------------------------

_OVERVIEW_HTML = """
<h3>CliniTrace</h3>
<p style="color:#1f1f2a;font-size:0.98em;line-height:1.6;">
  <strong>An agentic clinical-data transformation pipeline</strong> with
  human-in-the-loop review, dependency-aware derivation, and per-row
  audit trails. CliniTrace takes a structured mock clinical dataset and
  an Importing Data Contract (IDC); produces an analysis-ready dataset,
  a verification report, and a traceable audit. Six small agents do the
  work; a single Orchestrator schedules them; a Streamlit GUI lets a
  reviewer answer the questions the pipeline raises.
</p>
<p style="color:#1f1f2a;font-size:0.95em;line-height:1.6;">
  The architecture is <strong>hybrid by design</strong>: most agents are
  deterministic (verification, refinement, audit, orchestration) so
  pipeline runs are reproducible for regulatory submission, and LLMs
  are scoped to the two roles where natural-language reasoning genuinely
  adds value — interpreting a rule's clinical rationale to detect
  ambiguity (Spec Reviewer), and normalising free-form rule bodies into
  validated schemas (Code Generator). The agentic memory layer (LTM)
  caches reviewer decisions so the same question never needs answering
  twice.
</p>
"""


# ---------------------------------------------------------------------------
# Section 2 — Repository structure walkthrough
# ---------------------------------------------------------------------------
#
# The tree below is rendered via st.code, NOT st.markdown. Plain text only
# — no HTML, no inline styling. st.code preserves the whitespace and the
# box-drawing characters that the tree relies on.

_REPO_STRUCTURE_INTRO_HTML = """
<h4>Repository structure</h4>
<p style="font-size:0.92em;color:#4b5563;margin-top:-0.3em;">
  High-level map. See the
  <a href="https://github.com/mld-khaki/CliniTrace" target="_blank"
     rel="noopener noreferrer">GitHub source</a> for the full tree.
</p>
"""

_REPO_TREE_TEXT = """\
CliniTrace/
├── streamlit_app.py             # Streamlit Cloud entry point (root wrapper)
├── requirements.txt             # Cloud build deps
├── pyproject.toml               # Local-dev deps + tooling config
├── uv.lock                      # Pinned dependency graph (uv-managed)
├── docs/                        # Wallpaper, screenshots, design notes
├── examples/                    # Demo datasets + IDC YAML files
│   ├── demo_data.csv
│   ├── demo_spec.yaml
│   ├── demo_spec_ambiguous.yaml # Rule-vs-rationale gaps for live LLM demo
│   └── demo_datasets/           # Per-issue clinical-data scenarios
└── clinitrace/                  # Flat package layout (no src/)
    ├── agents/                  # The six agents that do the work
    │   ├── orchestrator.py      #   ⚙️ Sole DAG loop authority
    │   ├── sr.py                #   🤖 Spec Reviewer (LLM)
    │   ├── cg.py                #   🤖 Code Generator (LLM)
    │   ├── refinement.py        #   ⚙️ Deterministic patch table
    │   ├── audit.py             #   ⚙️ Lineage + audit trail writer
    │   ├── spec_triage.py       #   ⚙️ Suggests fixes for unknown rule_kinds
    │   └── spec_generator.py    #   ⚙️ Auto-IDC from dataset (deterministic + LLM)
    ├── llm/                     # Single dispatch fork: stub vs Ollama-live
    ├── rule_kinds/              # Five registered transformations
    │   ├── bin.py, flag.py, duration.py, compound.py, risk_score.py
    │   └── __init__.py          #   REGISTRY: name → (body class, apply fn)
    ├── spec/                    # IDC Pydantic models + YAML loader
    ├── memory/                  # STM (per-run state) + LTM (SQLite across runs)
    ├── verification/            # L1 + L2 + L_p property suites — fully deterministic
    ├── hitl/                    # File-based inbox/outbox for reviewer tickets
    └── ui/                      # Streamlit pages, glossary, settings
        ├── streamlit_app.py     #   Top-level page router
        ├── new_run_wizard.py    #   5-step Import Task wizard
        ├── about.py             #   You are here
        └── ...
"""


# ---------------------------------------------------------------------------
# Section 3 — Tech stack + architecture decisions
# ---------------------------------------------------------------------------

_TECH_STACK_HTML = """
<h4>Tech stack &amp; design decisions</h4>
<p style="font-size:0.92em;color:#4b5563;">
  A short list of the questions a reviewer is likely to ask, with
  one-line answers.
</p>
<table style="width:100%;border-collapse:collapse;font-size:0.92em;
              line-height:1.5;margin-bottom:1em;">
  <thead>
    <tr style="background:#f5f7fb;text-align:left;">
      <th style="padding:6px 10px;border:1px solid #e5e7eb;">Layer</th>
      <th style="padding:6px 10px;border:1px solid #e5e7eb;">Choice</th>
      <th style="padding:6px 10px;border:1px solid #e5e7eb;">Why</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">UI</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Streamlit</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Fastest path to a reviewer-facing GUI without a JS toolchain.
        Trade-off: no async, no streaming during blocking calls.
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">LLM backend</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Local Ollama (default) / stub</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Keeps data on the developer's machine for the live demo.
        Stub mode covers the cloud demo path (no GPU at share.streamlit.io).
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Schemas</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Pydantic v2 (frozen)</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Validates IDC + rule bodies at boundaries. Frozen models are safe
        to pass across agent boundaries without defensive copies.
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">LTM (long-term memory)</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">SQLite</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Single-file, zero ops, easy to inspect with any sqlite client.
        For a real deploy: swap for Turso / Neon / Cloudflare D1.
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Orchestration</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Hand-rolled</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Not LangChain / LangGraph: those frameworks add a runtime layer
        whose internals would need separate validation evidence. Direct
        Python is fewer moving parts to audit.
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">HITL transport</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">File inbox/outbox</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        JSON files under <code>&lt;run_dir&gt;/hitl/{inbox,outbox}</code>.
        Replay-friendly for CI, inspectable, easy to back up.
      </td>
    </tr>
    <tr>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">Tests</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">pytest + Hypothesis</td>
      <td style="padding:6px 10px;border:1px solid #e5e7eb;">
        Property-based testing for rule_kinds (L_p suites). 144 tests as
        of v0.0.1.
      </td>
    </tr>
  </tbody>
</table>

<h4 style="margin-top:1.5em;">Why hybrid (deterministic + LLM) and not fully agentic?</h4>
<p style="font-size:0.92em;line-height:1.6;">
  Regulatory-grade clinical data work demands reproducibility: the same
  input must produce the same output on every run. An LLM in the
  verification, refinement, audit, or orchestration role would break
  that property. So those four agents (V, R, A, O) are pure Python with
  fixed seeds. The two LLM agents (SR, CG) operate <em>between</em>
  well-typed states — they propose options, the deterministic gates
  validate them. The LLM never has the final word.
</p>

<h4 style="margin-top:1.5em;">Where the LLM actually fires</h4>
<ol style="font-size:0.92em;line-height:1.6;">
  <li><strong>SR ambiguity detection</strong> — only when the spec
      author left a non-empty <code>ambiguity_notes</code> field on a
      derivation. Otherwise the entry is treated as explicit and the
      LLM call is skipped.</li>
  <li><strong>CG normalisation</strong> — only when the
      <code>rule_body</code> doesn't validate directly against the
      rule_kind's Pydantic schema. Well-formed bodies short-circuit via
      direct Pydantic match.</li>
  <li><strong>Spec triage</strong> — only when the user wrote a
      <code>rule_kind</code> name that isn't in the registry. Text and
      body-shape signals run first; the LLM is escalation when both are
      weak.</li>
  <li><strong>Spec generation</strong> (auto-suggest IDC from dataset) —
      LLM augmentation runs after the deterministic profiler proposes
      derivations, to catch any clinically-useful ones the patterns
      missed.</li>
</ol>
<p style="font-size:0.92em;line-height:1.6;">
  In all four sites: a deterministic fast path runs first, the LLM is
  escalation, and a human reviewer is the final authority via HITL.
</p>
"""


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render() -> None:
    """Render the full About page.

    Mixes ``st.markdown`` (for the prose / table / contact card sections,
    which are rich HTML) and ``st.code`` (for the repo tree, which needs
    its whitespace preserved). Called from streamlit_app's Documentation
    sub-menu dispatch.
    """
    # Lazy import — keeps the test suite import-light for modules that
    # don't have streamlit installed at all (e.g. CI minimal envs).
    import streamlit as st  # noqa: PLC0415

    # Section 1: overview + contact card. One st.markdown call so the
    # card visually attaches to the prose above it without an extra gap.
    st.markdown(_OVERVIEW_HTML + _contact_card_html(), unsafe_allow_html=True)

    # Section 2: repo structure. Intro paragraph as HTML; tree as a code
    # block so the whitespace + box-drawing characters survive intact.
    st.markdown(_REPO_STRUCTURE_INTRO_HTML, unsafe_allow_html=True)
    st.code(_REPO_TREE_TEXT, language=None)

    # Section 3: tech stack table + architecture discussion.
    st.markdown(_TECH_STACK_HTML, unsafe_allow_html=True)
