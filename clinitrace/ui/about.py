"""'About' page content for the CliniTrace Documentation menu.

Mirrors the structure of presentation.GLOSSARY_HTML and TUTORIAL_HTML:
exports a single ABOUT_HTML string the Streamlit page renders via
``st.markdown(ABOUT_HTML, unsafe_allow_html=True)``.

Keeping the content here (in the UI package) rather than in
presentation.py because this is a UI-only artifact — it has no bearing
on the pipeline, the audit trail, or anything outside the GUI.

Three sections, in this order:
  1. Project overview + author card (who built it, where to find it).
  2. Repository structure walkthrough (high-level map of the codebase).
  3. Tech stack + architecture decisions (anticipates the 'why X and
     not Y?' question that a reviewer will ask).

Editing notes for future maintainers:
  - _LINKEDIN_URL is None by default (LinkedIn row hidden). To add it,
    replace None with a string like "https://www.linkedin.com/in/yourname/"
    and the row appears automatically.
  - Author name and GitHub URL are derived from pyproject.toml so a fork
    can update _AUTHOR_NAME and _GITHUB_URL once and re-render correctly.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Public identity — single source of truth for the About page contact card.
# ---------------------------------------------------------------------------

_AUTHOR_NAME = "Milad Khaki"

# GitHub URL — derived from the repo this code lives in. If you fork the
# project, update this to point at your own fork so the About page shows
# the correct source link.
_GITHUB_URL = "https://github.com/mld-khaki/CliniTrace"

# LinkedIn URL. Set to None (default) to hide the LinkedIn row entirely
# — that's the current choice for the public cloud demo. Set to a full
# URL (e.g. "https://www.linkedin.com/in/yourname/") to show a LinkedIn
# row in the contact card.
_LINKEDIN_URL: str | None = None


def _contact_card_html() -> str:
    """Render the author card, hiding any contact channel that's missing
    or still set to its placeholder value. Keeps the page from showing a
    broken LinkedIn link if the maintainer hasn't filled in their URL.
    """
    lines = [
        '<div style="border:1px solid #e5e7eb;border-radius:8px;'
        'padding:16px 20px;background:#f9fafb;margin:1em 0;">'
    ]
    lines.append(f'<div style="font-size:1.05em;font-weight:600;'
                 f'color:#1f1f2a;">{_AUTHOR_NAME}</div>')
    lines.append('<div style="color:#6b6b78;font-size:0.9em;'
                 'margin-bottom:0.5em;">'
                 'Author &amp; maintainer</div>')

    rows: list[tuple[str, str]] = []
    rows.append(("🌐 GitHub", _GITHUB_URL))
    if _LINKEDIN_URL:
        rows.append(("💼 LinkedIn", _LINKEDIN_URL))

    lines.append('<div style="font-size:0.92em;line-height:1.7;">')
    for label, url in rows:
        lines.append(
            f'<div>{label}: <a href="{url}" target="_blank" '
            f'rel="noopener noreferrer">{url}</a></div>'
        )
    lines.append('</div>')
    lines.append('</div>')
    return "".join(lines)


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
# Kept high-level: a reviewer browsing the deployed demo doesn't need
# every subfolder, just the architectural shape. Anyone wanting more
# detail can click through to GitHub.

_REPO_STRUCTURE_HTML = """
<h4>Repository structure</h4>
<p style="font-size:0.92em;color:#4b5563;margin-top:-0.3em;">
  High-level map. See the
  <a href="https://github.com/mld-khaki/CliniTrace" target="_blank"
     rel="noopener noreferrer">GitHub source</a> for the full tree.
</p>
<pre style="background:#f5f7fb;border:1px solid #e5e7eb;border-radius:6px;
            padding:12px 16px;font-size:0.85em;line-height:1.5;
            color:#1f1f2a;overflow-x:auto;"><span style="color:#313EF3;
            font-weight:600;">CliniTrace/</span>
