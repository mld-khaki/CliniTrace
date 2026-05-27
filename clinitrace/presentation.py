"""Presentation layer: human-readable labels for CliniTrace internals.

This module is the single source of truth for every string the reviewer
sees. Internal identifiers (verification layer codes like L1/L_p,
snake_case event types, property-test IDs like P-bin-1) stay in code for
engineers; the labels here are what we render to a clinical data manager
who has never read the design document.

Voice target: clinical data manager / study analyst. Comfortable with
"derived variable", "rule", "check", "review". Not a Python developer.

Discipline:
  - All source strings are ASCII (no smart quotes, no em-dashes); use "--".
  - Every helper falls back to the raw input on miss, so a new internal
    identifier never breaks the UI -- it just shows the dev label until
    someone adds a friendly one here.
  - This module imports nothing from clinitrace.* to stay decoupled and
    cheap to load from any agent or UI surface.
"""

from __future__ import annotations

from datetime import UTC

# --------------------------------------------------------------------------
# Verification layer names
# --------------------------------------------------------------------------

# Internal layer code -> reviewer label.
LAYER_LABELS: dict[str, str] = {
    "L1": "Schema check",
    "L2": "Coverage check",
    "L_p": "Behavior check",
}


# --------------------------------------------------------------------------
# HITL ticket kinds
# --------------------------------------------------------------------------

# Headline rendered in the Streamlit ticket page header.
TICKET_KIND_LABELS: dict[str, str] = {
    "ambiguity": "Ambiguous rule -- needs your judgement",
    "approval": "New rule -- needs your approval",
    "triage": "Rule failed its checks -- needs your decision",
}

# Lead-in sentence rendered above the actual prompt, so the reviewer knows
# what kind of question they are answering before reading the details.
TICKET_KIND_LEAD: dict[str, str] = {
    "ambiguity": (
        "We found a rule the spec doesn't fully define. Your call decides "
        "how the system behaves for this study."
    ),
    "approval": (
        "We've never seen this rule before in any prior run. Approve it "
        "before we apply it to the data."
    ),
    "triage": (
        "The system tried a few revisions and the rule still doesn't pass "
        "our checks. We need you to choose how to proceed."
    ),
}


# --------------------------------------------------------------------------
# Audit-trail event types
# --------------------------------------------------------------------------

# Every event_type currently emitted by Audit.log() should have an entry here.
# When you add a new event_type, add a label too -- the tests check coverage.
EVENT_TYPE_LABELS: dict[str, str] = {
    "run_start":                "Run started",
    "sr_complete":              "Spec review complete",
    "dag_planned":              "Execution plan ready",
    "dag_plan_failed":          "Could not plan execution",
    "dataset_check_failed":     "Dataset failed initial check",
    "cg_complete":              "Rule normalized",
    "v_complete":               "Checks complete",
    "r_complete":               "Rule revised",
    "r_budget_exhausted":       "Revision attempts exhausted",
    "r_early_stop":             "Revision halted (no further progress)",
    "apply_complete":           "Rule executed",
    "derivation_skipped":       "Variable skipped",
    "hitl_open":                "Reviewer question opened",
    "hitl_resolved":            "Reviewer question resolved",
    "hitl_auto_resolved":       "Reviewer question auto-resolved from memory",
    "ltm_write":                "Memory updated",
    "run_complete":             "Run complete",
    "dataset_format_fallback":  "Output format switched",
}


# --------------------------------------------------------------------------
# Property test IDs (verification's L_p layer)
# --------------------------------------------------------------------------

