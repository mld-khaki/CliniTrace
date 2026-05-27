"""CliniTrace Streamlit GUI.

Top-level horizontal menu (Round 4) with five pages:

  1. Review questions  -- lists open reviewer tickets in <run_dir>/hitl/inbox,
     renders one at a time with options + free-text, writes the decision to
     the outbox so the Orchestrator's polling loop picks it up.
  2. Run review        -- pick a past run; view the run summary, checks
     performed, activity log, output dataset, and per-row lineage.
  3. Across-run memory -- browse what CliniTrace remembers from past runs:
     rules previously seen, prior reviewer decisions, activity log.
  4. Documentation     -- sub-menu: Glossary / Tutorial.
  5. Settings          -- duplicate path inputs that mirror the sidebar.

All reviewer-facing strings flow through clinitrace.presentation so the UI,
the run_summary, and the audit trail use the same vocabulary.

The HITL ticket-resolution surface (locked in proposal section 5.3) is
unchanged; only the navigation chrome around it changes in this revision.

Run with:
    streamlit run clinitrace/ui/streamlit_app.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

from clinitrace.hitl import Resolution, Ticket
from clinitrace.ui import glossary, new_run_wizard, rule_preview, settings_store, task_meta
from clinitrace.presentation import (
    APP_TAGLINE,
    GLOSSARY_HTML,
    TAB_DESCRIPTIONS,
    TUTORIAL_HTML,
    humanize_ambiguity_class,
    humanize_column,
    humanize_columns,
    humanize_event,
    humanize_event_id,
    humanize_layer,
    humanize_option,
    humanize_property,
    humanize_rule_kind,
    humanize_run_id,
    humanize_status,
    humanize_ticket_kind,
    humanize_timestamp,
    short_fingerprint,
    summarize_options,
    summarize_resolution,
    ticket_lead_in,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


import re as _re

# Matches ISO-8601 timestamps with timezone offset (Z or +/-HH:MM, optional
# microseconds). Anchored to digits on both sides so it never eats partial
# matches inside other identifiers.
_ISO_TS_RE = _re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})"
)


def _humanize_iso_timestamps_in_text(text: str) -> str:
    """Find any ISO 8601 UTC timestamps in a free-text blob (e.g. the run
    summary markdown) and rewrite them in the user's configured display
    timezone. Run summaries are written once at run time with UTC strings
    baked in; this lets the reviewer's local timezone show up in the UI
    without rewriting the on-disk artifact.
    """
    return _ISO_TS_RE.sub(lambda m: humanize_timestamp(m.group(0)), text)


def _humanize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to reviewer-friendly headers without mutating the input.

    Per-value humanization is applied before the column rename so the
    friendlier column name lines up with a friendlier cell value. Every
    transform is NaN-safe (the helpers in clinitrace.presentation pass through
    non-string inputs unchanged), so heterogeneous audit-trail / LTM
    dataframes do not crash.

    The body column on rule_patterns is intentionally NOT summarized here;
    the LTM tab provides a row-selector below the table that renders the
    full body JSON via st.json. Same pattern applies to context fields on
    feedback_events that would not summarize cleanly.
    """
    out = df.copy()
    transforms = {
        "rule_kind":         humanize_rule_kind,
        "ticket_kind":       humanize_ticket_kind,
        "event_type":        humanize_event,
        "ambiguity_class":   humanize_ambiguity_class,
        "status":            humanize_status,
        "outcome":           humanize_status,
        "run_id":            humanize_run_id,
        "first_seen_run_id": humanize_run_id,
        "resolved_run_id":   humanize_run_id,
        "event_id":             humanize_event_id,
        "hitl_event_id":        humanize_event_id,
        "approval_event_id":    humanize_event_id,
        "resolution_event_id":  humanize_event_id,
        "ts":             humanize_timestamp,
        "first_seen_at":  humanize_timestamp,
        "resolved_at":    humanize_timestamp,
        "opened_at":      humanize_timestamp,
        "created_at":     humanize_timestamp,
        "updated_at":     humanize_timestamp,
        "started_at":     humanize_timestamp,
        "completed_at":   humanize_timestamp,
        "resolution":       summarize_resolution,
        "options_offered":  summarize_options,
        "body_signature":       short_fingerprint,
        "signature":            short_fingerprint,
        "ambiguity_signature":  short_fingerprint,
    }
    for col, fn in transforms.items():
        if col in out.columns:
            out[col] = out[col].map(fn)
    return out.rename(columns=humanize_columns(out.columns))


# ---------------------------------------------------------------------------
# Path inputs -- shared between sidebar and Settings page via session_state.
# ---------------------------------------------------------------------------


_DEFAULT_OUT_DIR = "demo_out"
_DEFAULT_LTM_PATH = "demo_ltm.db"


def _current_paths() -> tuple[Path, Path]:
    """Resolve current Runs folder and Memory file from session_state."""
    out_dir = Path(st.session_state.get("out_dir", _DEFAULT_OUT_DIR))
    ltm_path = Path(st.session_state.get("ltm_path", _DEFAULT_LTM_PATH))
    return out_dir, ltm_path


# ---------------------------------------------------------------------------
# Page 1: Review questions
# ---------------------------------------------------------------------------


def _scan_runs(out_dir: Path) -> list[Path]:
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("run-*"), reverse=True)


def _open_tickets(run_dir: Path) -> list[Path]:
    inbox = run_dir / "hitl" / "inbox"
    outbox = run_dir / "hitl" / "outbox"
    if not inbox.exists():
        return []
    tickets = sorted(inbox.glob("*.ticket.json"))
    open_only: list[Path] = []
    for tk in tickets:
        event_id = tk.name.removesuffix(".ticket.json")
        if not (outbox / f"{event_id}.resolution.json").exists():
            open_only.append(tk)
    return open_only