├── streamlit_app.py           <span style="color:#6b6b78;"># Streamlit Cloud entry point (root wrapper)</span>
├── requirements.txt           <span style="color:#6b6b78;"># Cloud build deps</span>
├── pyproject.toml             <span style="color:#6b6b78;"># Local-dev deps + tooling config</span>
├── docs/                      <span style="color:#6b6b78;"># Wallpaper, screenshots, design notes</span>
├── examples/                  <span style="color:#6b6b78;"># Demo datasets + IDC YAML files</span>
│   ├── demo_data.csv
│   ├── demo_spec.yaml
│   ├── demo_spec_ambiguous.yaml   <span style="color:#6b6b78;"># Rule-vs-rationale gaps for live LLM demo</span>
│   └── demo_datasets/             <span style="color:#6b6b78;"># Per-issue clinical-data scenarios</span>
└── clinitrace/                <span style="color:#6b6b78;"># Flat package layout (no src/)</span>
    ├── agents/                <span style="color:#6b6b78;"># The six agents that do the work</span>
    │   ├── orchestrator.py    <span style="color:#6b6b78;">#   ⚙️ Sole DAG loop authority</span>
    │   ├── sr.py              <span style="color:#6b6b78;">#   🤖 Spec Reviewer (LLM)</span>
    │   ├── cg.py              <span style="color:#6b6b78;">#   🤖 Code Generator (LLM)</span>
    │   ├── refinement.py      <span style="color:#6b6b78;">#   ⚙️ Deterministic patch table</span>
    │   ├── audit.py           <span style="color:#6b6b78;">#   ⚙️ Lineage + audit trail writer</span>
    │   ├── spec_triage.py     <span style="color:#6b6b78;">#   ⚙️ Suggests fixes for unknown rule_kinds</span>
    │   └── spec_generator.py  <span style="color:#6b6b78;">#   ⚙️ Auto-IDC from dataset (deterministic + LLM)</span>
    ├── llm/                   <span style="color:#6b6b78;"># Single dispatch fork: stub vs Ollama-live</span>
    ├── rule_kinds/            <span style="color:#6b6b78;"># Five registered transformations</span>
    │   ├── bin.py, flag.py, duration.py, compound.py, risk_score.py
    │   └── __init__.py        <span style="color:#6b6b78;">#   REGISTRY: name → (body class, apply fn)</span>
    ├── spec/                  <span style="color:#6b6b78;"># IDC Pydantic models + YAML loader</span>
    ├── memory/                <span style="color:#6b6b78;"># STM (per-run state) + LTM (SQLite across runs)</span>
    ├── verification/          <span style="color:#6b6b78;"># L1 + L2 + L_p property suites — fully deterministic</span>
    ├── hitl/                  <span style="color:#6b6b78;"># File-based inbox/outbox for reviewer tickets</span>
    └── ui/                    <span style="color:#6b6b78;"># Streamlit pages, glossary, settings</span>
        ├── streamlit_app.py   <span style="color:#6b6b78;">#   Top-level page router</span>
        ├── new_run_wizard.py  <span style="color:#6b6b78;">#   5-step Import Task wizard</span>
        ├── about.py           <span style="color:#6b6b78;">#   You are here</span>
        └── ...
</pre>
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
# Public composed HTML (concatenated in render order)
# ---------------------------------------------------------------------------


def render_html() -> str:
    """Return the full About page HTML, ready for st.markdown.

    Wrapping the contact card in a function (not a module-level string)
    means a future change that hides LinkedIn / GitHub conditionally
    only needs to edit one place.
    """
    return (
        _OVERVIEW_HTML
        + _contact_card_html()
        + _REPO_STRUCTURE_HTML
        + _TECH_STACK_HTML
    )


# Module-level alias so the streamlit_app dispatch reads identically to
# the existing GLOSSARY_HTML / TUTORIAL_HTML pattern.
ABOUT_HTML = render_html()