# Per-rule_kind invariants. Descriptions are written so the test ID
# is itself the explanation. P-bin-1 means nothing; the value here
# does.
PROPERTY_LABELS: dict[str, str] = {
    # bin
    "P-bin-1": "Every value lands in exactly one declared bucket",
    "P-bin-2": "Missing values are handled per the spec",
    "P-bin-3": "Output values stay within the declared bucket list",
    "P-bin-4": "Same input gives the same output every time",
    # flag
    "P-flag-1": "Every declared input maps to its declared output",
    "P-flag-2": "Missing values are handled per the spec",
    "P-flag-3": "Unmapped values are handled per the spec",
    "P-flag-4": "Output values stay within the declared set",
    "P-flag-5": "Same input gives the same output every time",
    # duration (deferred rule_kind, contracts documented)
    "P-duration-1": "Time differences are non-negative when end >= start",
    "P-duration-2": "Missing dates are handled per the spec",
    "P-duration-3": "Unit conversion matches a reference calculation",
    "P-duration-4": "Negative durations are handled per the spec",
    "P-duration-5": "Same input gives the same output every time",
    # mapping (deferred)
    "P-mapping-1": "Every declared key tuple maps to its declared value",
    "P-mapping-2": "Unknown key combinations are handled per the spec",
    "P-mapping-3": "Missing values in keys are handled per the spec",
    "P-mapping-4": "Output values stay within the declared set",
    "P-mapping-5": "Same input gives the same output every time",
    # expression (deferred)
    "P-expression-1": "Same input gives the same output every time",
    "P-expression-2": "Output is a finite number for reasonable inputs",
    "P-expression-3": "Division by zero is handled per the spec",
    "P-expression-4": "Missing input values are handled per the spec",
    "P-expression-5": "Output stays within the declared range",
    # compound
    "P-compound-1": "All condition outcomes are covered",
    "P-compound-2": "Null handling is explicit per the spec",
    "P-compound-3": "Output values are within the declared set",
    "P-compound-4": "Same input gives the same output every time",
    # risk_score
    "P-risk_score-1": "Every tier is reachable by some input",
    "P-risk_score-2": "Tier ordering is enforced (first match wins)",
    "P-risk_score-3": "Unmatched rows receive the fallback label",
    "P-risk_score-4": "Null handling per spec when all tiers are undefined",
    "P-risk_score-5": "Same input gives the same output every time",
}


# --------------------------------------------------------------------------
# Severities
# --------------------------------------------------------------------------

SEVERITY_LABELS: dict[str, str] = {
    "error":   "blocking",
    "warning": "advisory",
    "info":    "informational",
}


# --------------------------------------------------------------------------
# Rule kinds
# --------------------------------------------------------------------------

