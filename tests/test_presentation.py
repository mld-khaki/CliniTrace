"""Tests for the presentation (humanization) layer.

These tests are part of slice H1 of the humanization pass. They guard two
things:

  1. Every internal identifier we currently use in code has a label here.
     A missing label is a regression (UI shows the raw dev string).
  2. The helpers fall back gracefully on unknown inputs.

When adding a new layer / ticket kind / event type / property ID, add it
to presentation.py *and* (where relevant) extend the coverage assertions
below.
"""

from __future__ import annotations

import pytest

from clinitrace.presentation import (
    EVENT_TYPE_LABELS,
    GLOSSARY,
    LAYER_LABELS,
    PROPERTY_LABELS,
    RULE_KIND_LABELS,
    SEVERITY_LABELS,
    TICKET_KIND_LABELS,
    TICKET_KIND_LEAD,
    humanize_event,
    humanize_layer,
    humanize_property,
    humanize_rule_kind,
    humanize_severity,
    humanize_ticket_kind,
    ticket_lead_in,
)


# ---------------------------------------------------------------------------
# Coverage: every dictionary has the expected internal keys
# ---------------------------------------------------------------------------


def test_layer_labels_cover_all_three_layers() -> None:
    assert set(LAYER_LABELS.keys()) == {"L1", "L2", "L_p"}


def test_ticket_kinds_cover_three_first_class_nodes() -> None:
    expected = {"ambiguity", "approval", "triage"}
    assert set(TICKET_KIND_LABELS.keys()) == expected
    assert set(TICKET_KIND_LEAD.keys()) == expected


def test_event_type_labels_cover_known_audit_events() -> None:
    # Every event_type currently emitted by Audit.log() in the codebase.
    # When a new event_type is introduced, add it both to the code site
    # and here, so this test fails loudly if a label is forgotten.
    known_events = {
        "run_start",
        "sr_complete",
        "dag_planned",
        "dag_plan_failed",
        "dataset_check_failed",
        "cg_complete",
        "v_complete",
        "r_complete",
        "r_budget_exhausted",
        "r_early_stop",
        "apply_complete",
        "derivation_skipped",
        "hitl_open",
        "hitl_resolved",
        "hitl_auto_resolved",
        "ltm_write",
        "run_complete",
        "dataset_format_fallback",
    }
    missing = known_events - set(EVENT_TYPE_LABELS.keys())
    assert not missing, f"event types without a label: {sorted(missing)}"


def test_property_labels_cover_two_shipped_rule_kinds() -> None:
    # bin ships 4 properties, flag ships 5 (per property_test_contracts.md).
    bin_ids = {f"P-bin-{i}" for i in range(1, 5)}
    flag_ids = {f"P-flag-{i}" for i in range(1, 6)}
    missing = (bin_ids | flag_ids) - set(PROPERTY_LABELS.keys())
    assert not missing, f"property IDs without a label: {sorted(missing)}"


def test_severity_labels_cover_three_levels() -> None:
    assert set(SEVERITY_LABELS.keys()) == {"error", "warning", "info"}


# ---------------------------------------------------------------------------
# Fallbacks: unknown inputs return readable defaults
# ---------------------------------------------------------------------------


def test_humanize_layer_falls_back_to_input() -> None:
    assert humanize_layer("L99") == "L99"


def test_humanize_ticket_kind_falls_back_to_input() -> None:
    assert humanize_ticket_kind("unknown_kind") == "unknown_kind"


def test_ticket_lead_in_falls_back_to_generic_sentence() -> None:
    lead = ticket_lead_in("unknown_kind")
    assert "input" in lead.lower() or "rule" in lead.lower()


def test_humanize_event_falls_back_to_titlecase() -> None:
    # Known event: explicit label.
    assert humanize_event("run_start") == "Run started"
    # Unknown event: snake_case becomes Title Case.
    assert humanize_event("future_event_kind") == "Future event kind"


def test_humanize_property_falls_back_to_input() -> None:
    assert humanize_property("P-unknown-99") == "P-unknown-99"


