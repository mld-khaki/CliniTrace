"""Central glossary of CliniTrace terms + abbreviations.

The dict GLOSSARY maps every jargon term or abbreviation that appears in
the UI to a short, reviewer-friendly definition. UI surfaces (selectboxes,
buttons, markdown text) wrap such terms with the ``term()`` helper so a
hover tooltip surfaces the definition.

Why a single source of truth:
  - Definitions can drift if scattered through per-page docstrings.
  - We want the Documentation > Glossary page to render the SAME text
    that hover tooltips show, so a curious user has one place to learn.

The helper accepts an optional override definition so a page can give
local context for a term without polluting the global glossary.
"""

from __future__ import annotations

import html

GLOSSARY: dict[str, str] = {
    # Core domain
    "IDC": (
        "Importing Data Contract — a small YAML file that declares which "
        "columns to derive and how. CliniTrace treats it as the agreement "
        "between the data team and the pipeline."
    ),
    "Importing Data Contract": (
        "A YAML file declaring the derivations (new columns) to compute, "
        "their input columns, and any clinical rationale. Think of it as a "
        "data contract between you and the pipeline."
    ),
    "derivation": (
        "A new column the pipeline computes from existing ones using a rule "
        "(e.g. AGE_GROUP from age, RESPONSE_FLAG from response)."
    ),
    "ambiguity": (
        "When a rule's intent is unclear — typically because the rationale "
        "mentions a case the rule body does not handle. Surfaces as a "
        "reviewer question."
    ),
    "rationale": (
        "Free-text clinical justification attached to a rule, used by the "
        "Specification Review agent to detect ambiguity."
    ),
    "lineage": (
        "The trail from one output cell back to its source rows, rule body, "
        "and any reviewer decisions that produced it."
    ),
    "spec": "Older internal name for the Importing Data Contract.",
    # Agents
    "HITL": (
        "Human-in-the-Loop — a workflow checkpoint where the pipeline pauses "
        "and asks a reviewer to make a decision before continuing."
    ),
    "SR": (
        "Spec Reviewer 🤖 (LLM-backed) — interprets each rule and flags "
        "ambiguity."
    ),
    "CG": (
        "Code Generator 🤖 (LLM-backed) — normalises a rule into a "
        "validated form, or reuses one from long-term memory."
    ),
    "V": (
        "Verifier ⚙️ (deterministic) — runs schema, coverage, and property "
        "checks on a rule. Never calls an LLM."
    ),
    "R": (
        "Refiner ⚙️ (deterministic) — patches a rule when verification "
        "finds issues. Never calls an LLM."
    ),
    "A": (
        "Auditor ⚙️ (deterministic) — records lineage and the full event "
        "timeline. Never calls an LLM."
    ),
    "O": (
        "Orchestrator ⚙️ (deterministic) — schedules the agents and owns "
        "the DAG execution loop. Never calls an LLM."
    ),

    # Pretty agent labels (used as display strings on Agent steps column)
    "🤖 Spec Reviewer": (
        "LLM-backed agent that interprets each rule and flags ambiguity."
    ),
    "🤖 Code Generator": (
        "LLM-backed agent that normalises a rule into validated form."
    ),
    "⚙️ Verifier": (
        "Deterministic schema / coverage / property checks. No LLM calls."
    ),
    "⚙️ Refiner": (
        "Deterministic patcher that fixes a rule when verification fails."
    ),
    "⚙️ Auditor": (
        "Deterministic agent that appends lineage to audit_trail.jsonl."
    ),
    "⚙️ Orchestrator": (
        "Deterministic DAG planner and loop authority. No LLM calls."
    ),
    # Memory
    "STM": (
        "Short-Term Memory — per-task workflow state (current stage, "
        "intermediate outputs). Lives only as long as the task runs."
    ),
    "LTM": (
        "Long-Term Memory — a SQLite database of validated rules and prior "
        "reviewer decisions, shared across tasks so the pipeline learns "
        "between runs."
    ),
    # Architecture
    "DAG": (
        "Directed Acyclic Graph — the dependency structure between "
        "derivations. CliniTrace uses it to compute derivations in the "
        "right order."
    ),
    "LLM": (
        "Large Language Model — used for two agents (Spec Review, Code "
        "Generation). The rest of the pipeline is deterministic."
    ),
    "Ollama": (
        "A lightweight local LLM server. CliniTrace can call it via HTTP "
        "when 'live' mode is enabled."
    ),
    "LangChain": (
        "A popular Python framework for chaining LLM calls. CliniTrace does "
        "NOT use it — the orchestration is hand-rolled for regulatory "
        "auditability."
    ),
    "LangGraph": (
        "A graph-based LLM orchestration framework built on LangChain. "
        "Listed for completeness; CliniTrace doesn't use it."
    ),
    # Rule kinds
    "bin": (
        "A rule that buckets a numeric column into categories using "
        "edges and labels (e.g. age -> minor/adult/senior)."
    ),
    "flag": (
        "A rule that maps each input value to a fixed output string "
        "(e.g. response -> Y/N)."
    ),
    "duration": (
        "A rule that computes a time delta between two date columns "
        "(e.g. visit_date - treatment_start_date in days)."
    ),
    "compound": (
        "A rule that combines per-column predicates with AND/OR to "
        "produce a yes/no flag (e.g. ANALYSIS_POP_FLAG = age>=18 AND "
        "response IS NOT NULL)."
    ),
    "risk_score": (
        "A rule that walks an ordered ladder of tiers and assigns the "
        "first matching tier's label, with a fallback for unmatched "
        "rows (e.g. RISK_GROUP = high/medium/low)."
    ),
    # File formats
    "CSV": "Comma-separated values — plain text table format.",
    "TSV": "Tab-separated values — like CSV but with tabs.",
    "YAML": "Human-readable structured-data format. The IDC uses YAML.",
    "JSON": "Machine-readable structured-data format.",
    "Parquet": "Compressed columnar file format. Faster than CSV for large data.",
    # UI/UX
    "CLI": "Command-Line Interface — running the tool from a terminal.",
    "UI": "User Interface — this web app.",
    # Time
    "UTC": "Coordinated Universal Time — the reference timezone with no offset.",
    "ISO 8601": "Standard timestamp format like 2026-05-26T15:26:34Z.",
    # Misc
    "DSL": "Domain-Specific Language — a small language tailored to a domain.",
    "audit trail": (
        "An append-only log of every event the pipeline produced, with "
        "timestamps and event IDs. Used for reconstruction and review."
    ),
    "stub mode": (
        "Pipeline runs without calling any LLM, using deterministic fixture "
        "responses. Useful for demos and CI."
    ),
    "live mode": "Pipeline calls a real LLM (currently via Ollama).",
    "warm LTM": (
        "An LTM database that already contains validated rules / resolutions "
        "from prior tasks, so the new task can skip work."
    ),
    "cold LTM": "An empty or new LTM database; the pipeline starts from scratch.",
}