def _ticket_label(ticket_path: Path) -> str:
    """Render a ticket file as 'Variable - Question type' for the selectbox."""
    try:
        raw = json.loads(ticket_path.read_text(encoding="utf-8"))
        kind = humanize_ticket_kind(raw.get("ticket_kind", ""))
        target = raw.get("target") or "unspecified variable"
        return f"{target} -- {kind}"
    except Exception:
        return ticket_path.name.removesuffix(".ticket.json")


def _render_hitl_page(out_dir: Path) -> None:
    st.subheader("IDC Clarifications")
    st.markdown(
        "Clarifications the pipeline asked about your "
        + glossary.term("IDC")
        + ". They are raised by the "
        + glossary.term("SR")
        + " agent when a rule is ambiguous (for example, the rationale "
        "mentions a value the rule body doesn't handle). Resolved here, "
        "applied to the next stage. &nbsp;("
        + glossary.term("HITL")
        + ")",
        unsafe_allow_html=True,
    )
    runs = _scan_runs(out_dir)
    if not runs:
        st.info(
            f"No tasks found in `{out_dir}`. Start a new task first, then "
            f"come back to review any clarifications it raises."
        )
        return

    # Pre-scan: count open clarifications per task so we can show a summary
    # and offer to hide clean tasks.
    open_counts: dict[Path, int] = {r: len(_open_tickets(r)) for r in runs}
    needs_review = [r for r in runs if open_counts[r] > 0]
    clean = [r for r in runs if open_counts[r] == 0]

    summary_cols = st.columns([1, 1, 3])
    summary_cols[0].metric(
        "Tasks needing review",
        len(needs_review),
        help="Tasks with at least one open clarification.",
    )
    summary_cols[1].metric(
        "Clean tasks",
        len(clean),
        help="Tasks with no open clarifications.",
    )
    with summary_cols[2]:
        only_open = st.toggle(
            "Show only tasks with open clarifications",
            value=True,
            key="hitl_filter_only_open",
            help=(
                "Hide tasks that have no pending clarifications. Turn off "
                "to also see clean tasks (useful for audit trails)."
            ),
        )

    visible_runs = needs_review if only_open else runs
    if not visible_runs:
        st.success("🎉 No tasks need clarification right now.")
        st.caption(
            "All tasks are clean. Toggle the filter off to see them anyway."
        )
        return

    selected_run = st.selectbox(
        "Which task",
        visible_runs,
        format_func=lambda p: (
            f"({open_counts[p]} open) " if open_counts[p] else "(clean) "
        ) + task_meta.format_run_label(p),
        key="hitl_run",
        help="Most recent task is selected by default.",
    )
    open_tk = _open_tickets(selected_run)
    if not open_tk:
        st.success(
            f"No open clarifications in "
            f"{task_meta.format_run_label(selected_run)}."
        )
        st.caption(
            "Resolved clarifications are kept alongside their decision file; "
            "this view only shows what still needs your input."
        )
        return

    st.write(
        f"**{len(open_tk)}** clarification(s) waiting for your decision."
    )
    chosen = st.selectbox(
        "Which clarification",
        open_tk,
        format_func=_ticket_label,
        key="hitl_ticket",
        help=(
            "Pick one to see its full prompt and the resolution options."
        ),
    )
    ticket_raw = json.loads(chosen.read_text(encoding="utf-8"))
    ticket = Ticket.model_validate(ticket_raw)
    kind = ticket.ticket_kind.value

    st.markdown(f"### {humanize_ticket_kind(kind)}")
    st.caption(ticket_lead_in(kind))
    st.markdown(f"**About variable:** `{ticket.target}`")
    st.info(ticket.prompt_shown_to_human)

    if ticket.context:
        ctx_pretty = dict(ticket.context)
        if "ambiguity_class" in ctx_pretty:
            ctx_pretty["What kind of clarification this is"] = (
                humanize_ambiguity_class(ctx_pretty.pop("ambiguity_class"))
            )
        for hash_key in ("ambiguity_signature", "body_signature", "signature"):
            if hash_key in ctx_pretty:
                ctx_pretty[humanize_column(hash_key)] = short_fingerprint(
                    ctx_pretty.pop(hash_key)
                )
        with st.expander("Why this clarification was raised"):
            for k, v in ctx_pretty.items():
                st.markdown(f"- **{k}:** {v}")
        with st.expander("Technical details (raw context JSON)"):
            st.json(ticket.context)

    raw_options = list(ticket.options_offered) + ["__other__"]

    def _option_format(raw: str) -> str:
        if raw == "__other__":
            return "Other (write your own decision below)"
        return humanize_option(raw)

    chosen_raw_option = st.radio(
        "Your decision",
        raw_options,
        format_func=_option_format,
        key=f"opt_{ticket.event_id}",
        help=(
            "Pick the option that best matches what should happen. If none "
            "fit, pick 'Other' and explain in the reasoning box."
        ),
    )
    chosen_option = (
        chosen_raw_option if chosen_raw_option != "__other__" else "Other (free text)"
    )

    free_text = st.text_area(
        "Your reasoning (optional, but recommended)",
        key=f"reason_{ticket.event_id}",
        help=(
            "Captured in the audit trail. Useful for future reviewers (and "
            "for the system's memory) to know why you chose what you chose."
        ),
    )

    with st.expander("Advanced (edit the rule body as JSON)"):
        body_patch_raw = st.text_area(
            "Rule body adjustment (JSON)",
            value="{}",
            help=(
                "Optional adjustment merged into the rule body. "
                "Leave empty for most cases. "
                "Example for the demo: "
                "{\"unmapped_handling\": \"value\", \"unmapped_value\": \"U\"}"
            ),
            key=f"patch_{ticket.event_id}",
        )

    if st.button("Save your decision", key=f"submit_{ticket.event_id}"):
        try:
            body_patch = json.loads(body_patch_raw) if body_patch_raw.strip() else {}
        except json.JSONDecodeError as exc:
            st.error(f"The advanced JSON adjustment is not valid JSON: {exc}")
            return
        if not isinstance(body_patch, dict):
            st.error("The advanced JSON adjustment must be a JSON object.")
            return
        resolution = Resolution(
            event_id=ticket.event_id,
            ticket_kind=ticket.ticket_kind,
            target=ticket.target,
            chosen_option=chosen_option,
            body_patch=body_patch,
            free_text_rationale=free_text,
            resolved_by="streamlit-ui",
        )
        outbox = selected_run / "hitl" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        out_path = outbox / f"{ticket.event_id}.resolution.json"
        out_path.write_text(resolution.model_dump_json(indent=2), encoding="utf-8")
        st.success("Saved your decision. The system will pick it up shortly.")
        st.caption(f"Stored at: {out_path}")