def test_humanize_severity_falls_back_to_input() -> None:
    assert humanize_severity("catastrophic") == "catastrophic"


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "Rule",
        "Derived variable",
        "Schema check",
        "Coverage check",
        "Behavior check",
        "Memory hit",
        "Reviewer ticket",
        "Lineage",
    ],
)
def test_glossary_includes_key_term(term: str) -> None:
    assert term in GLOSSARY


def test_glossary_is_markdown_table_shaped() -> None:
    # Header row + separator + at least 8 entry rows.
    lines = [ln for ln in GLOSSARY.splitlines() if ln.strip()]
    assert lines[0].startswith("| Term"), f"unexpected header: {lines[0]!r}"
    assert lines[1].startswith("| ---"), f"unexpected separator: {lines[1]!r}"
    assert len(lines) >= 10  # header + separator + 8 entries



def test_rule_kind_labels_cover_five_rule_kinds() -> None:
    expected = {"bin", "flag", "duration", "expression", "mapping"}
    missing = expected - set(RULE_KIND_LABELS.keys())
    assert not missing, f"rule_kinds without a label: {sorted(missing)}"


def test_humanize_rule_kind_falls_back_to_input() -> None:
    assert humanize_rule_kind("custom_kind") == "custom_kind"


def test_humanize_rule_kind_known_value() -> None:
    assert humanize_rule_kind("bin") == "Bucketing"
    assert humanize_rule_kind("flag") == "Value mapping"


# ---------------------------------------------------------------------------
# ASCII-only discipline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label_dict",
    [LAYER_LABELS, TICKET_KIND_LABELS, TICKET_KIND_LEAD, EVENT_TYPE_LABELS,
     PROPERTY_LABELS, SEVERITY_LABELS, RULE_KIND_LABELS],
)
def test_all_label_strings_are_ascii(label_dict: dict[str, str]) -> None:
    for key, value in label_dict.items():
        try:
            value.encode("ascii")
        except UnicodeEncodeError as exc:
            pytest.fail(
                f"label for {key!r} contains non-ASCII char: {value!r} ({exc})"
            )


def test_glossary_is_ascii() -> None:
    try:
        GLOSSARY.encode("ascii")
    except UnicodeEncodeError as exc:
        pytest.fail(f"GLOSSARY contains non-ASCII: {exc}")


# ---------------------------------------------------------------------------
# NaN / None / non-string safety (Round 3 regression guard)
# ---------------------------------------------------------------------------
#
# Streamlit builds dataframes from heterogeneous audit_trail.jsonl events;
# pandas fills missing fields with NaN (a float). Every humanizer used inside
# `_humanize_df` must return non-string inputs unchanged or pandas .map(...)
# crashes with "AttributeError: 'float' object has no attribute 'replace'".


import math  # noqa: E402

from clinitrace.presentation import (
    humanize_ambiguity_class,
    humanize_column,
    humanize_event,
    humanize_option,
    humanize_status,
    short_fingerprint,
)


_HUMANIZERS_USED_IN_DATAFRAME_MAP = [
    humanize_event,
    humanize_option,
    humanize_ambiguity_class,
    humanize_column,
    humanize_status,
    humanize_rule_kind,
    humanize_ticket_kind,
    short_fingerprint,
]


@pytest.mark.parametrize("fn", _HUMANIZERS_USED_IN_DATAFRAME_MAP)
def test_humanizer_passes_through_nan(fn) -> None:
    """NaN must round-trip unchanged (it is still NaN, by identity of !=).

    This is the actual production bug Milad hit: pandas .map(fn) over an
    audit_trail column containing some rows without the field crashes if the
    fallback path calls .replace() on the NaN.
    """
    nan = float("nan")
    result = fn(nan)
    assert isinstance(result, float) and math.isnan(result), (
        f"{fn.__name__}({nan!r}) returned {result!r}; expected NaN unchanged"
    )


