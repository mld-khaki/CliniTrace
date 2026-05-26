"""Multi-step 'Start new run' wizard for CliniTrace.

Mirrors the Excel-import experience: upload -> preview/configure ->
spec -> run -> results. State lives in st.session_state under the
``wizard_*`` namespace so each step can be re-entered without losing
the user's prior choices.

This module renders a single function ``render()`` that the top-level
streamlit_app calls when the user picks 'Start new run' from the menu.
"""

from __future__ import annotations

import html
import io
import json
import re
import sqlite3
import tempfile
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from clinitrace.agents import orchestrator as orch
from clinitrace.agents import spec_generator
from clinitrace.llm import current_mode
from clinitrace.memory import LTM
from clinitrace.presentation import humanize_timestamp
from clinitrace.spec import load_spec
from clinitrace.spec.model import Spec
from clinitrace.ui import glossary, llm_indicator, task_meta


_ISO_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})"
)


def _humanize_iso_in_text(text: str) -> str:
    return _ISO_TS_RE.sub(lambda m: humanize_timestamp(m.group(0)), text)


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------


_WIZARD_KEYS = [
    "wizard_step",
    "wizard_task_name",
    "wizard_dataset_name",
    "wizard_dataset_bytes",
    "wizard_dataset_kind",          # "csv" | "parquet" | "sqlite"
    "wizard_csv_sep",
    "wizard_csv_header_row",
    "wizard_csv_encoding",
    "wizard_sqlite_table",
    "wizard_dataset",               # parsed pd.DataFrame
    "wizard_column_types",          # dict[col, dtype-name]
    "wizard_spec_source",           # "upload" | "example" | "existing"
    "wizard_spec_bytes",
    "wizard_spec_name",
    "wizard_spec_obj",              # Spec
    "wizard_out_dir",
    "wizard_ltm_path",
    "wizard_run_result",
    "wizard_run_error",
]


def _init_state() -> None:
    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 1
    for key in _WIZARD_KEYS:
        st.session_state.setdefault(key, None)
    if st.session_state["wizard_csv_sep"] is None:
        st.session_state["wizard_csv_sep"] = ","
    if st.session_state["wizard_csv_header_row"] is None:
        st.session_state["wizard_csv_header_row"] = 0
    if st.session_state["wizard_csv_encoding"] is None:
        st.session_state["wizard_csv_encoding"] = "utf-8"
    if st.session_state["wizard_out_dir"] is None:
        st.session_state["wizard_out_dir"] = "demo_out"
    if st.session_state["wizard_ltm_path"] is None:
        st.session_state["wizard_ltm_path"] = "demo_ltm.db"


def _reset_wizard() -> None:
    for key in _WIZARD_KEYS:
        st.session_state.pop(key, None)
    _init_state()


def _set_step(step: int) -> None:
    st.session_state["wizard_step"] = step


# ---------------------------------------------------------------------------
# Step header (progress bar)
# ---------------------------------------------------------------------------


_STEP_TITLES = {
    1: "1. Name & upload",
    2: "2. Preview & configure",
    3: "3. Choose IDC",
    4: "4. Run",
    5: "5. Results",
}


def _render_stepper(current: int) -> None:
    cols = st.columns(len(_STEP_TITLES))
    for idx, (step, title) in enumerate(_STEP_TITLES.items()):
        with cols[idx]:
            if step < current:
                st.markdown(f"✅ **{title}**")
            elif step == current:
                st.markdown(f"🔵 **{title}**")
            else:
                st.markdown(f"⚪ {title}")
    st.divider()


# ---------------------------------------------------------------------------
# Step 1: Upload dataset
# ---------------------------------------------------------------------------


def _detect_kind(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".csv") or name.endswith(".tsv"):
        return "csv"
    if name.endswith(".parquet") or name.endswith(".pq"):
        return "parquet"
    if name.endswith(".db") or name.endswith(".sqlite") or name.endswith(".sqlite3"):
        return "sqlite"
    return None


def _render_step_upload() -> None:
    st.subheader("Step 1 — Name your task and upload data")
    st.caption(
        "Give this import task a memorable name (e.g. *Phase 2 May 2026*) "
        "so you can find it later. Then drop a CSV, Parquet, or SQLite file."
    )

    task_name_default = st.session_state.get("wizard_task_name") or ""
    new_name = st.text_input(
        "Task name",
        value=task_name_default,
        key="wizard_task_name_input",
        max_chars=80,
        placeholder="e.g. Phase 2 Trial – May 2026",
        help=(
            "Shows up everywhere this task is referenced — Run history, "
            "Review questions, summaries. Optional but strongly recommended."
        ),
    )
    st.session_state["wizard_task_name"] = new_name.strip() or None

    uploaded = st.file_uploader(
        "Drag and drop a dataset here",
        type=["csv", "tsv", "parquet", "pq", "db", "sqlite", "sqlite3"],
        accept_multiple_files=False,
        key="wizard_uploader",
    )

    if uploaded is None:
        st.info(
            "No file selected yet. Example files live under the repo's "
            "`examples/` folder (`demo_data.csv`)."
        )
        return

    kind = _detect_kind(uploaded.name)
    if kind is None:
        st.error(f"Unsupported file type: {uploaded.name}")
        return

    raw = uploaded.read()
    st.session_state["wizard_dataset_name"] = uploaded.name
    st.session_state["wizard_dataset_bytes"] = raw
    st.session_state["wizard_dataset_kind"] = kind

    size_kb = len(raw) / 1024
    st.success(
        f"Loaded **{uploaded.name}** ({kind.upper()}, {size_kb:,.1f} KB)."
    )
    cols = st.columns([1, 1, 1])
    cols[0].metric("File", uploaded.name)
    cols[1].metric("Format", kind.upper())
    cols[2].metric("Size", f"{size_kb:,.1f} KB")

    if st.button("Next: preview & configure →", type="primary"):
        _set_step(2)
        st.rerun()