AGENT_LABELS: dict[str, str] = {
    "SR": "🤖 Spec Reviewer",
    "CG": "🤖 Code Generator",
    "V":  "⚙️ Verifier",
    "R":  "⚙️ Refiner",
    "A":  "⚙️ Auditor",
    "O":  "⚙️ Orchestrator",
}


def agent_label(code: str) -> str:
    """Return the icon+name label for an internal agent code (SR/CG/V/R/A/O).
    Unknown codes pass through unchanged so the function is safe on legacy
    or future agent codes that have not been mapped yet.
    """
    return AGENT_LABELS.get(code, code)


def agent_chain_label(codes: list[str]) -> str:
    """Join a list of agent codes (e.g. ['CG', 'V']) into a friendly arrow
    chain ('🤖 Code Generator → ⚙️ Verifier'). Used in the Run review
    table's 'Agent steps' column.
    """
    return " → ".join(agent_label(c) for c in codes if c)


def define(term_label: str) -> str | None:
    """Return the canonical definition for a term, or None if not in glossary."""
    return GLOSSARY.get(term_label)


def term(label: str, definition: str | None = None) -> str:
    """Return an HTML <abbr> tag that shows a tooltip on hover.

    Falls back to the label-only if no definition can be resolved.
    """
    text = definition or define(label)
    if not text:
        return html.escape(label)
    return (
        f'<abbr title="{html.escape(text)}" '
        f'style="text-decoration: underline dotted; cursor: help;">'
        f"{html.escape(label)}</abbr>"
    )


def help_text(label: str, definition: str | None = None) -> str:
    """Return a plain-text definition suitable for the `help` parameter on
    Streamlit widgets. Falls back to the label if no definition exists.
    """
    text = definition or define(label)
    return text or label


# ---------------------------------------------------------------------------
# Rule-body humanization
# ---------------------------------------------------------------------------


def _humanize_bin(body: dict) -> str:
    edges = body.get("edges", []) or []
    labels = body.get("labels", []) or []
    null_handling = body.get("null_handling", "null")

    if len(labels) != len(edges) + 1:
        return (
            "Bucketing rule (the configuration looks unusual: "
            f"{len(labels)} label(s) for {len(edges)} cutoff(s))."
        )

    ranges = []
    for i, label in enumerate(labels):
        if i == 0:
            ranges.append(f"below **{edges[0]}** → **{label}**")
        elif i == len(labels) - 1:
            ranges.append(f"**{edges[i-1]}** and above → **{label}**")
        else:
            ranges.append(
                f"**{edges[i-1]}** to under **{edges[i]}** → **{label}**"
            )

    null_phrase = {
        "null":  "Missing values pass through as null.",
        "label": (
            f"Missing values are labelled "
            f"**{body.get('null_label', '?')}**."
        ),
        "skip":  "Missing values are skipped entirely.",
    }.get(null_handling, f"Null handling: {null_handling}.")

    return (
        f"Buckets a numeric column into {len(labels)} categories: "
        + "; ".join(ranges)
        + ". "
        + null_phrase
    )