# Internal rule_kind name -> reviewer label. The reviewer sees this in the
# per-variable section of run_summary.md: "Rule type: Bucketing", etc.
RULE_KIND_LABELS: dict[str, str] = {
    "bin":        "Bucketing",
    "flag":       "Value mapping",
    "duration":   "Time difference",
    "expression": "Computed expression",
    "mapping":    "Multi-key lookup",
    "compound":   "Conditional assignment",
    "risk_score": "Risk stratification",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def humanize_layer(layer: str) -> str:
    """Return a reviewer-friendly name for a verification layer code."""
    return LAYER_LABELS.get(layer, layer)


def humanize_ticket_kind(kind: str) -> str:
    """Return a headline for an HITL ticket kind."""
    return TICKET_KIND_LABELS.get(kind, kind)


def ticket_lead_in(kind: str) -> str:
    """Return the orientation sentence shown above the ticket prompt."""
    return TICKET_KIND_LEAD.get(
        kind, "We need your input on this rule."
    )


def humanize_event(event_type) -> str:
    """Return a reviewer-friendly headline for an audit-trail event type.

    Fallback: snake_case -> Title Case, so a brand-new event type at least
    renders readably until someone adds it to EVENT_TYPE_LABELS. Returns
    non-string inputs unchanged so pandas .map() over a column with NaN /
    None rows does not crash.
    """
    if not isinstance(event_type, str):
        return event_type
    if event_type in EVENT_TYPE_LABELS:
        return EVENT_TYPE_LABELS[event_type]
    return event_type.replace("_", " ").capitalize()


def humanize_property(property_id: str) -> str:
    """Return a reviewer-friendly description for a property-test ID."""
    return PROPERTY_LABELS.get(property_id, property_id)


def humanize_severity(severity: str) -> str:
    """Return a reviewer-friendly word for a finding severity level."""
    return SEVERITY_LABELS.get(severity, severity)


def humanize_rule_kind(rule_kind: str) -> str:
    """Return a reviewer-friendly name for a rule_kind."""
    return RULE_KIND_LABELS.get(rule_kind, rule_kind)


# --------------------------------------------------------------------------
# Resolution option labels (Round 3)
# --------------------------------------------------------------------------

# Raw option strings emitted by SR (stub + LLM contract) -> reviewer text.
# These are the radio-button labels shown to the reviewer in the HITL page.
# The raw string stays as the chosen_option value in the resolution JSON for
# downstream code, but the reviewer never sees the raw form.
RESOLUTION_OPTION_LABELS: dict[str, str] = {
    # flag, unmapped-value ambiguity
    "treat_unmapped_as_null": "Map unknown values to blank (null)",
    "flag_unknown_as_U":      "Map unknown values to a special flag 'U'",
    "raise_on_unmapped":      "Exclude unknown values from the output",
    # bin, null-handling ambiguity
    "treat_null_as_null":     "Leave missing values as blank (null)",
    "treat_null_as_label":    "Assign missing values to a dedicated bucket",
    "raise_on_null":          "Exclude rows with missing values",
    # generic / rationale ambiguity
    "accept_default":         "Accept the rule as drafted",
    "modify_body":            "Edit the rule before applying it",
    "reject":                 "Reject the rule and do not produce this variable",
}


def humanize_option(option) -> str:
    """Return a reviewer-friendly label for a resolution option.

    Fallback: turn snake_case into a sentence so a brand-new option at least
    reads as words until someone adds it to RESOLUTION_OPTION_LABELS.
    Returns non-string inputs unchanged for pandas .map() NaN safety.
    """
    if not isinstance(option, str):
        return option
    if option in RESOLUTION_OPTION_LABELS:
        return RESOLUTION_OPTION_LABELS[option]
    return option.replace("_", " ").capitalize()


# --------------------------------------------------------------------------
# Ambiguity classes (Round 3)
# --------------------------------------------------------------------------

AMBIGUITY_CLASS_LABELS: dict[str, str] = {
    "unmapped_value_undefined":
        "Some inputs are not covered by the mapping",
    "null_handling_undefined":
        "Behaviour for missing values is not specified",
    "rationale_undefined":
        "The rule needs human judgement before it can be applied",
    "ltm_cached":
        "This ambiguity matched a prior reviewer decision in memory",
    "missing_logic":
        "The rule is missing logic the spec did not provide",
    "structural_conflict":
        "The rule body and rationale disagree",
}


def humanize_ambiguity_class(ambiguity_class) -> str:
    """Return a reviewer-friendly description of an ambiguity classification.

    Returns non-string inputs unchanged for pandas .map() NaN safety -- the
    audit_trail.jsonl has heterogeneous event schemas, so columns built from
    it will have NaN in rows that do not carry this field.
    """
    if not isinstance(ambiguity_class, str):
        return ambiguity_class
    if ambiguity_class in AMBIGUITY_CLASS_LABELS:
        return AMBIGUITY_CLASS_LABELS[ambiguity_class]
    return ambiguity_class.replace("_", " ").capitalize()


# --------------------------------------------------------------------------
# Dataframe column humanizers (Round 3)
# --------------------------------------------------------------------------

COLUMN_LABELS: dict[str, str] = {
    "ts":                  "When",
    "run_id":              "Run",
    "event_type":          "Activity",
    "event_id":            "Question ID",
    "target":              "Variable",
    "ticket_kind":         "Question type",
    "rule_kind":           "Rule type",
    "body_signature":      "Rule fingerprint",
    "signature":           "Fingerprint",
    "ambiguity_signature": "Question fingerprint",
    "ambiguity_class":     "Question category",
    "chosen_option":       "Decision",
    "options_offered":     "Options offered",
    "resolved_by":         "Decided by",
    "free_text_rationale": "Reviewer note",
    "hitl_event_ids":      "Linked question IDs",
    "hitl_event_id":       "Question ID",
    "body":                "Rule body (technical)",
    "agent_chain":         "Agent steps",
    "iteration":           "Revision number",
    "iterations":          "Revisions",
    "ltm_hit":             "Recognised from memory",
    "ltm_pattern_ref":     "Memory entry",
    "passed":              "Passed",
    "n_findings":          "Issues raised",
    "findings":            "Issues",
    "reason":              "Reason",
    "status":              "Status",
    "source_mode":         "AI source (per call)",
    "source_model":        "AI model",
    "spec_version":        "Spec version",
    "execution_order":     "Order of execution",
    "outcome":             "Outcome",
    "confidence":          "Confidence",
    "llm_mode":            "AI mode (for run)",
    "table":               "Memory area",
    "wrote":               "Wrote",
    "started_at":          "Started",
    "completed_at":        "Completed",
    "created_at":          "Created",
    "updated_at":          "Updated",
    "opened_at":           "Opened at",
    "resolved_at":         "Resolved at",
    "first_seen_at":       "First seen",
    "first_seen_run_id":   "First seen in run",
    "approval_event_id":   "Approval question ID",
    "resolved_run_id":     "Resolved in run",
    "resolution_event_id": "Question ID",
    "resolution":          "Decision",
}


def humanize_column(column) -> str:
    """Return a reviewer-friendly column header for a raw dataframe column.

    Returns non-string inputs unchanged for safety, even though column names
    are typically strings.
    """
    if not isinstance(column, str):
        return column
    if column in COLUMN_LABELS:
        return COLUMN_LABELS[column]
    return column.replace("_", " ").capitalize()


def humanize_columns(columns) -> dict:
    """Return a {raw -> human} rename map for an iterable of column names.

    Collision-safe: if multiple raw columns would map to the same human
    label, the first occurrence keeps the human label and subsequent
    occurrences are suffixed with the raw key in parentheses. This prevents
    pandas/pyarrow from raising ValueError on duplicate column names when a
    heterogeneous audit trail produces columns whose human labels collide.
    """
    seen: set[str] = set()
    result: dict = {}
    for c in columns:
        label = humanize_column(c)
        if not isinstance(label, str):
            # Non-string column name (rare); pass through unchanged.
            result[c] = label
            continue
        if label in seen and label != c:
            # Collision -- suffix with the raw key so the reviewer can still
            # tell columns apart, and pandas does not produce duplicates.
            label = f"{label} ({c})"
        seen.add(label)
        result[c] = label
    return result


# --------------------------------------------------------------------------
# Status labels (Round 3)
# --------------------------------------------------------------------------

STATUS_LABELS: dict[str, str] = {
    "verified":   "Verified",
    "unresolved": "Unresolved",
    "skipped":    "Skipped",
    "missing":    "Not produced",
    "passed":     "Passed",
    "failed":     "Failed",
}


def humanize_status(status) -> str:
    """Return a reviewer-friendly status word.

    Returns non-string inputs unchanged so pandas .map() over a column with
    NaN rows does not produce the cosmetic string "Nan".
    """
    if not isinstance(status, str):
        return status
    if status in STATUS_LABELS:
        return STATUS_LABELS[status]
    return status.replace("_", " ").capitalize()


# --------------------------------------------------------------------------
# Run / event / fingerprint friendly identifiers (Round 3)
# --------------------------------------------------------------------------

def humanize_run_id(run_id: str) -> str:
    """Render a 'run-20260522T203140Z-39f341'-style ID as a reviewer-friendly
    label like 'May 22, 2026 at 4:31 PM EDT (39f341)' in the display tz.

    Falls back to the raw run_id on any parse failure -- this is presentation
    only, never used as a key.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        rest = run_id.removeprefix("run-")
        ts_part, short = rest.split("-", 1)
        # Build a UTC datetime from the embedded YYYYMMDDTHHMMSSZ stamp.
        dt_utc = datetime(
            int(ts_part[0:4]),
            int(ts_part[4:6]),
            int(ts_part[6:8]),
            int(ts_part[9:11]),
            int(ts_part[11:13]),
            int(ts_part[13:15]),
            tzinfo=UTC,
        )
        try:
            target_tz = ZoneInfo(_DISPLAY_TZ_NAME)
            dt_local = dt_utc.astimezone(target_tz)
            tz_label = dt_local.tzname() or _DISPLAY_TZ_NAME
        except Exception:
            dt_local = dt_utc
            tz_label = "UTC"
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        hour = dt_local.hour
        suffix = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return (
            f"{months[dt_local.month - 1]} {dt_local.day}, {dt_local.year} at "
            f"{hour12}:{dt_local.minute:02d} {suffix} {tz_label} ({short})"
        )
    except Exception:
        return run_id


def short_fingerprint(value, length: int = 6) -> str:
    """Truncate a long hex hash to a short tag for display.

    Returns the value unchanged for non-string non-None inputs (NaN, ints) so
    pandas .map() over a heterogeneous column does not produce ugly strings
    like "nan".
    """
    if value is None:
        return "(none)"
    if not isinstance(value, str):
        return value
    if len(value) <= length:
        return value
    return value[:length]


# Module-level display timezone. The UI updates this from session_state so
# humanized timestamps follow the user's preference without every caller
# having to pass tz explicitly.
_DISPLAY_TZ_NAME: str = "UTC"


def set_display_timezone(tz_name: str) -> None:
    """Set the timezone used by humanize_timestamp for display.

    Accepts any IANA tz name (e.g. 'America/Toronto', 'Europe/Paris', 'UTC').
    Invalid names silently fall back to UTC so the UI never crashes on
    a misconfigured setting.
    """
    global _DISPLAY_TZ_NAME
    if not isinstance(tz_name, str) or not tz_name:
        _DISPLAY_TZ_NAME = "UTC"
        return
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz_name)  # validate
        _DISPLAY_TZ_NAME = tz_name
    except Exception:
        _DISPLAY_TZ_NAME = "UTC"


def get_display_timezone() -> str:
    """Return the currently configured display timezone name."""
    return _DISPLAY_TZ_NAME


def humanize_timestamp(value) -> str:
    """Render an ISO 8601 timestamp as a reviewer-friendly date string.

    Converts the UTC timestamp into the display timezone configured via
    set_display_timezone(). Default is UTC.

    '2026-05-22T20:32:25.944584+00:00' -> 'May 22, 2026, 4:32 PM EDT'.

    Returns the value unchanged for non-string inputs (NaN, None) so pandas
    .map() over a heterogeneous timestamp column does not crash. Also returns
    the input unchanged on any parse error -- presentation only, never used
    as a key.
    """
    if not isinstance(value, str):
        return value
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # fromisoformat() handles both "+00:00" and the older "Z" suffix in
        # Python 3.11+, but on 3.10 we have to swap Z manually for safety.
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        try:
            target_tz = ZoneInfo(_DISPLAY_TZ_NAME)
            dt_local = dt.astimezone(target_tz)
            tz_label = dt_local.tzname() or _DISPLAY_TZ_NAME
        except Exception:
            dt_local = dt
            tz_label = "UTC"
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        hour = dt_local.hour
        suffix = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        return (
            f"{months[dt_local.month - 1]} {dt_local.day}, {dt_local.year}, "
            f"{h12}:{dt_local.minute:02d} {suffix} {tz_label}"
        )
    except Exception:
        return value


def humanize_event_id(value) -> str:
    """Render an event_id like 'evt-381f3b7a4dd6' as '381f3b7a' for compact
    display. Strips the 'evt-' prefix and keeps the first 8 hex chars so a
    reviewer can still match it against the audit trail.

    Returns non-strings unchanged.
    """
    if not isinstance(value, str):
        return value
    stripped = value.removeprefix("evt-")
    if not stripped:
        return value
    return stripped[:8]


def summarize_resolution(value):
    """Extract the reviewer-meaningful field from a resolution JSON string.

    Returns just the humanized chosen_option as a plain sentence. The full
    structured resolution remains available via row-inspectors that show the
    raw JSON below the table.

    Input shape (from SQLite TEXT column):
        '{"body_patch": {}, "chosen_option": "treat_unmapped_as_null", "free_text_rationale": ""}'

    Returns the input unchanged on parse error or non-string input.
    """
    if not isinstance(value, str):
        return value
    import json
    try:
        obj = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value
    if not isinstance(obj, dict):
        return value
    chosen = obj.get("chosen_option")
    if not chosen or not isinstance(chosen, str):
        return value
    # Only humanize when chosen is a raw key. Plain-English values (from
    # older demo resolutions or "Other (free text)" picks) are preserved
    # verbatim -- capitalize() would mangle them.
    if chosen in RESOLUTION_OPTION_LABELS:
        return RESOLUTION_OPTION_LABELS[chosen]
    return chosen


def summarize_options(value):
    """Render a JSON-encoded options list as a semicolon-separated summary.

    Input can be either:
      '{"options": ["raw_key1", "raw_key2"]}'  (feedback_events table)
      '["raw_key1", "raw_key2"]'               (audit_trail in-memory)

    Returns the input unchanged on parse error or non-string input.
    """
    if not isinstance(value, str):
        return value
    import json
    try:
        obj = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value
    if isinstance(obj, dict):
        opts = obj.get("options", [])
    elif isinstance(obj, list):
        opts = obj
    else:
        return value
    if not opts:
        return "(no options recorded)"
    def _one(o):
        if not isinstance(o, str):
            return str(o)
        # Same rule as summarize_resolution: only humanize raw keys; plain
        # English values pass through.
        return RESOLUTION_OPTION_LABELS.get(o, o)
    return "; ".join(_one(o) for o in opts)


# --------------------------------------------------------------------------
# Page-level chrome (Round 3)
# --------------------------------------------------------------------------

APP_TAGLINE: str = (
    "Apply a transformation spec to a clinical dataset with checks, reviewer "
    "questions, and a full trail of what happened."
)

TAB_DESCRIPTIONS: dict[str, str] = {
    "review_questions": (
        "Questions the system raised while applying your spec. Each one needs "
        "a decision before that derived variable can be marked verified."
    ),
    "run_review": (
        "Inspect a past run: the plain-language summary, the checks each rule "
        "passed, the activity log, and the output dataset with per-row lineage."
    ),
    "across_run_memory": (
        "Rules and decisions the system has remembered across runs. New runs "
        "consult this memory first so reviewers do not answer the same "
        "question twice."
    ),
}


# --------------------------------------------------------------------------
# Glossary
# --------------------------------------------------------------------------

GLOSSARY: str = """\
| Term | Meaning |
| --- | --- |
| Rule | A single instruction for deriving a new column from existing ones. |
| Derived variable | A column the system computes from the patient dataset using a rule. |
| Schema check | A first pass that verifies the rule itself is well-formed (e.g., bucket boundaries make sense). |
| Coverage check | Confirms every possible input value has a defined output. No "and otherwise null" loopholes. |
| Behavior check | Tries the rule against many synthetic inputs to confirm it behaves predictably. |
| Memory hit | The system recognized this rule (or this ambiguity) from a prior run and reused that decision. |
| Reviewer ticket | A question the system raised that needs your judgement before it can proceed. |
| Lineage | A trail back to source rows, the rule body, and any human decisions that produced an output value. |
| Rule fingerprint | A short hash that uniquely identifies a rule body. Same fingerprint means the same rule has been seen before. |
| Question fingerprint | A short hash for an ambiguity. Same fingerprint means the same kind of question has been raised before. |
"""

GLOSSARY_HTML: str = """\
<dl>
  <dt><b>IDC (Importing Data Contract)</b></dt>
  <dd>The YAML file you upload that declares which new columns to derive
      and how. CliniTrace treats it as a contract between you and the
      pipeline.</dd>
  <dt><b>Import task</b></dt>
  <dd>One execution of the pipeline against a dataset and an IDC. Each
      task has its own folder under the Runs directory and may carry a
      reviewer-supplied name (e.g. <i>Phase 2 Trial &mdash; May 2026</i>).</dd>
  <dt><b>Rule</b></dt>
  <dd>A single instruction for deriving a new column from existing ones.
      Each rule has a kind (bucketing, value mapping, ...) and a body
      that parameterises it.</dd>
  <dt><b>Derived variable</b></dt>
  <dd>A column CliniTrace computes from the dataset using a rule.</dd>
  <dt><b>IDC Clarification</b></dt>
  <dd>A question the Spec Reviewer raises when a rule is ambiguous
      (e.g. the rationale mentions a value the rule body does not
      handle). Resolved by a reviewer; the answer is remembered for
      future tasks.</dd>
  <dt><b>Schema check</b></dt>
  <dd>A first pass that verifies the rule itself is well-formed
      (e.g. bucket boundaries make sense).</dd>
  <dt><b>Coverage check</b></dt>
  <dd>Confirms every possible input value has a defined output.
      No "and otherwise null" loopholes.</dd>
  <dt><b>Behaviour check</b></dt>
  <dd>Tries the rule against many synthetic inputs to confirm it
      behaves predictably.</dd>
  <dt><b>Rulebook hit (memory hit)</b></dt>
  <dd>CliniTrace recognised this rule body, or this kind of
      clarification, from a prior task and reused the validated
      result &mdash; no LLM call, no new reviewer ticket.</dd>
  <dt><b>Lineage</b></dt>
  <dd>A trail back from one output cell to its source rows, the rule
      body that produced it, and any reviewer decisions that
      applied.</dd>
  <dt><b>Body signature (rule fingerprint)</b></dt>
  <dd>A short hash that uniquely identifies a rule body. Same hash
      means the same rule &mdash; even across studies and target
      columns.</dd>
  <dt><b>Stub mode vs live mode</b></dt>
  <dd>Stub mode runs the pipeline without calling any LLM, using
      deterministic fixture responses (great for demos and CI). Live
      mode calls a real LLM via the configured backend (currently
      Ollama).</dd>
</dl>
"""


# --------------------------------------------------------------------------
# Tutorial
# --------------------------------------------------------------------------

TUTORIAL_HTML: str = """\
<h3>What CliniTrace does</h3>

<p>CliniTrace takes a clinical dataset (CSV, Parquet, or SQLite) and an
<b>Importing Data Contract (IDC)</b> &mdash; a small YAML file that
declares which new columns to derive and how. It produces an
analysis-ready dataset, a verification report, and a full audit trail.
Every value in the output can be traced back to the source rows, the
rule body that produced it, and any reviewer decisions that applied
along the way.</p>

<h3>The six agents</h3>

<p>The pipeline is split into six small agents, scheduled by an
Orchestrator. No agent calls another agent directly. Two are
LLM-backed; the rest are deterministic.</p>

<ul>
  <li><b>&#129302; Spec Reviewer (LLM)</b> reads each rule in your IDC.
      If something is ambiguous &mdash; e.g. the rationale mentions a
      value the rule body does not handle &mdash; it opens a
      clarification rather than guessing.</li>
  <li><b>&#129302; Code Generator (LLM)</b> produces the executable
      body for each rule. For rules CliniTrace has seen before, the
      Code Generator skips the LLM entirely and reuses the validated
      body from the IDC Rulebook.</li>
  <li><b>&#9881;&#65039; Verifier (deterministic)</b> runs three layers
      of checks per derivation: schema (is the rule well-formed?),
      coverage (does every possible input have a defined output?), and
      behaviour (does the rule behave predictably on many synthetic
      inputs?). Nothing is marked verified without the Verifier.</li>
  <li><b>&#9881;&#65039; Refiner (deterministic)</b> proposes fixes for
      Verifier failures and sends them back through the Verifier. The
      Refiner never bypasses verification.</li>
  <li><b>&#9881;&#65039; Auditor (deterministic)</b> writes the
      activity log, the per-row lineage records, and a plain-language
      run summary.</li>
  <li><b>&#9881;&#65039; Orchestrator (deterministic)</b> is the only
      component allowed to invoke other agents. It builds the
      dependency graph: a derived variable that depends on another
      derived variable will not run until its inputs exist and have
      passed verification.</li>
</ul>

<h3>Memory in two layers</h3>

<p>Short-term memory holds the current task's intermediate state. The
<b>IDC Rulebook</b> (long-term memory) remembers, across tasks,
validated rule bodies and prior reviewer decisions on ambiguous
specs &mdash; so a reviewer answers each clarification only once. The
Rulebook is how CliniTrace gets faster and more consistent the more
you use it.</p>

<p>If a derivation fails verification and refinement cannot fix it, the
task does not silently fall back to a partial answer. The affected
derivation is marked unresolved, the rest still ships, and the run
exits with a code that says "some derivations did not verify".</p>

<h3>Two ways to use CliniTrace</h3>

<p>Both entry points share the same backend and the same Rulebook.</p>

<h4>1. The web UI (this app) &mdash; <code>python -m clinitrace ui</code></h4>

<p>Best for interactive reviewers. The "New Import Task" tab walks you
through five steps:</p>

<ol>
  <li><b>Name &amp; upload.</b> Give the task a memorable name (e.g.
      <i>Phase 2 Trial &mdash; May 2026</i>), then drop a dataset
      (CSV, Parquet, or SQLite).</li>
  <li><b>Preview &amp; configure.</b> See the first 20 rows. Tweak
      CSV delimiter, header row, or encoding; pick a table if the
      file is SQLite.</li>
  <li><b>Choose IDC.</b> Upload your own YAML or pick the bundled
      demo. CliniTrace checks that every column the IDC needs is
      present in your dataset before you start.</li>
  <li><b>Run.</b> One button. The pipeline executes; if the Spec
      Reviewer raises clarifications, they appear on the "IDC
      Clarifications" tab.</li>
  <li><b>Results.</b> Output preview, metric cards (derivations
      verified, unresolved, clarifications opened, Rulebook hits),
      audit trail, and a download button for the analysis-ready
      dataset.</li>
</ol>

<h4>2. The batch CLI &mdash; <code>python -m clinitrace run ...</code></h4>

<p>Best for automation, CI, and headless demos:</p>

<pre>python -m clinitrace run \\
  --spec examples/demo_spec.yaml \\
  --data examples/demo_data.csv \\
  --out demo_out \\
  --replay examples/demo_resolutions.json</pre>

<p>The <code>--replay</code> flag points at a JSON file of
pre-recorded reviewer decisions, so a headless run never blocks on
clarifications. Omit it to require interactive answers via the
UI.</p>

<h3>The other tabs</h3>

<ul>
  <li><b>IDC Clarifications.</b> Open clarifications across all
      tasks. The default filter hides clean tasks so you focus on
      what actually needs your input. Each clarification shows the
      ambiguity, the suggested options, and a free-text reasoning
      box. Save your decision and the pipeline picks it up.</li>
  <li><b>Import Task History.</b> Browse past tasks. Four sub-tabs
      per task: <i>Summary</i> (plain-language report);
      <i>Checks performed</i> (one row per derivation with status,
      rule kind, revisions, agent chain); <i>Activity log</i> (every
      pipeline event, filterable by event type); <i>Output data</i>
      (the analysis-ready dataset, with lineage for any row).</li>
  <li><b>IDC Rulebook.</b> What CliniTrace remembers across tasks.
      Three sub-tabs: <i>Rules we&rsquo;ve seen before</i> (validated
      bodies, each with a plain-English summary and a
      <i>&#129514; Try it</i> sandbox to feed sample inputs);
      <i>Prior reviewer decisions</i>; and <i>Activity log</i>.</li>
  <li><b>Settings.</b> Display timezone, paths for runs and the
      Rulebook, and LLM configuration (stub vs live, backend, model,
      endpoint URL, timeout). Settings persist to
      <code>.clinitrace_settings.json</code> so they survive a
      restart.</li>
</ul>

<h3>Demo walk-through</h3>

<ol>
  <li>Launch the UI: <code>python -m clinitrace ui</code>.</li>
  <li>Pick <b>New Import Task</b>. Name it (e.g.
      <i>Demo</i>), upload <code>examples/demo_data.csv</code>,
      proceed through Preview, choose the bundled demo IDC, and
      click <b>Start task</b>.</li>
  <li>If this is your first run, the Spec Reviewer will flag the
      <code>RESPONSE_FLAG</code> rule &mdash; the rationale mentions
      <code>unknown</code> but the rule body has no handling for it.
      Switch to <b>IDC Clarifications</b>, pick an option (the
      pipeline suggests mapping <code>unknown</code> to
      <code>U</code>), write a short rationale, and save.</li>
  <li>Go back to the task on the <b>Results</b> step or open the
      <b>Import Task History</b>. The Summary will read
      "all derivations verified."</li>
  <li>Open the <b>IDC Rulebook</b>. You should now see two rule
      bodies under <i>Rules we&rsquo;ve seen before</i>
      (<code>AGE_GROUP</code> and <code>RESPONSE_FLAG</code>), one
      ambiguity resolution, and one feedback event.</li>
  <li>Start <b>another</b> task with the same data and IDC. The
      Rulebook is now warm: clarifications auto-resolve, the Code
      Generator skips the LLM, and the task finishes with zero
      reviewer input.</li>
</ol>

<h3>When something fails</h3>

<p>Open <b>Import Task History &rsaquo; Summary</b> for the affected
task &mdash; it tells you in plain language whether every derivation
passed. If one is unresolved, expand its issues under <i>Checks
performed</i>: the message comes from the layer that flagged it
(schema, coverage, or behaviour). If a clarification stays open and
never closes, check that you clicked Save and that the Runs folder
in Settings really points at the task you are looking at.</p>
"""