@pytest.mark.parametrize("fn", _HUMANIZERS_USED_IN_DATAFRAME_MAP)
def test_humanizer_passes_through_non_string(fn) -> None:
    """Ints, None, and other non-string inputs should also pass through."""
    # short_fingerprint(None) is special: documented to return "(none)".
    if fn is short_fingerprint:
        assert fn(None) == "(none)"
    else:
        assert fn(None) is None
    # Ints pass through everywhere (pandas can produce them in numeric cols).
    assert fn(42) == 42


def test_humanizer_happy_path_still_works() -> None:
    """Lock that adding the type guard did not break the dict-hit path."""
    assert humanize_ambiguity_class("missing_logic") == (
        "The rule is missing logic the spec did not provide"
    )
    assert humanize_event("hitl_open") == "Reviewer question opened"
    assert (
        humanize_option("flag_unknown_as_U")
        == "Map unknown values to a special flag 'U'"
    )
    assert humanize_status("verified") == "Verified"
    assert humanize_column("event_type") == "Activity"
    # And the fallback (snake_case -> Title Case) for unknown strings.
    assert humanize_event("totally_new_event_type") == "Totally new event type"


# ---------------------------------------------------------------------------
# Collision-safe column humanization (Round 3 regression guard)
# ---------------------------------------------------------------------------
#
# pandas DataFrame.rename(columns=...) will produce duplicate column names if
# multiple raw columns map to the same human label. pyarrow then refuses to
# serialize the DataFrame with "ValueError: Duplicate column names found".
# humanize_columns must therefore be collision-safe.


from clinitrace.presentation import humanize_columns  # noqa: E402


def test_humanize_columns_no_duplicates_on_real_audit_trail() -> None:
    """The full set of columns produced by a real audit_trail.jsonl must yield
    unique reviewer labels. This was the production bug Milad hit: source_mode
    and llm_mode both mapped to 'AI mode' and pyarrow rejected the DataFrame.
    """
    cols = [
        "event_type", "llm_mode", "run_id", "spec_version", "ts",
        "event_id", "options_offered", "target", "ticket_kind",
        "chosen_option", "resolved_by", "signature", "table",
        "findings", "execution_order", "body_signature", "confidence",
        "ltm_hit", "outcome", "reason", "rule_kind", "source_mode",
        "source_model", "iteration", "n_findings", "passed",
        "derivations_unresolved", "derivations_verified", "ltm_writes",
        "ambiguity_class", "ambiguity_signature", "auto_resolved",
        "body_patch",
    ]
    rename = humanize_columns(cols)
    labels = list(rename.values())
    assert len(labels) == len(set(labels)), (
        f"duplicate labels: "
        f"{sorted([lbl for lbl in labels if labels.count(lbl) > 1])}"
    )


def test_humanize_columns_disambiguates_mode_keys() -> None:
    """The two mode-related fields are semantically different and should
    have distinct reviewer labels.
    """
    rename = humanize_columns(["llm_mode", "source_mode", "source_model"])
    # llm_mode is the per-run configuration ("stub" or "live" for the whole
    # run). source_mode is per-agent-call (was THIS LLM call done with the
    # stub or live?).
    assert rename["llm_mode"] != rename["source_mode"]
    assert rename["source_model"] != rename["source_mode"]
    assert len(set(rename.values())) == 3


def test_humanize_columns_suffixes_synthetic_collisions() -> None:
    """If COLUMN_LABELS is ever extended in a way that introduces a collision,
    the helper must still produce unique output names by suffixing duplicates
    with the raw key in parentheses.
    """
    from clinitrace.presentation import COLUMN_LABELS

    fakes = {
        "fake_one": "TestLabel",
        "fake_two": "TestLabel",
        "fake_three": "TestLabel",
    }
    # Save and restore so other tests are not affected.
    saved = {k: COLUMN_LABELS.get(k) for k in fakes}
    COLUMN_LABELS.update(fakes)
    try:
        rename = humanize_columns(["fake_one", "fake_two", "fake_three"])
        labels = list(rename.values())
        assert len(labels) == len(set(labels))
        # The FIRST occurrence keeps the plain label; subsequent ones get
        # suffixed with the raw key.
        assert rename["fake_one"] == "TestLabel"
        assert rename["fake_two"] == "TestLabel (fake_two)"
        assert rename["fake_three"] == "TestLabel (fake_three)"
    finally:
        for k, v in saved.items():
            if v is None:
                COLUMN_LABELS.pop(k, None)
            else:
                COLUMN_LABELS[k] = v