# ---------------------------------------------------------------------------
# Step 2: Preview & configure
# ---------------------------------------------------------------------------


def _parse_dataset() -> pd.DataFrame | None:
    """Parse the uploaded bytes using current configuration."""
    raw = st.session_state["wizard_dataset_bytes"]
    kind = st.session_state["wizard_dataset_kind"]
    if raw is None or kind is None:
        return None
    try:
        if kind == "csv":
            return pd.read_csv(
                io.BytesIO(raw),
                sep=st.session_state["wizard_csv_sep"],
                header=st.session_state["wizard_csv_header_row"],
                encoding=st.session_state["wizard_csv_encoding"],
            )
        if kind == "parquet":
            return pd.read_parquet(io.BytesIO(raw))
        if kind == "sqlite":
            # SQLite needs a real file on disk; write to a temp file.
            with tempfile.NamedTemporaryFile(
                suffix=".db", delete=False
            ) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            conn = sqlite3.connect(tmp_path)
            try:
                tables = pd.read_sql_query(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                    conn,
                )["name"].tolist()
                if not tables:
                    st.error("No tables found in the SQLite file.")
                    return None
                table = st.session_state.get("wizard_sqlite_table") or tables[0]
                if table not in tables:
                    table = tables[0]
                st.session_state["wizard_sqlite_table"] = table
                st.session_state["_sqlite_tables_cache"] = tables
                return pd.read_sql_query(
                    f"SELECT * FROM {table}", conn  # noqa: S608
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse the file with the current settings: {exc}")
        return None
    return None


def _render_step_preview() -> None:
    st.subheader("Step 2 — Preview & configure")
    st.caption(
        "Confirm the file parses correctly. Tweak the options on the left "
        "if columns look wrong."
    )

    if st.session_state["wizard_dataset_bytes"] is None:
        st.warning("Go back to Step 1 and upload a file first.")
        if st.button("← Back to upload"):
            _set_step(1)
            st.rerun()
        return

    kind = st.session_state["wizard_dataset_kind"]

    cfg_col, preview_col = st.columns([1, 3])

    with cfg_col:
        st.markdown("**Parsing options**")
        if kind == "csv":
            st.text_input(
                "Delimiter",
                value=st.session_state["wizard_csv_sep"],
                key="wizard_csv_sep",
                help="Try `,` `;` `\\t` (tab) or `|`.",
            )
            st.number_input(
                "Header row (0 = first row)",
                min_value=0,
                max_value=10,
                value=st.session_state["wizard_csv_header_row"],
                key="wizard_csv_header_row",
            )
            st.selectbox(
                "Encoding",
                options=["utf-8", "utf-16", "latin-1", "cp1252"],
                index=0,
                key="wizard_csv_encoding",
            )
        elif kind == "sqlite":
            # Need to parse once to populate the tables list.
            _ = _parse_dataset()
            tables = st.session_state.get("_sqlite_tables_cache", [])
            if tables:
                st.selectbox(
                    "Table",
                    options=tables,
                    index=tables.index(st.session_state["wizard_sqlite_table"])
                    if st.session_state["wizard_sqlite_table"] in tables
                    else 0,
                    key="wizard_sqlite_table",
                )
        else:
            st.caption("No options for Parquet — schema is embedded.")

    df = _parse_dataset()
    if df is None:
        return
    st.session_state["wizard_dataset"] = df

    with preview_col:
        st.markdown(f"**Preview** — {len(df):,} rows × {len(df.columns)} columns")
        st.dataframe(df.head(20), width="stretch", height=300)

        st.markdown("**Detected column types** (override below if needed)")
        type_df = pd.DataFrame(
            {
                "column": df.columns,
                "detected": [str(t) for t in df.dtypes],
                "non_null": [int(df[c].notna().sum()) for c in df.columns],
                "sample": [
                    str(df[c].dropna().iloc[0]) if df[c].notna().any() else ""
                    for c in df.columns
                ],
            }
        )
        st.dataframe(type_df, width="stretch", height=200)

    nav_a, nav_b, nav_c = st.columns([1, 1, 6])
    with nav_a:
        if st.button("← Back"):
            _set_step(1)
            st.rerun()
    with nav_b:
        if st.button("Next →", type="primary"):
            _set_step(3)
            st.rerun()


# ---------------------------------------------------------------------------
# Step 3: Choose specification
# ---------------------------------------------------------------------------


def _stage1_plan(spec: Spec, ltm: LTM, mode: str) -> list[dict[str, object]]:
    """Pre-flight Stage 1 plan: what SR will do for each entry, decided
    BEFORE the orchestrator runs.

    Streamlit cannot repaint during the blocking orch.run() call, so a
    live per-entry progress indicator isn't physically possible without
    streaming or threading-based refactors that this codebase doesn't yet
    have. The next-best honest signal is to compute the plan up front and
    render it as a table — the user sees, per entry: "this will use LTM
    cache" vs "this will call the LLM" vs "this will short-circuit
    because no ambiguity_notes is set" — before any LLM call fires.

    Decision rules mirror the actual logic in agents/sr.py:_review_one:
      1. LTM hit on ambiguity_signature → "ltm cache"
      2. ambiguity_notes is blank → "skip (no notes)"  [matches the
         live-mode short-circuit added recently]
      3. live mode + non-blank notes → "🤖 call LLM"
      4. stub mode + non-blank notes → "⚙️ stub heuristic"
    """
    plan: list[dict[str, object]] = []
    for entry in spec.derivations:
        sig = entry.ambiguity_signature()
        ltm_hit = ltm.find_ambiguity_resolution(sig) is not None
        notes_present = bool(entry.ambiguity_notes and entry.ambiguity_notes.strip())

        if ltm_hit:
            decision = "📁 LTM cache"
            cost = "no LLM call"
        elif not notes_present:
            decision = "⚙️ skip"
            cost = "no LLM call (no ambiguity_notes)"
        elif mode == "live":
            decision = "🤖 call LLM"
            cost = "1 Ollama call"
        else:
            decision = "⚙️ stub"
            cost = "no LLM call (stub mode)"

        plan.append({
            "Variable": entry.name,
            "Rule type": entry.rule_kind,
            "Plan": decision,
            "Cost": cost,
        })
    return plan


def _confidence_band(conf: float) -> tuple[str, str, str]:
    """Return (keyword, color_hex, tooltip) for a proposal confidence.

    The confidence values are **heuristic priors** hardcoded per proposer
    in `agents/spec_generator.py` — they are NOT model-generated
    probabilities. They reflect how strong the pattern signal is and how
    confident the developer is that the body values are right out of the
    box. LLM-augmented proposals are capped so an LLM never out-ranks a
    deterministic shape signature.

    The four bands give the reviewer a one-word read instead of having
    to interpret a number:
      Strong (≥0.90):   clear pattern + body likely right.
      Likely (0.70–0.89): right kind of derivation, body values are guesses.
      Tentative (0.50–0.69): pattern matched but cutoffs are placeholders.
      Weak (<0.50):     low signal, consider skipping.

    Colors follow clinical UX conventions: green = safe, blue = neutral,
    amber = caution, red = warning. The badge is the only visual cue —
    a colored container border would have required CSS injection and
    Streamlit doesn't expose container colors directly.
    """
    if conf >= 0.90:
        return ("Strong", "#16a34a", (
            f"Strong match ({conf:.0%}) — clear pattern signal and the body "
            "values are likely right. Worth a quick sanity-check before "
            "accepting, but the derivation is almost certainly meaningful "
            "for your dataset. (Heuristic prior, not a learned probability.)"
        ))
    if conf >= 0.70:
        return ("Likely", "#2563eb", (
            f"Likely match ({conf:.0%}) — the right kind of derivation, but "
            "the body values (value mappings, edge cuts, etc.) are guesses. "
            "Review the rule body before accepting. LLM-augmented proposals "
            "land in this band by design."
        ))
    if conf >= 0.50:
        return ("Tentative", "#d97706", (
            f"Tentative match ({conf:.0%}) — pattern matched but the "
            "cutoffs / thresholds are placeholders. The agent does not "
            "know your clinical thresholds. Definitely edit the body "
            "before accepting."
        ))
    return ("Weak", "#dc2626", (
        f"Weak match ({conf:.0%}) — low signal. Consider skipping this "
        "proposal unless you can rewrite the body yourself."
    ))


def _confidence_badge_html(conf: float) -> str:
    """Render the confidence keyword as a coloured pill with an <abbr>
    tooltip, followed by the raw percentage. Returns ready-to-use HTML
    (caller passes it to st.markdown with unsafe_allow_html=True).

    The <abbr> tag is the same affordance the glossary uses, so dotted-
    underline + native tooltip is consistent across the app.
    """
    keyword, color, tip = _confidence_band(conf)
    return (
        f'<abbr title="{html.escape(tip)}" '
        f'style="text-decoration:none;cursor:help;">'
        f'<span style="background-color:{color};color:white;'
        f'padding:1px 8px;border-radius:10px;font-size:0.72em;'
        f'font-weight:600;letter-spacing:0.02em;">{keyword}</span>'
        f'&nbsp;<span style="color:#666;font-size:0.82em;">'
        f'({conf:.0%})</span></abbr>'
    )


def _render_auto_suggest_panel() -> Spec | None:
    """Render the agentic IDC-from-dataset workflow inside Step 3.

    Reads the dataset loaded in Step 2, runs the deterministic profiler
    and proposer, shows the profile + proposals as reviewer-friendly
    tables, and lets the user accept a subset. Returns a Spec built from
    the accepted proposals (or None if nothing is selected).

    Design notes:
      - Profile + proposals are computed once per dataset and cached in
        session_state. Without the cache, every checkbox toggle would
        re-run the proposer (cheap but wasteful) and reset the editable
        rationale fields (bad UX).
      - Each proposal's name and rationale are user-editable inline so
        the reviewer can rename AGE_GROUP to ELDERLY_FLAG (or whatever)
        and add their own clinical justification before accepting.
      - The "Use these as the IDC" button is the explicit HITL boundary:
        nothing reaches the pipeline until the human commits.
    """
    df = st.session_state.get("wizard_dataset")
    if df is None:
        st.warning(
            "Go back to Step 2 to load and preview your dataset first. "
            "Auto-suggest needs the dataset to inspect column types."
        )
        return None

    # ----- Cache profile + proposals per dataset --------------------------
    # Use the dataset's column tuple as a cheap fingerprint. If the user
    # goes back to Step 2 and re-parses with different settings, the
    # column set probably changes, invalidating the cache.
    # Fingerprint also includes the LLM mode so flipping live↔stub
    # invalidates the cache (LLM augmentation differs between modes).
    fingerprint = (
        st.session_state.get("wizard_dataset_name"),
        tuple(df.columns),
        len(df),
        current_mode(),
    )
    cache_key = "wizard_autosuggest_cache"
    cached = st.session_state.get(cache_key)

    if cached is None or cached.get("fingerprint") != fingerprint:
        # Stage 1 — deterministic by design. The profile + pattern proposer
        # *never* calls the LLM (it would be the wrong tool — these are
        # regex / shape rules). Pass deterministic=True so the indicator
        # honestly says so regardless of LLM mode, instead of routing
        # through the live/stub branches.
        with llm_indicator.llm_call(
            "Dataset profile + pattern proposer",
            purpose="Read column dtypes, ranges, cardinality and match against "
                    "five clinical idioms (age, flag, duration, compound, risk).",
            deterministic=True,
        ) as ind:
            profile = spec_generator.profile_dataset(df)
            proposals = spec_generator.propose_derivations(df, profile)
            ind.note(
                f"Profiled {len(profile)} columns; proposed "
                f"{len(proposals)} derivation(s) deterministically."
            )

        # Stage 2 — LLM augmentation. Genuine LLM call site (when live).
        # We use getattr() so a stale `spec_generator` module (e.g. a
        # Streamlit session started before this function was added) falls
        # back to "no augmentation" with a clear note, instead of crashing
        # the wizard with AttributeError. Restart still recommended, but
        # the page stays usable in the meantime.
        with llm_indicator.llm_call(
            "LLM augmentation — find derivations the patterns missed",
            purpose="Send the column profile + existing proposals to the LLM; "
                    "ask for additional clinically useful derivations.",
            expanded=True,
            position=(1, 1),  # one-shot augmentation; position helps tag the call site
        ) as ind:
            augment_fn = getattr(
                spec_generator, "augment_proposals_with_llm", None,
            )
            if augment_fn is None:
                ind.note(
                    "⚠️ `spec_generator.augment_proposals_with_llm` is not "
                    "available on the loaded module. This usually means "
                    "Streamlit was started before the function was added — "
                    "stop the server (Ctrl+C) and run `python -m clinitrace "
                    "ui` again to pick up the change. Skipping augmentation "
                    "for this run."
                )
                augmented: list[dict] = []
            else:
                augmented = augment_fn(df, profile, proposals)
            if augmented:
                ind.note(
                    f"LLM proposed **{len(augmented)}** additional "
                    f"derivation(s): " +
                    ", ".join(f"`{p['name']}`" for p in augmented)
                )
                proposals = proposals + augmented
            elif augment_fn is not None and current_mode() == "live":
                ind.note(
                    "LLM returned no additional proposals — the "
                    "deterministic patterns already covered the dataset's "
                    "common idioms."
                )

        st.session_state[cache_key] = {
            "fingerprint": fingerprint,
            "profile": profile,
            "proposals": proposals,
        }
        cached = st.session_state[cache_key]

    profile = cached["profile"]
    proposals: list[dict] = cached["proposals"]

    # ----- Profile panel --------------------------------------------------
    with st.expander(
        f"📊 Dataset profile — {len(profile)} columns",
        expanded=False,
    ):
        rows = []
        kind_label = {
            "date": "📅 date",
            "numeric": "🔢 numeric",
            "low_cardinality": "🏷 categorical (low cardinality)",
            "high_cardinality": "📝 free text / high cardinality",
            "unknown": "❓ unknown",
        }
        for col, p in profile.items():
            extra = ""
            if p["kind"] == "numeric":
                extra = f"range {p.get('min', '?')}–{p.get('max', '?')}"
            elif p["kind"] == "low_cardinality":
                extra = f"values: {', '.join(p.get('values', [])[:5])}"
            elif p["kind"] == "date":
                extra = f"sample: {p['sample_values'][0] if p['sample_values'] else '—'}"
            rows.append({
                "Column": col,
                "Detected as": kind_label.get(p["kind"], p["kind"]),
                "Nulls %": f"{p['null_fraction']*100:.0f}%",
                "Unique": p["n_unique"],
                "Notes": extra,
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if not proposals:
        st.warning(
            "No derivations could be suggested for this dataset. "
            "Try the 'Upload my own' or 'Use bundled demo' options."
        )
        return None

    # ----- Proposals panel ------------------------------------------------
    st.markdown(
        f"**{len(proposals)} suggested derivation(s).** Review each, edit "
        "name / rationale as needed, then accept the ones you want."
    )
    if current_mode() == "stub":
        st.caption(
            "💡 Tip: enable the LLM in Settings to get richer "
            "auto-generated rationales and catch derivations the "
            "deterministic patterns miss."
        )

    accepted: list[dict] = []
    for i, prop in enumerate(proposals):
        # Per-proposal accept checkbox + editable name + editable rationale.
        accept_key = f"wizard_propose_accept_{i}"
        name_key = f"wizard_propose_name_{i}"
        rationale_key = f"wizard_propose_rationale_{i}"
        st.session_state.setdefault(accept_key, True)
        st.session_state.setdefault(name_key, prop["name"])
        st.session_state.setdefault(rationale_key, prop["rationale"])

        with st.container(border=True):
            # Wider first column (was 0.5) so the checkbox sits comfortably
            # on one line. Streamlit was wrapping the "Use" label
            # character-per-character into a vertical strip at 0.5.
            cols = st.columns([0.8, 2, 4, 3], vertical_alignment="center")
            with cols[0]:
                st.checkbox(
                    "Use",
                    key=accept_key,
                    label_visibility="collapsed",
                    help="Include this derivation in the generated IDC.",
                )
            with cols[1]:
                # Four-line label: explicit "rule type" caption above the
                # value (otherwise reviewers don't always realise that "bin"
                # is the *kind* of transformation), then the rule_kind
                # itself with a glossary tooltip (dotted underline + hover
                # definition), then the confidence badge, then inputs.
                #
                # We use glossary.term() so the affordance matches the rest
                # of the app — same dotted-underline pattern shown for IDC,
                # HITL, SR, etc. The GLOSSARY dict already has plain-English
                # definitions for all five registered rule_kinds.
                rule_kind = prop["rule_kind"]
                st.markdown(
                    "<span style='font-size:0.72em;color:#888;"
                    "text-transform:uppercase;letter-spacing:0.05em;'>"
                    "Rule type</span><br>"
                    f"<span style='font-size:1.05em;font-weight:600;'>"
                    f"{glossary.term(rule_kind)}</span><br>"
                    + _confidence_badge_html(prop["_confidence"]),
                    unsafe_allow_html=True,
                )
                st.caption(f"inputs: `{', '.join(prop['inputs'])}`")
            with cols[2]:
                st.text_input(
                    "Output column name",
                    key=name_key,
                    label_visibility="collapsed",
                )
                st.text_area(
                    "Rationale",
                    key=rationale_key,
                    height=68,
                    label_visibility="collapsed",
                )
            with cols[3]:
                st.caption(f"_Why suggested:_ {prop['_reason']}")
                with st.expander("Rule body (JSON)", expanded=False):
                    st.json(prop["rule_body"])

        if st.session_state[accept_key]:
            patched = dict(prop)
            patched["name"] = st.session_state[name_key].strip() or prop["name"]
            patched["rationale"] = st.session_state[rationale_key]
            accepted.append(patched)

    # Cross-list footer hint pointing at the IDC Rulebook. The Rulebook
    # page renders an interactive Try-it sandbox for each rule_kind, plus
    # any validated bodies the system has learned (LTM rule_patterns).
    # That's the best place for a reviewer to develop intuition for what
    # `bin` vs `flag` vs `duration` etc. actually do.
    st.caption(
        "💡 Hover any **rule type** above for a quick definition. "
        "For full documentation — including interactive Try-it sandboxes "
        "and validated bodies from past tasks — visit the "
        "**IDC Rulebook** page in the main menu."
    )

    if not accepted:
        st.info("Tick at least one **Use** checkbox to build the IDC.")
        return None

    # ----- Build & validate Spec -----------------------------------------
    spec_dict = spec_generator.proposals_to_spec_dict(accepted)
    try:
        spec = Spec.model_validate(spec_dict)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"The accepted proposals don't form a valid IDC: {exc}. "
            "Adjust your edits and try again."
        )
        return None

    # ----- Download / inspect (so the user can save the generated YAML) --
    yaml_text = yaml.safe_dump(spec_dict, sort_keys=False, allow_unicode=True)
    nav_a, nav_b = st.columns([1, 6])
    with nav_a:
        st.download_button(
            "⬇ Download as YAML",
            data=yaml_text.encode("utf-8"),
            file_name="generated_idc.yaml",
            mime="text/yaml",
            help="Save the generated IDC so you can hand-edit it later.",
        )
    with nav_b:
        with st.expander("Show generated IDC YAML", expanded=False):
            st.code(yaml_text, language="yaml")

    st.session_state["wizard_spec_bytes"] = yaml_text.encode("utf-8")
    st.session_state["wizard_spec_name"] = "generated_idc.yaml"
    return spec


def _bundled_example_spec_path() -> Path | None:
    """Look for examples/demo_spec.yaml in a few likely spots."""
    candidates = [
        Path.cwd() / "examples" / "demo_spec.yaml",
        Path.cwd() / "repo" / "examples" / "demo_spec.yaml",
        Path(__file__).resolve().parents[3] / "examples" / "demo_spec.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _render_step_spec() -> None:
    st.subheader("Step 3 — Choose Importing Data Contract (IDC)")
    st.markdown(
        "The "
        + glossary.term("IDC")
        + " tells CliniTrace which "
        + glossary.term("derivation", glossary.define("derivation"))
        + "s to compute and how. Upload your own "
        + glossary.term("YAML")
        + " or pick the bundled demo.",
        unsafe_allow_html=True,
    )

    source = st.radio(
        "IDC source",
        options=[
            "Auto-suggest from dataset (agentic)",
            "Upload my own",
            "Use bundled demo",
        ],
        horizontal=True,
        key="wizard_spec_source_radio",
        help=(
            "Auto-suggest reads your dataset and proposes derivations using "
            "deterministic pattern matching (plus LLM augmentation if "
            "enabled). You review each suggestion before it becomes the IDC."
        ),
    )

    spec: Spec | None = None
    if source == "Auto-suggest from dataset (agentic)":
        spec = _render_auto_suggest_panel()
    elif source == "Upload my own":
        uploaded = st.file_uploader(
            "Drop an IDC file (YAML)",
            type=["yaml", "yml"],
            accept_multiple_files=False,
            key="wizard_spec_uploader",
            help="The IDC declares which new columns to derive and how.",
        )
        if uploaded is not None:
            raw = uploaded.read()
            st.session_state["wizard_spec_bytes"] = raw
            st.session_state["wizard_spec_name"] = uploaded.name
            # The model_validate() path runs the spec_triage agent on any
            # unknown rule_kind (see spec/model.py — model_validator
            # "triage_rule_kind" with mode='before'). Triage uses three
            # signals — text similarity, body shape, and (in live mode)
            # an LLM semantic match. We wrap parse + validate in the
            # indicator so the user can see when triage fires.
            with llm_indicator.llm_call(
                "Parse + validate YAML IDC",
                purpose="Pydantic schema check. If a rule_kind is unknown, "
                        "the spec_triage agent runs (text + shape + optional LLM).",
                deterministic=True,
            ) as ind:
                try:
                    data = yaml.safe_load(raw.decode("utf-8"))
                    spec = Spec.model_validate(data)
                    ind.note(
                        f"YAML parsed and validated — "
                        f"{len(data.get('derivations', []))} derivation(s)."
                    )
                except Exception as exc:  # noqa: BLE001
                    # Triage's error message lands here when a rule_kind is
                    # unknown; the indicator's error label keeps the rich
                    # text intact for the user to read.
                    st.error(f"Could not load IDC: {exc}")
    else:
        demo_path = _bundled_example_spec_path()
        if demo_path is None:
            st.error(
                "Bundled demo IDC not found. Upload your own to continue."
            )
        else:
            st.info(f"Using `{demo_path}`")
            try:
                spec = load_spec(demo_path)
                st.session_state["wizard_spec_name"] = demo_path.name
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not load demo IDC: {exc}")

    if spec is not None:
        st.session_state["wizard_spec_obj"] = spec
        st.success(f"Loaded IDC with {len(spec.derivations)} derivation(s).")
        rows = []
        for d in spec.derivations:
            rows.append({
                "Variable": d.name,
                "Rule kind": d.rule_kind,
                "Inputs": ", ".join(d.inputs),
                "Has ambiguity note": "yes" if d.ambiguity_notes else "no",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch")

        # Check IDC columns vs dataset columns
        df = st.session_state.get("wizard_dataset")
        if df is not None:
            spec_inputs = {col for d in spec.derivations for col in d.inputs}
            derived = {d.name for d in spec.derivations}
            source_needed = spec_inputs - derived
            missing = source_needed - set(df.columns)
            if missing:
                st.warning(
                    f"⚠️ IDC expects these source columns not in your "
                    f"dataset: {sorted(missing)}. The task will fail at "
                    f"dataset validation."
                )
            else:
                st.success("✅ All required source columns present in dataset.")

    nav_a, nav_b, nav_c = st.columns([1, 1, 6])
    with nav_a:
        if st.button("← Back", key="spec_back"):
            _set_step(2)
            st.rerun()
    with nav_b:
        if st.button(
            "Next: run →",
            type="primary",
            disabled=spec is None,
            key="spec_next",
        ):
            _set_step(4)
            st.rerun()


# ---------------------------------------------------------------------------
# Step 4: Run pipeline
# ---------------------------------------------------------------------------


def _render_step_run() -> None:
    st.subheader("Step 4 — Run the task")
    name = st.session_state.get("wizard_task_name")
    if name:
        st.caption(f"Task name: **{name}**")
    st.caption(
        "Click 'Start' to execute the agentic pipeline. Progress streams "
        "below; clarifications (if any) will appear in the 'IDC "
        "clarifications' page while the task is waiting."
    )

    df = st.session_state.get("wizard_dataset")
    spec = st.session_state.get("wizard_spec_obj")
    if df is None or spec is None:
        st.warning("Complete the earlier steps first.")
        return

    with st.expander("Run settings", expanded=False):
        st.text_input(
            "Output folder (run artifacts go in subfolders here)",
            value=st.session_state["wizard_out_dir"],
            key="wizard_out_dir",
        )
        st.text_input(
            "Long-term memory file",
            value=st.session_state["wizard_ltm_path"],
            key="wizard_ltm_path",
        )
        st.caption(
            "Paths resolve relative to the working directory where Streamlit "
            "was launched."
        )

    # Two-rerun pattern so the Start button visibly disables during the run.
    # Streamlit naturally blocks new clicks while orch.run() is executing,
    # but the BUTTON ITSELF still RENDERS as enabled because its disabled
    # state is decided at render time. By gating on a session_state flag
    # and rerunning between click and execute, we get a clean
    # "▶ Start task" → "⏳ Running task…" visual transition.
    in_progress = st.session_state.get("wizard_run_in_progress", False)
    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("← Back", key="run_back", disabled=in_progress):
            _set_step(3)
            st.rerun()
    with cols[1]:
        if in_progress:
            # Render the in-progress placeholder. Disabled + no on-click so
            # a stray double-click while the rerun is in flight is harmless.
            st.button(
                "⏳ Running task…",
                disabled=True,
                key="run_start_inprogress",
                type="primary",
            )
            start = False
        else:
            start = st.button(
                "▶ Start task",
                type="primary",
                key="run_start",
            )

    if start and not in_progress:
        # Click landed on a fresh page render — flip the flag and rerun so
        # the next render shows the disabled "Running…" button BEFORE we
        # start the long orch.run() call.
        st.session_state["wizard_run_in_progress"] = True
        st.rerun()

    if not in_progress:
        return  # waiting for the user to click; nothing to execute

    out_dir = Path(st.session_state["wizard_out_dir"])
    ltm_path = Path(st.session_state["wizard_ltm_path"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # Make the run-status label honest about LLM mode so the user can see at
    # a glance whether this run was agentic (live) or stubbed. The pipeline
    # itself runs multiple LLM call sites (SR per entry, CG per derivation)
    # interspersed with deterministic V/R/A — exact per-call indicators
    # would need orchestrator-side hooks; mode-tagging the outer status box
    # is the right granularity for this surface.
    mode = current_mode()
    mode_label = (
        "🤖 Running agentic pipeline (LLM enabled — SR + CG call Ollama)"
        if mode == "live"
        else "⚙️ Running deterministic pipeline (LLM disabled in Settings)"
    )
    # Open the LTM before computing the plan so we can probe for cached
    # resolutions per entry. The same handle is passed into orch.run() so
    # we only pay the SQLite open cost once.
    ltm = LTM(ltm_path)

    # ----- Stage 1 plan (pre-flight) -------------------------------------
    # Rendered OUTSIDE the status box so it stays visible during the
    # blocking orch.run() call below — st.status's content updates aren't
    # flushed to the browser until the script yields, but content added
    # before the blocking call IS visible while the spinner runs.
    plan = _stage1_plan(spec, ltm, mode)
    llm_calls_expected = sum(1 for p in plan if "call LLM" in str(p["Plan"]))
    cache_hits = sum(1 for p in plan if "LTM cache" in str(p["Plan"]))
    skips = sum(1 for p in plan if "skip" in str(p["Plan"]))
    st.markdown(
        f"**Stage 1 plan — Spec Review over {len(plan)} entries:** "
        f"📁 {cache_hits} LTM cache hit(s), ⚙️ {skips} skipped, "
        f"🤖 **{llm_calls_expected} LLM call(s) expected**."
    )
    st.dataframe(pd.DataFrame(plan), width="stretch", hide_index=True)
    st.caption(
        "Streamlit can't repaint the page during a blocking pipeline call, "
        "so per-entry progress can't be streamed live. The plan above shows "
        "exactly what Stage 1 will do; counts below appear once the run "
        "completes."
    )

    status = st.status(mode_label, expanded=True)
    try:
        status.write("**Stage 0** — Validating source columns against the dataset…")
        status.write(
            f"**Stage 1** — Running 🤖 Spec Reviewer over "
            f"{len(spec.derivations)} derivation(s); "
            f"expecting **{llm_calls_expected} LLM call(s)** "
            f"({cache_hits} cached, {skips} short-circuited)…"
        )
        result = orch.run(
            spec=spec,
            dataset=df,
            out_dir=out_dir,
            ltm=ltm,
            llm_mode=mode,
            inbox_poll_interval=1.0,
            inbox_poll_timeout=300.0,
        )
        status.write("**Stage 2-5** — DAG planning + 🤖 CG normalisation + ⚙️ V verification + ⚙️ A audit.")
        # Persist the user-supplied task name (if any) inside the run dir so
        # it appears in selectors and summaries forever after.
        task_name = st.session_state.get("wizard_task_name")
        if task_name:
            task_meta.save(result.run_dir, {"task_name": task_name})
        st.session_state["wizard_run_result"] = result
        st.session_state["wizard_run_error"] = None
        # Surface the LLM activity counts so the user can SEE whether the
        # agentic loop actually fired (or whether everything cache-hit).
        counts = result.counts
        status.write(
            f"**Counts** — SR findings: {counts.get('sr_findings', 0)}, "
            f"auto-resolved from LTM: {counts.get('sr_auto_resolved', 0)}, "
            f"HITL tickets opened: {counts.get('hitl_tickets_opened', 0)}, "
            f"CG LTM hits: {counts.get('cg_ltm_hits', 0)}, "
            f"derivations verified: {counts.get('derivations_verified', 0)}."
        )
        status.update(
            label=(
                f"✅ {'🤖 Agentic' if mode == 'live' else '⚙️ Stub'} "
                f"task complete — {counts.get('derivations_verified', 0)} "
                f"derivation(s) verified"
            ),
            state="complete",
        )
        # Clear the in-progress flag BEFORE advancing the step so the
        # Start button reseeds on its next render.
        st.session_state["wizard_run_in_progress"] = False
        _set_step(5)
        st.rerun()
    except orch.DatasetValidationError as exc:
        st.session_state["wizard_run_error"] = f"Dataset validation failed: {exc}"
        status.update(label="❌ Dataset validation failed", state="error")
    except Exception as exc:  # noqa: BLE001
        st.session_state["wizard_run_error"] = (
            f"{exc}\n\n{traceback.format_exc()}"
        )
        status.update(label="❌ Run failed", state="error")
    finally:
        # ALWAYS clear the in-progress flag on any exit path — otherwise a
        # failed run would leave the user stuck on a permanently "Running…"
        # button until they refresh the page.
        st.session_state["wizard_run_in_progress"] = False
        ltm.close()

    if st.session_state.get("wizard_run_error"):
        st.error(st.session_state["wizard_run_error"])


# ---------------------------------------------------------------------------
# Step 5: Results
# ---------------------------------------------------------------------------


def _render_step_results() -> None:
    st.subheader("Step 5 — Results")
    result = st.session_state.get("wizard_run_result")
    if result is None:
        st.info("No result yet. Go back and start the task.")
        if st.button("← Back to run"):
            _set_step(4)
            st.rerun()
        return

    name = st.session_state.get("wizard_task_name")
    label = task_meta.format_run_label(result.run_dir)
    if name:
        st.success(f"Task **{name}** complete.")
        st.caption(label)
    else:
        st.success(f"Task complete: {label}")

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "Derivations verified",
        result.counts.get("derivations_verified", 0),
        help=glossary.help_text("derivation"),
    )
    metric_cols[1].metric(
        "Unresolved",
        result.counts.get("derivations_unresolved", 0),
        help="Derivations that could not be verified end-to-end.",
    )
    metric_cols[2].metric(
        "HITL tickets opened",
        result.counts.get("hitl_tickets_opened", 0),
        help=glossary.help_text("HITL"),
    )
    metric_cols[3].metric(
        "LTM hits (CG)",
        result.counts.get("cg_ltm_hits", 0),
        help=(
            "Code Generation reused a validated rule from Long-Term Memory "
            "instead of calling the LLM."
        ),
    )

    out_path = result.output_dataset_path
    st.markdown(f"**Output dataset:** `{out_path.name}`")
    try:
        if out_path.suffix == ".parquet":
            out_df = pd.read_parquet(out_path)
        else:
            out_df = pd.read_csv(out_path)
        st.dataframe(out_df, width="stretch", height=300)
        st.download_button(
            "⬇ Download analysis-ready dataset",
            data=out_path.read_bytes(),
            file_name=out_path.name,
            mime="text/csv" if out_path.suffix == ".csv" else "application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not preview output dataset: {exc}")

    summary_path = result.run_summary_path
    if summary_path.exists():
        with st.expander("Run summary", expanded=False):
            raw = summary_path.read_text(encoding="utf-8")
            st.markdown(_humanize_iso_in_text(raw))

    trail_path = result.run_dir / "audit_trail.jsonl"
    if trail_path.exists():
        with st.expander("Audit trail (raw)", expanded=False):
            events = [
                json.loads(line)
                for line in trail_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            st.dataframe(pd.DataFrame(events), width="stretch", height=300)

    nav_a, nav_b, _ = st.columns([1, 1, 6])
    with nav_a:
        if st.button("← Back"):
            _set_step(4)
            st.rerun()
    with nav_b:
        if st.button("Start another task"):
            _reset_wizard()
            st.rerun()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render() -> None:
    _init_state()
    current = st.session_state["wizard_step"]
    _render_stepper(current)
    if current == 1:
        _render_step_upload()
    elif current == 2:
        _render_step_preview()
    elif current == 3:
        _render_step_spec()
    elif current == 4:
        _render_step_run()
    elif current == 5:
        _render_step_results()
    else:
        st.error(f"Unknown wizard step: {current}")