# ---------------------------------------------------------------------------
# Page 2: Run review
# ---------------------------------------------------------------------------


def _render_run_inspector(out_dir: Path) -> None:
    st.subheader("Import Task History")
    st.caption(TAB_DESCRIPTIONS["run_review"])
    runs = _scan_runs(out_dir)
    if not runs:
        st.info(f"No runs found in `{out_dir}`.")
        return
    selected_run = st.selectbox(
        "Which task",
        runs,
        format_func=task_meta.format_run_label,
        key="inspect_run",
        help="Most recent task is selected by default.",
    )

    summary = selected_run / "run_summary.md"
    report = selected_run / "verification_report.json"
    trail = selected_run / "audit_trail.jsonl"
    dataset_parquet = selected_run / "analysis_ready.parquet"
    dataset_csv = selected_run / "analysis_ready.csv"

    sub_tabs = st.tabs(
        ["Summary", "Checks performed", "Activity log", "Output data"]
    )

    with sub_tabs[0]:
        if summary.exists():
            raw = summary.read_text(encoding="utf-8")
            st.markdown(_humanize_iso_timestamps_in_text(raw))
        else:
            st.warning("This run has no summary file yet.")

    with sub_tabs[1]:
        st.caption(
            "Each derived variable, the rule type, whether the system "
            "recognised the rule from memory, and any issues raised."
        )
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            rows: list[dict[str, Any]] = []
            for name, rec in data.get("derivations", {}).items():
                rows.append(
                    {
                        "Variable": name,
                        "Status": humanize_status(rec.get("status", "")),
                        "Rule type": humanize_rule_kind(rec.get("rule_kind", "")),
                        "Revisions": rec.get("iterations"),
                        "Recognised from memory": bool(rec.get("ltm_hit")),
                        "Agent steps": glossary.agent_chain_label(
                            rec.get("agent_chain", []) or []
                        ),
                        "Issues raised": len(rec.get("findings", []) or []),
                        "Reason (if unresolved)": rec.get("reason"),
                    }
                )
            if rows:
                st.dataframe(pd.DataFrame(rows), width="stretch")
            for name, rec in data.get("derivations", {}).items():
                findings = rec.get("findings", []) or []
                if not findings:
                    continue
                with st.expander(f"Issues for {name} ({len(findings)})"):
                    for f in findings:
                        layer = humanize_layer(f.get("layer", ""))
                        prop = f.get("property_id")
                        prop_label = (
                            f" -- {humanize_property(prop)}" if prop else ""
                        )
                        st.markdown(
                            f"- **{layer}**{prop_label}: {f.get('message', '')}"
                        )
            with st.expander("Technical details (raw report JSON)"):
                st.json(data)
        else:
            st.warning("No verification report for this run.")

    with sub_tabs[2]:
        st.caption(
            "Every step the system took, in order. Filter by activity type "
            "to focus on a phase (e.g. only reviewer questions, only memory "
            "writes)."
        )
        if trail.exists():
            events = [
                json.loads(line)
                for line in trail.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if events:
                kinds = sorted({e["event_type"] for e in events})
                kind_to_label = {k: humanize_event(k) for k in kinds}
                wanted_labels = st.multiselect(
                    "Show activity of type:",
                    list(kind_to_label.values()),
                    default=list(kind_to_label.values()),
                )
                wanted_kinds = {
                    k for k, label in kind_to_label.items()
                    if label in wanted_labels
                }
                filtered = [e for e in events if e["event_type"] in wanted_kinds]
                st.write(
                    f"Showing {len(filtered)} of {len(events)} activity entries."
                )
                if filtered:
                    df_events = pd.DataFrame(filtered)
                    df_events_h = _humanize_df(df_events)
                    cols = list(df_events_h.columns)
                    if "Activity" in cols:
                        cols.insert(0, cols.pop(cols.index("Activity")))
                        df_events_h = df_events_h[cols]
                    st.dataframe(df_events_h, width="stretch", height=400)
                with st.expander("Technical details (raw first event)"):
                    if filtered:
                        st.json(filtered[0])
            else:
                st.info("No activity recorded for this run.")
        else:
            st.warning("No activity log for this run.")

    with sub_tabs[3]:
        st.caption(
            "The analysis-ready dataset produced by this run. Pick a row to "
            "see the lineage trail back to source rows and rules."
        )
        dataset_path: Path | None = None
        if dataset_parquet.exists():
            dataset_path = dataset_parquet
            df = pd.read_parquet(dataset_parquet)
        elif dataset_csv.exists():
            dataset_path = dataset_csv
            df = pd.read_csv(dataset_csv)
        else:
            df = None
        if df is None:
            st.warning("No output dataset file for this run.")
        else:
            st.caption(f"{len(df)} rows in `{dataset_path.name}`.")
            st.dataframe(df, width="stretch", height=400)
            if "lineage_id" in df.columns:
                row_idx = st.number_input(
                    "Show the trail for row",
                    min_value=0,
                    max_value=len(df) - 1,
                    value=0,
                    step=1,
                    help=(
                        "Each row has a lineage record: which source rows, "
                        "which rule, who approved it."
                    ),
                )
                try:
                    lineage = json.loads(df["lineage_id"].iloc[int(row_idx)])
                    st.json(lineage)
                except (json.JSONDecodeError, TypeError):
                    st.info("No trail available for this row.")


# ---------------------------------------------------------------------------
# Page 3: Across-run memory
# ---------------------------------------------------------------------------


def _table_to_df(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", conn)  # noqa: S608


_LTM_TAB_LABELS: dict[str, tuple[str, str]] = {
    "rule_patterns": (
        "Rules we've seen before",
        "Validated rules the system can reuse on the next run without "
        "re-running the AI or asking for reviewer approval.",
    ),
    "ambiguity_resolutions": (
        "Prior reviewer decisions",
        "Decisions reviewers have made on ambiguous rules. New runs apply "
        "these automatically when the same ambiguity reappears.",
    ),
    "feedback_events": (
        "Activity log",
        "Every reviewer interaction recorded across runs, with the option "
        "chosen and the rationale (if provided).",
    ),
}


def _render_ltm_page(ltm_path: Path) -> None:
    st.subheader("IDC Rulebook")
    st.markdown(
        "What the pipeline remembers across tasks — validated rules, prior "
        "reviewer decisions, and a log of every interaction. The rulebook "
        "is how CliniTrace gets faster and more consistent the more you "
        "use it. &nbsp;(Stored as "
        + glossary.term("LTM")
        + ".)",
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ What's in this page?", expanded=False):
        st.markdown(
            "- **Rules we've seen before** — validated rule bodies the "
            "pipeline can reuse without re-asking an LLM. Each entry has a "
            "plain-English summary and a *Try it* sandbox so you can feed "
            "sample inputs and see the rule's output instantly.\n"
            "- **Prior reviewer decisions** — when a previous task hit an "
            "ambiguity, the reviewer's answer is stored here. The next task "
            "with the same ambiguity auto-resolves from this table — no "
            "ticket opened.\n"
            "- **Activity log** — every reviewer interaction across all "
            "tasks, with timestamps and rationales. Useful as an "
            "explainability / audit surface."
        )
        st.caption(
            "Rule bodies are stored **without a target column** so the same "
            "validated body can be reused across studies and target "
            "variables. The body signature (canonical hash) is what links "
            "an IDC entry to a remembered rule."
        )
    if not ltm_path.exists():
        st.info(f"No memory file at `{ltm_path}`. Run the pipeline first.")
        return
    conn = sqlite3.connect(ltm_path)
    try:
        tables = list(_LTM_TAB_LABELS.keys())
        labels = [_LTM_TAB_LABELS[t][0] for t in tables]
        sub_tabs = st.tabs(labels)
        for tab, name in zip(sub_tabs, tables, strict=True):
            with tab:
                st.caption(_LTM_TAB_LABELS[name][1])
                try:
                    df = _table_to_df(conn, name)
                except pd.errors.DatabaseError as exc:
                    st.error(
                        f"Could not read {_LTM_TAB_LABELS[name][0]!r}: {exc}"
                    )
                    continue
                if len(df) == 0:
                    st.info("Nothing remembered yet for this category.")
                    continue
                df_h = _humanize_df(df)
                st.caption(
                    f"{len(df_h)} entr{'y' if len(df_h) == 1 else 'ies'}."
                )
                st.dataframe(df_h, width="stretch", height=350)
                if name == "rule_patterns":
                    selected = st.selectbox(
                        "Show the rule body for entry",
                        list(range(len(df))),
                        format_func=lambda i, df=df: (
                            f"{humanize_rule_kind(df.iloc[i]['rule_kind'])} "
                            f"(fingerprint "
                            f"{short_fingerprint(df.iloc[i]['body_signature'])})"
                        ),
                        key=f"ltm_inspect_{name}",
                        help=(
                            "Pick an entry to see the full validated rule "
                            "body the system would reuse."
                        ),
                    )
                    if selected is not None:
                        row = df.iloc[selected]
                        rule_kind_code = row["rule_kind"]
                        body_raw = row["body"]
                        try:
                            body_obj = json.loads(body_raw)
                        except (json.JSONDecodeError, TypeError):
                            body_obj = None

                        st.markdown(f"#### {humanize_rule_kind(rule_kind_code)} rule")
                        st.caption(
                            "Validated rule the pipeline will reuse on the "
                            "next task whose IDC produces this same body "
                            "signature. The body itself is target-agnostic "
                            "— it does not carry a column name."
                        )
                        plain = glossary.humanize_rule_body(
                            rule_kind_code, body_obj
                        )
                        st.markdown(plain)
                        meta_cols = st.columns(3)
                        meta_cols[0].metric(
                            "Rule kind",
                            humanize_rule_kind(rule_kind_code),
                        )
                        meta_cols[1].metric(
                            "Body signature",
                            short_fingerprint(row["body_signature"]),
                            help="Canonical hash of the rule body. Same hash = same rule.",
                        )
                        first_run = row.get("first_seen_run_id")
                        meta_cols[2].metric(
                            "First seen in",
                            humanize_run_id(first_run) if first_run else "—",
                        )
                        st.markdown("**🧪 Try it — feed a sample input**")
                        st.caption(
                            "The result below is computed by the *real* "
                            "apply function used during a task run — what "
                            "you see here is exactly what the pipeline "
                            "would output."
                        )
                        if body_obj is not None:
                            rule_preview.render(
                                rule_kind_code,
                                body_obj,
                                key_prefix=f"ltm_{name}_{selected}",
                            )
                        else:
                            st.info(
                                "Cannot render a Try-it preview because "
                                "the saved body is not valid JSON."
                            )

                        with st.expander("Technical details (raw body JSON)"):
                            if body_obj is not None:
                                st.json(body_obj)
                            else:
                                st.code(str(body_raw))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Page 4: Documentation (Glossary + Tutorial)
# ---------------------------------------------------------------------------


def _render_documentation_page() -> None:
    # Lazy import for `about` — its module-level state is small but
    # matches the pattern presentation.py uses for its lazy assets.
    from clinitrace.ui import about as about_page  # noqa: PLC0415

    st.subheader("Documentation")
    st.caption(
        "Reference material that travels with the app. Pick Glossary for "
        "term definitions, Tutorial for a guided tour, or About for "
        "project background and author / source links."
    )
    sub_choice = option_menu(
        menu_title=None,
        options=["Glossary", "Tutorial", "About"],
        # bootstrap icons; info-circle is the standard 'about' affordance.
        icons=["book-half", "compass", "info-circle"],
        default_index=0,
        orientation="horizontal",
        key="doc_sub_menu",
    )
    if sub_choice == "Glossary":
        st.markdown(GLOSSARY_HTML, unsafe_allow_html=True)
    elif sub_choice == "Tutorial":
        st.markdown(TUTORIAL_HTML, unsafe_allow_html=True)
    else:
        # About uses st.code() for the repo tree (whitespace preservation)
        # plus st.markdown for the prose around it — so we delegate to
        # about.render() rather than emitting one big HTML blob.
        about_page.render()


# ---------------------------------------------------------------------------
# Page 5: Settings
# ---------------------------------------------------------------------------


_COMMON_TIMEZONES = [
    "UTC",
    "America/Toronto",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Australia/Sydney",
]

_COMMON_MODELS = [
    "gpt-oss:20b",
    "llama3.1:8b",
    "llama3.1:70b",
    "mistral:7b",
    "qwen2.5:7b",
    "qwen2.5:14b",
    "phi3:medium",
    "gemma2:9b",
]


def _get_pending(key: str, saved: dict) -> object:
    """Read pending value if user has edited; otherwise the saved value."""
    pending_key = f"pending_{key}"
    if pending_key in st.session_state:
        return st.session_state[pending_key]
    return saved.get(key)


def _set_pending(key: str, value: object) -> None:
    st.session_state[f"pending_{key}"] = value


def _clear_pending() -> None:
    for k in list(st.session_state.keys()):
        if k.startswith("pending_"):
            del st.session_state[k]


def _has_unsaved_changes(saved: dict) -> bool:
    for key, default_val in settings_store.DEFAULTS.items():
        pending = _get_pending(key, saved)
        if pending != saved.get(key, default_val):
            return True
    return False


def _render_settings_page() -> None:
    from clinitrace.presentation import set_display_timezone

    saved = settings_store.load()

    st.subheader("Settings")

    # -----------------------------------------------------------------
    # Display
    # -----------------------------------------------------------------
    st.markdown("### 🕐 Display")
    st.caption("How CliniTrace renders dates and times.")

    current_tz = _get_pending("display_tz", saved)
    tz_options = list(_COMMON_TIMEZONES)
    if current_tz not in tz_options:
        tz_options.insert(0, current_tz)
    new_tz = st.selectbox(
        "Timezone",
        options=tz_options,
        index=tz_options.index(current_tz),
        key="display_tz_select",
        help=(
            "All audit-trail timestamps are stored in UTC; this only changes "
            "how they're displayed."
        ),
    )
    _set_pending("display_tz", new_tz)

    st.divider()

    # -----------------------------------------------------------------
    # Paths
    # -----------------------------------------------------------------
    st.markdown("### 📁 Paths")
    st.caption("Where runs and memory live on disk.")
    new_out_dir = st.text_input(
        "Runs folder",
        value=_get_pending("out_dir", saved),
        key="out_dir_input",
        help="Folder containing this study's run subfolders.",
    )
    _set_pending("out_dir", new_out_dir)

    new_ltm_path = st.text_input(
        "Memory file",
        value=_get_pending("ltm_path", saved),
        key="ltm_path_input",
        help="File where CliniTrace stores what it has learned across runs.",
    )
    _set_pending("ltm_path", new_ltm_path)
    st.caption(
        "Paths are relative to where you launched the app. "
        "Tilde (~) is not expanded; use a full path if you need one."
    )

    st.divider()

    # -----------------------------------------------------------------
    # LLM
    # -----------------------------------------------------------------
    st.markdown("### 🤖 LLM")
    st.caption(
        "How CliniTrace calls a language model for spec review and code "
        "generation."
    )

    cloud_demo = settings_store.is_cloud_demo()
    if cloud_demo:
        # On Streamlit Cloud the user's local Ollama is not reachable, so
        # enabling live mode would just silently fail back to stub. We
        # disable the toggle and explain why — better than letting them
        # toggle it on and watch the LLM never actually fire.
        st.info(
            "☁️ **Cloud demo mode** — the LLM toggle is locked off. Live "
            "LLM mode requires a reachable Ollama (or other backend) "
            "URL; share.streamlit.io has no access to your local "
            "machine. To try live LLM, run CliniTrace locally with "
            "`python -m clinitrace ui`."
        )
        st.toggle(
            "Enable LLM",
            value=False,
            disabled=True,
            key="llm_enabled_toggle_cloud",
            help="Locked off on Streamlit Cloud — see banner above.",
        )
        _set_pending("llm_enabled", False)
        new_llm_enabled = False
    else:
        new_llm_enabled = st.toggle(
            "Enable LLM",
            value=_get_pending("llm_enabled", saved),
            key="llm_enabled_toggle",
            help=(
                "Off (stub mode): deterministic fixture-driven responses. No "
                "network. Recommended for demos and CI.\n\n"
                "On (live mode): actually call a language model. Requires the "
                "selected backend to be reachable."
            ),
        )
        _set_pending("llm_enabled", new_llm_enabled)

    backend_options = ["Local (Ollama)", "LangChain (planned)", "LangGraph (planned)"]
    current_backend = _get_pending("llm_backend", saved)
    if current_backend not in backend_options:
        current_backend = "Local (Ollama)"
    new_backend = st.radio(
        "Backend",
        options=backend_options,
        index=backend_options.index(current_backend),
        horizontal=True,
        key="llm_backend_radio",
        disabled=not new_llm_enabled,
        help=(
            "Local (Ollama): direct HTTP calls to a local Ollama server. "
            "Zero external dependencies beyond the model weights.\n\n"
            "LangChain / LangGraph: framework integrations are planned."
        ),
    )
    _set_pending("llm_backend", new_backend)
    if new_backend != "Local (Ollama)":
        st.warning(
            f"**{new_backend}** is not yet implemented. Falling back to "
            "Local (Ollama) if you start a live run."
        )

    if new_llm_enabled and new_backend == "Local (Ollama)":
        cols = st.columns([2, 1])
        with cols[0]:
            new_url = st.text_input(
                "Endpoint URL",
                value=_get_pending("llm_url", saved),
                key="llm_url_input",
                help="Ollama server URL.",
            )
            _set_pending("llm_url", new_url)

            current_model = _get_pending("llm_model", saved)
            model_options = list(_COMMON_MODELS)
            if current_model not in model_options:
                model_options.insert(0, current_model)
            new_model = st.selectbox(
                "Model",
                options=model_options,
                index=model_options.index(current_model),
                key="llm_model_select",
                help=(
                    "Model tag to use. Must already be pulled on the Ollama "
                    "server (`ollama pull <model>`)."
                ),
            )
            _set_pending("llm_model", new_model)
        with cols[1]:
            new_timeout = st.number_input(
                "Timeout (s)",
                min_value=5.0,
                max_value=600.0,
                value=float(_get_pending("llm_timeout", saved)),
                step=5.0,
                key="llm_timeout_input",
                help="Per-call timeout. Large models on CPU need >120s.",
            )
            _set_pending("llm_timeout", new_timeout)

        if st.button("Test connection", key="llm_test_btn"):
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"{new_url.rstrip('/')}/api/tags",
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = resp.read().decode("utf-8")
                tags = json.loads(body).get("models", [])
                names = [t.get("name", "") for t in tags]
                if new_model in names or any(
                    n.startswith(new_model.split(":")[0]) for n in names
                ):
                    st.success(
                        f"✅ Reachable. Model `{new_model}` is available."
                    )
                else:
                    st.warning(
                        f"⚠️ Reachable, but `{new_model}` not in installed "
                        f"models. Available: {names[:5]}"
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Could not reach Ollama: {exc}")
    elif not new_llm_enabled:
        st.info(
            "LLM is **disabled** (stub mode). Runs use deterministic "
            "fixture responses — perfect for demos."
        )

    # -----------------------------------------------------------------
    # Save / Reset row
    # -----------------------------------------------------------------
    st.divider()
    unsaved = _has_unsaved_changes(saved)
    if unsaved:
        st.warning("⚠️ You have unsaved changes.")

    save_col, discard_col, reset_col, status_col = st.columns([1, 1, 1, 3])
    with save_col:
        if st.button(
            "💾 Save settings",
            type="primary",
            disabled=not unsaved,
            key="settings_save_btn",
        ):
            values = {
                k: _get_pending(k, saved)
                for k in settings_store.DEFAULTS
            }
            path = settings_store.save(values)
            settings_store.apply_to_environment(values)
            # Apply display-side settings immediately
            st.session_state["display_tz"] = values["display_tz"]
            st.session_state["out_dir"] = values["out_dir"]
            st.session_state["ltm_path"] = values["ltm_path"]
            set_display_timezone(values["display_tz"])
            _clear_pending()
            st.success(f"Saved to `{path.name}`.")
            st.rerun()
    with discard_col:
        if st.button(
            "↺ Discard changes",
            disabled=not unsaved,
            key="settings_discard_btn",
        ):
            _clear_pending()
            st.rerun()
    with reset_col:
        if st.button("🗑 Reset to defaults", key="settings_reset_btn"):
            settings_store.reset()
            _clear_pending()
            settings_store.apply_to_environment(settings_store.DEFAULTS)
            st.session_state["display_tz"] = settings_store.DEFAULTS["display_tz"]
            st.session_state["out_dir"] = settings_store.DEFAULTS["out_dir"]
            st.session_state["ltm_path"] = settings_store.DEFAULTS["ltm_path"]
            set_display_timezone(settings_store.DEFAULTS["display_tz"])
            st.info("Reset to defaults.")
            st.rerun()
    with status_col:
        st.caption(
            f"Settings file: `{settings_store.config_path().name}` "
            f"({'exists' if settings_store.config_path().exists() else 'not yet created'})"
        )

    # ---------------------------------------------------------------------
    # Danger zone: reset everything
    # ---------------------------------------------------------------------
    _render_reset_everything(saved)


def _human_bytes(n: int) -> str:
    """Compact size string. 1024 -> '1.0 KB', etc."""
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB"]
    f = float(n)
    for u in units:
        f /= 1024.0
        if f < 1024.0:
            return f"{f:.1f} {u}"
    return f"{f:.1f} TB"


def _render_reset_everything(saved: dict[str, object]) -> None:
    """Render the Danger Zone: a two-step destructive reset.

    Why two-step (preview → confirm) and not a single button:
      a one-click "delete everything" is too easy to fat-finger, and the
      consequences (lost LTM, lost audit trail) are not recoverable. The
      preview shows the EXACT files+sizes that will be removed, keyed on
      the user's CURRENT paths (so a study lead who changed ltm_path can
      see their real LTM and not the default).
    """
    # Function-local import to match the convention used elsewhere in this
    # file (see _render_settings_page) — keeps the module-level import
    # graph small and avoids circular-import risk if presentation ever
    # needs to import from ui.
    from clinitrace.presentation import set_display_timezone
    st.divider()
    with st.expander("⚠️ Reset everything (advanced) — wipe custom state", expanded=False):
        st.caption(
            "Use this when you want a clean slate for a demo, or when "
            "switching between studies. Each checkbox is independent — "
            "pick only what you want to remove."
        )

        confirm_key = "reset_everything_confirm_pending"
        st.session_state.setdefault(confirm_key, False)

        clear_settings = st.checkbox(
            "Settings file (.clinitrace_settings.json)",
            key="reset_clear_settings",
            help=(
                "Reverts display timezone, paths, LLM config, etc. to "
                "shipped defaults. Same as the existing 'Reset to defaults' "
                "button above."
            ),
        )
        clear_ltm = st.checkbox(
            "LTM database — learned rules and reviewer decisions",
            key="reset_clear_ltm",
            help=(
                "Wipes all rule_patterns and ambiguity_resolutions. The "
                "next run will have to re-invoke the LLM for any "
                "rule the system has previously seen."
            ),
        )
        clear_history = st.checkbox(
            "Task history (demo_out/run-*)",
            key="reset_clear_history",
            help=(
                "Deletes every past Import Task: outputs, audit trails, "
                "lineage records, HITL tickets. Cannot be undone."
            ),
        )

        # Preview pane: show exact paths + sizes so the user knows what
        # they're about to lose BEFORE the irreversible click.
        preview = settings_store.hard_reset_summary(dict(saved))
        items: list[str] = []
        if clear_settings:
            sf = preview["settings_file"]
            if sf["exists"]:
                items.append(
                    f"  • `{sf['path']}` ({_human_bytes(sf['size'])})"
                )
            else:
                items.append(f"  • `{sf['path']}` *(does not exist — nothing to remove)*")
        if clear_ltm:
            lf = preview["ltm_db"]
            if lf["exists"]:
                items.append(
                    f"  • `{lf['path']}` ({_human_bytes(lf['size'])})"
                )
            else:
                items.append(f"  • `{lf['path']}` *(does not exist — nothing to remove)*")
        if clear_history:
            th = preview["task_history"]
            if th["exists"] and th["runs"] > 0:
                items.append(
                    f"  • `{th['path']}/run-*` "
                    f"({th['runs']} run dir(s), {_human_bytes(th['size'])})"
                )
            elif th["exists"]:
                items.append(f"  • `{th['path']}/run-*` *(no run dirs to remove)*")
            else:
                items.append(f"  • `{th['path']}` *(does not exist — nothing to remove)*")

        any_selected = clear_settings or clear_ltm or clear_history
        if any_selected:
            st.markdown("**Will remove:**")
            st.markdown("\n".join(items))
        else:
            st.info("Select at least one category above to preview the impact.")

        # Two-step confirm. First click → set pending; second click → do it.
        col_a, col_b, _ = st.columns([1, 1, 3])
        with col_a:
            if not st.session_state[confirm_key]:
                clicked = st.button(
                    "🗑 Remove selected…",
                    disabled=not any_selected,
                    key="reset_request_btn",
                )
                if clicked:
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(
                    "⚠️ This cannot be undone. Click **Yes, remove** to "
                    "proceed, or **Cancel** to back out."
                )
                if st.button(
                    "✓ Yes, remove",
                    type="primary",
                    key="reset_confirm_btn",
                ):
                    actions = settings_store.hard_reset(
                        clear_settings=clear_settings,
                        clear_ltm=clear_ltm,
                        clear_history=clear_history,
                        ltm_path=saved.get("ltm_path"),
                        out_dir=saved.get("out_dir"),
                    )
                    # After settings file is cleared, push defaults into env
                    # + session_state so the rest of the UI doesn't read
                    # stale values until the next page load.
                    if clear_settings:
                        settings_store.apply_to_environment(settings_store.DEFAULTS)
                        st.session_state["display_tz"] = settings_store.DEFAULTS["display_tz"]
                        st.session_state["out_dir"] = settings_store.DEFAULTS["out_dir"]
                        st.session_state["ltm_path"] = settings_store.DEFAULTS["ltm_path"]
                        set_display_timezone(settings_store.DEFAULTS["display_tz"])
                    # Clear the checkboxes so a repeat won't run by accident.
                    # NB: Streamlit forbids writing to a widget-bound key
                    # AFTER the widget renders on this pass. `del` is
                    # allowed and makes the checkbox reseed to its default
                    # (unchecked) on the next rerun.
                    for k in ("reset_clear_settings", "reset_clear_ltm", "reset_clear_history"):
                        if k in st.session_state:
                            del st.session_state[k]
                    st.session_state[confirm_key] = False
                    for line in actions:
                        st.success(line)
                    st.rerun()
        with col_b:
            if st.session_state[confirm_key]:
                if st.button("Cancel", key="reset_cancel_btn"):
                    st.session_state[confirm_key] = False
                    st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_MENU_OPTIONS = [
    "New Import\nTask",
    "IDC\nClarifications",
    "Import Task\nHistory",
    "IDC\nRulebook",
    "CliniTrace\nDocumentation",
    "Settings",
]

_MENU_ICONS = [
    "rocket-takeoff",
    "question-circle",
    "clipboard-data",
    "journal-bookmark",
    "book",
    "gear",
]


def main() -> None:
    st.set_page_config(page_title="CliniTrace", layout="wide")

    # ----- Apply background wallpaper -----------------------------------
    # The wallpaper lives in <repo_root>/docs/ alongside other
    # documentation assets. We resolve the path relative to this file so
    # the call works no matter what CWD Streamlit was launched from.
    # Apply BEFORE other CSS so our max-width / centering rules can
    # cascade over (and the wallpaper's `background-image` doesn't
    # collide with them — they target different selectors).
    from clinitrace.ui import wallpaper  # local import: keeps module-level imports tidy
    # parents[2] gets us to the repo root: this file is at
    # <root>/clinitrace/ui/streamlit_app.py (flat layout, no src/).
    # If the layout ever changes again, adjust this index AND the
    # corresponding one in new_run_wizard.py:_bundled_example_spec_path().
    _wallpaper_path = (
        Path(__file__).resolve().parents[2] / "docs" / "background_clinitrace.png"
    )
    wallpaper.apply(_wallpaper_path)

    st.markdown("""
        <style>
            /* Hide the empty sidebar nav (we removed the path inputs). */
            [data-testid="stSidebarNav"] { display: none; }

            /* Cap the content at a comfortable reading width and center it.
               Narrower than Streamlit's default "wide" (~1200px) so the
               layout doesn't sprawl on big monitors. */
            .main .block-container,
            [data-testid="stAppViewContainer"] .main .block-container,
            [data-testid="stMainBlockContainer"] {
                max-width: 1000px !important;
                margin-left: auto !important;
                margin-right: auto !important;
                padding-left: 2rem !important;
                padding-right: 2rem !important;
                padding-top: 2rem !important;
            }

            /* Thicker, more visible horizontal dividers. Default Streamlit
               draws a 1px hairline that's hard to see; 3px reads as an
               intentional section break. */
            hr,
            [data-testid="stDivider"] hr,
            [data-testid="stHeadingDivider"] {
                border-top-width: 3px !important;
                border-top-style: solid !important;
                margin-top: 1rem !important;
                margin-bottom: 1rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # On first render of the session, load saved settings from disk and push
    # them into session_state + env vars so the rest of the app sees them.
    from clinitrace.presentation import set_display_timezone
    if "settings_loaded" not in st.session_state:
        saved = settings_store.load()
        st.session_state["display_tz"] = saved["display_tz"]
        st.session_state["out_dir"] = saved["out_dir"]
        st.session_state["ltm_path"] = saved["ltm_path"]
        settings_store.apply_to_environment(saved)
        st.session_state["settings_loaded"] = True

    # Apply the user's display timezone before any humanize_timestamp call
    # on this page render (Settings, audit trail, etc.).
    set_display_timezone(st.session_state.get("display_tz", "UTC"))

    # The header row uses [1.2, 3] columns. The title/tagline cell is its
    # own flex column; the menu cell is independent. We bottom-align the
    # menu via CSS (see styles below) so the buttons sit at the same
    # baseline as the tagline regardless of how many lines the tagline takes.
    col1, col2 = st.columns([1.2, 3], vertical_alignment="bottom")
    with col1:
        st.title("CliniTrace")
        st.markdown(
            f'<div style="font-size: 0.75rem; color: #6b6b78; '
            f'line-height: 1.3; margin-top: -0.5rem;">{APP_TAGLINE}</div>',
            unsafe_allow_html=True,
        )
    with col2:
        # Menu styling notes:
        #   - white-space: pre-line lets embedded "\n" render as a real
        #     line break inside an option label.
        #   - flex + center on nav-link gives icon-above-text layout and
        #     keeps single-line and two-line items visually the same height.
        #   - min-height equalises all menu cells so the row looks balanced.
        choice = option_menu(
            menu_title=None,
            options=_MENU_OPTIONS,
            icons=_MENU_ICONS,
            default_index=0,
            orientation="horizontal",
            key="top_menu",
            styles={
                "container": {
                    "padding": "0",
                    "background-color": "transparent",
                },
                "nav-link": {
                    "white-space": "pre-line",
                    "text-align": "center",
                    "line-height": "1.15",
                    "font-size": "14px",
                    "display": "flex",
                    "flex-direction": "column",
                    "align-items": "center",
                    "justify-content": "center",
                    "min-height": "56px",
                    "padding": "8px 12px",
                    "margin": "0 2px",
                },
                "nav-link-selected": {
                    "font-weight": "600",
                },
                "icon": {
                    "margin-right": "0",
                    "margin-bottom": "4px",
                    "font-size": "18px",
                },
            },
        )

    # Horizontal rule separating the header (title + tagline + menu) from the
    # page body. Visually anchors the menu as part of the app chrome rather
    # than as part of whatever page the user is on.
    st.divider()

    # Persistent cloud-demo banner. Renders on every page (just under the
    # header) so users on share.streamlit.io always know the LLM is off.
    # We use st.info (not st.warning) because this is informational, not a
    # problem state — the app is operating exactly as configured.
    if settings_store.is_cloud_demo():
        st.info(
            "☁️ **You're viewing the Cloud demo** — running in stub mode "
            "(no live LLM, deterministic fixture responses). To exercise "
            "the live agentic loop with a real LLM, clone the repo and run "
            "locally: `python -m clinitrace ui`. State (LTM, audit) resets "
            "on each cold start."
        )

    # Show a small jargon-busters panel at the top of every page.
    with st.expander("📖 Jargon-busters (terms used in this app)", expanded=False):
        st.caption(
            "Hover any underlined term anywhere in the app for a definition. "
            "🤖 = LLM-backed agent · ⚙️ = deterministic agent (no LLM call)."
        )
        st.markdown("**Agents** (the six modular components of the pipeline)")
        agent_cols = st.columns(2)
        for i, code in enumerate(["SR", "CG", "V", "R", "A", "O"]):
            with agent_cols[i % 2]:
                label = glossary.agent_label(code)
                defn = glossary.define(code) or ""
                st.markdown(f"- **{label}** — {defn}")

        st.markdown("**Concepts and abbreviations**")
        general_terms = [
            "IDC", "HITL", "LTM", "STM", "DAG",
            "derivation", "ambiguity", "lineage", "audit trail",
            "stub mode", "live mode", "warm LTM", "cold LTM",
            "Ollama", "LangChain", "LangGraph",
        ]
        gcols = st.columns(3)
        for i, t in enumerate(general_terms):
            with gcols[i % 3]:
                defn = glossary.define(t)
                if defn:
                    st.markdown(f"**{t}** — {defn}")

    # Second divider closes the jargon-busters band; everything below this
    # belongs to the active page (subheader + body content).
    st.divider()

    out_dir, ltm_path = _current_paths()

    if choice == "New Import\nTask":
        new_run_wizard.render()
    elif choice == "IDC\nClarifications":
        _render_hitl_page(out_dir)
    elif choice == "Import Task\nHistory":
        _render_run_inspector(out_dir)
    elif choice == "IDC\nRulebook":
        _render_ltm_page(ltm_path)
    elif choice == "CliniTrace\nDocumentation":
        _render_documentation_page()
    elif choice == "Settings":
        _render_settings_page()


main()