def test_humanize_columns_preserves_raw_keys_as_input() -> None:
    """Sanity: every input raw key shows up exactly once in the output."""
    cols = ["event_type", "ts", "target"]
    rename = humanize_columns(cols)
    assert set(rename.keys()) == set(cols)


# ---------------------------------------------------------------------------
# LTM-cell humanization (Round 3.2 regression guard)
# ---------------------------------------------------------------------------


from clinitrace.presentation import (  # noqa: E402
    humanize_event_id,
    humanize_timestamp,
    summarize_options,
    summarize_resolution,
)


def test_humanize_timestamp_iso_with_offset() -> None:
    assert humanize_timestamp("2026-05-22T20:32:25.944584+00:00") == (
        "May 22, 2026, 8:32 PM UTC"
    )


def test_humanize_timestamp_iso_with_z() -> None:
    assert humanize_timestamp("2026-05-22T20:32:25Z") == (
        "May 22, 2026, 8:32 PM UTC"
    )


def test_humanize_timestamp_returns_garbage_unchanged() -> None:
    assert humanize_timestamp("not a date") == "not a date"


def test_humanize_timestamp_nan_safe() -> None:
    nan = float("nan")
    result = humanize_timestamp(nan)
    assert isinstance(result, float) and math.isnan(result)


def test_humanize_event_id_strips_prefix_and_truncates() -> None:
    assert humanize_event_id("evt-381f3b7a4dd6") == "381f3b7a"


def test_humanize_event_id_passes_through_short_form() -> None:
    # Already-short id without the evt- prefix.
    assert humanize_event_id("abc123") == "abc123"


def test_humanize_event_id_nan_safe() -> None:
    nan = float("nan")
    result = humanize_event_id(nan)
    assert isinstance(result, float) and math.isnan(result)


def test_summarize_resolution_raw_key_humanized() -> None:
    import json
    blob = json.dumps({
        "body_patch": {},
        "chosen_option": "flag_unknown_as_U",
        "free_text_rationale": "",
    })
    assert summarize_resolution(blob) == (
        "Map unknown values to a special flag 'U'"
    )


def test_summarize_resolution_plain_english_preserved() -> None:
    """When chosen_option is already plain English (free text from a reviewer
    or older demo data), it must NOT be capitalize()-d -- that would lowercase
    real proper nouns like 'U'."""
    import json
    blob = json.dumps({
        "body_patch": {},
        "chosen_option": "Map unknown to a special flag such as 'U'",
        "free_text_rationale": "",
    })
    assert summarize_resolution(blob) == (
        "Map unknown to a special flag such as 'U'"
    )


def test_summarize_resolution_garbage_passes_through() -> None:
    assert summarize_resolution("not json") == "not json"


def test_summarize_resolution_nan_safe() -> None:
    nan = float("nan")
    result = summarize_resolution(nan)
    assert isinstance(result, float) and math.isnan(result)


def test_summarize_options_dict_form_with_raw_keys() -> None:
    import json
    blob = json.dumps({"options": ["flag_unknown_as_U", "raise_on_unmapped"]})
    assert summarize_options(blob) == (
        "Map unknown values to a special flag 'U'; "
        "Exclude unknown values from the output"
    )


def test_summarize_options_list_form() -> None:
    import json
    blob = json.dumps(["treat_unmapped_as_null"])
    assert summarize_options(blob) == "Map unknown values to blank (null)"


def test_summarize_options_nan_safe() -> None:
    nan = float("nan")
    result = summarize_options(nan)
    assert isinstance(result, float) and math.isnan(result)