def _humanize_flag(body: dict) -> str:
    mapping = body.get("map", {}) or {}
    if not mapping:
        return "Value-mapping rule (no mapping defined)."

    pairs = [f"`{k}` → **{v}**" for k, v in mapping.items()]
    summary = "Maps each input value to a fixed output flag: " + ", ".join(pairs) + "."

    unmapped = body.get("unmapped_handling")
    unmapped_val = body.get("unmapped_value")
    if unmapped == "value" and unmapped_val is not None:
        summary += f" Any other input → **{unmapped_val}**."
    elif unmapped == "null":
        summary += " Any other input → null."
    elif unmapped == "error":
        summary += " Any other input → raises an error."

    null_handling = body.get("null_handling")
    if null_handling == "null":
        summary += " Missing values pass through as null."
    elif null_handling == "label" and body.get("null_label") is not None:
        summary += f" Missing values are labelled **{body['null_label']}**."

    return summary


def _humanize_duration(body: dict) -> str:
    start = body.get("start_column", "?")
    end = body.get("end_column", "?")
    unit = body.get("unit", "days")
    nh = body.get("null_handling", "null")
    null_phrase = (
        "Rows with a missing start or end emit null."
        if nh == "null"
        else "Rows with a missing start or end raise an error."
    )
    return (
        f"Computes **{end} − {start}** expressed in **{unit}**. "
        f"{null_phrase}"
    )


_COMPOUND_OP_PHRASES = {
    "==": "equals",
    "!=": "does not equal",
    ">=": "is at least",
    "<=": "is at most",
    ">":  "is greater than",
    "<":  "is less than",
    "is_null":  "is missing",
    "not_null": "is present",
    "in":       "is one of",
}


def _format_compound_condition(cond: dict) -> str:
    col = cond.get("column", "?")
    op = cond.get("op", "?")
    value = cond.get("value")
    phrase = _COMPOUND_OP_PHRASES.get(op, op)
    if op in ("is_null", "not_null"):
        return f"`{col}` {phrase}"
    if op == "in":
        return f"`{col}` {phrase} {value!r}"
    return f"`{col}` {phrase} **{value}**"


def _humanize_compound(body: dict) -> str:
    conds = body.get("conditions", []) or []
    if not conds:
        return "Compound rule (no conditions defined)."
    combinator = body.get("combinator", "and").upper()
    true_v = body.get("true_value", "Y")
    false_v = body.get("false_value", "N")
    nh = body.get("null_handling", "false")

    parts = [_format_compound_condition(c) for c in conds]
    joiner = f" **{combinator}** "
    summary = (
        f"Emits **{true_v}** when " + joiner.join(parts) +
        f"; otherwise **{false_v}**."
    )
    null_phrase = {
        "null":     " Rows with a missing operand emit null.",
        "false":    f" Rows with a missing operand default to **{false_v}**.",
        "true":     f" Rows with a missing operand default to **{true_v}**.",
        "error":    " Rows with a missing operand raise an error.",
    }.get(nh, "")
    return summary + null_phrase


def _humanize_risk_score(body: dict) -> str:
    tiers = body.get("tiers", []) or []
    if not tiers:
        return "Risk-tier rule (no tiers defined)."

    rungs: list[str] = []
    for tier in tiers:
        label = tier.get("label", "?")
        conds = tier.get("conditions", []) or []
        combinator = tier.get("combinator", "and").upper()
        parts = [_format_compound_condition(c) for c in conds]
        joiner = f" **{combinator}** "
        rungs.append(f"**{label}** if " + joiner.join(parts))

    fallback = body.get("fallback_label", "?")
    nh = body.get("null_handling", "fallback")
    null_phrase = {
        "fallback": f" Rows where no tier resolves fall through to **{fallback}**.",
        "null":     " Rows where no tier resolves emit null.",
        "error":    " Rows where no tier resolves raise an error.",
    }.get(nh, "")
    return (
        "Walks the ladder top-to-bottom; first match wins. "
        + "; ".join(rungs)
        + f"; otherwise **{fallback}**."
        + null_phrase
    )


_HUMANIZERS = {
    "bin": _humanize_bin,
    "flag": _humanize_flag,
    "duration": _humanize_duration,
    "compound": _humanize_compound,
    "risk_score": _humanize_risk_score,
}


def humanize_rule_body(rule_kind: str, body: dict | None) -> str:
    """Return a plain-English description of what a saved rule body does.

    The same rule body is reusable across studies / target columns -- it does
    NOT carry a target name. That's by design: validated bodies are stored
    target-agnostically so they can be matched by canonical signature across
    runs.
    """
    if body is None:
        return f"No rule body recorded for this {rule_kind} entry."
    fn = _HUMANIZERS.get(rule_kind)
    if fn is None:
        return (
            f"This is a `{rule_kind}` rule. "
            "Plain-English summary not yet available for this rule kind — "
            "see the raw body below."
        )
    return fn(body)
