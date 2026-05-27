"""Interactive 'Try it' preview for IDC Rulebook entries.

Renders sample inputs next to each saved rule body so the reviewer can
feed values and see the rule's output. Uses the production apply_*
functions (clinitrace.rule_kinds) so the preview is identical to what
the pipeline would produce on a real dataset -- there is NO separate
re-implementation of the rule semantics in the UI layer.

Why this matters:
  - "Read the JSON and trust the description" is a heavy ask for a
    clinical reviewer. "Type 17, click Test, see 'minor'" is concrete.
  - Scores on PDF criteria 4 (HITL usability) and 7 (implementation
    quality / understandability).

UX design:
  - Inputs (number / text / select / checkbox) edit a *draft* state
    that lives in session_state under the widget keys.
  - A "Test" button is the explicit moment when the draft becomes
    *applied* state (stored under f'{key_prefix}_applied'). The rule
    runs against the applied state on every rerun.
  - If draft and applied differ, a yellow banner asks the user to
    click Test, so the input-vs-output mismatch is impossible to miss.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from clinitrace.rule_kinds.bin import BinBody, apply_bin
from clinitrace.rule_kinds.compound import CompoundBody, apply_compound
from clinitrace.rule_kinds.duration import DurationBody, apply_duration
from clinitrace.rule_kinds.flag import FlagBody, apply_flag
from clinitrace.rule_kinds.risk_score import RiskScoreBody, apply_risk_score

# ---------------------------------------------------------------------------
# Bin preview
# ---------------------------------------------------------------------------


def _render_bin_preview(body_dict: dict, key_prefix: str) -> None:
    try:
        body = BinBody.model_validate(body_dict)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not parse rule body for preview: {exc}")
        return

    draft_input_key = f"{key_prefix}_bin_input"
    draft_null_key = f"{key_prefix}_bin_null"
    applied_key = f"{key_prefix}_bin_applied"

    # Seed the draft session_state on first render so the widgets stay in
    # sync with whatever was last applied (or sensible defaults).
    st.session_state.setdefault(draft_input_key, 0.0)
    st.session_state.setdefault(draft_null_key, False)
    st.session_state.setdefault(applied_key, (0.0, False))

    cols = st.columns([1, 1, 2])
    with cols[0]:
        st.number_input(
            "Sample input value",
            step=1.0,
            key=draft_input_key,
            help="Type a number, then click **Test** to push it through.",
        )
        st.checkbox(
            "Try with null instead",
            key=draft_null_key,
            help="See how the rule handles a missing value.",
        )
        test_clicked = st.button(
            "▶ Test this input",
            key=f"{key_prefix}_bin_test",
            type="primary",
            use_container_width=True,
            help="Send the input above through the rule.",
        )

    draft_value = float(st.session_state[draft_input_key])
    draft_null = bool(st.session_state[draft_null_key])

    if test_clicked:
        st.session_state[applied_key] = (draft_value, draft_null)

    applied_value, applied_null = st.session_state[applied_key]

    # Yellow banner when the user has edited inputs but not clicked Test yet.
    if (draft_value, draft_null) != (applied_value, applied_null):
        with cols[0]:
            st.warning("⏳ Click **Test** to apply your changes.")

    sample_value = np.nan if applied_null else applied_value
    sample = pd.DataFrame({"value": pd.Series([sample_value], dtype="float64")})
    try:
        result = apply_bin(sample, target="result", source="value", body=body)
        output = result["result"].iloc[0]
    except Exception as exc:  # noqa: BLE001
        with cols[1]:
            st.error(f"Rule raised an error: {exc}")
        return

    # Compose the "why" caption from the APPLIED input, not the draft.
    if applied_null:
        path = "missing value → null handling"
    else:
        bucket_idx = len(body.labels) - 1
        for i, edge in enumerate(body.edges):
            if applied_value < edge:
                bucket_idx = i
                break
        bucket_name = body.labels[bucket_idx]
        if bucket_idx == 0:
            interval = f"below {body.edges[0]}"
        elif bucket_idx == len(body.labels) - 1:
            interval = f"{body.edges[bucket_idx - 1]} and above"
        else:
            interval = (
                f"{body.edges[bucket_idx - 1]} to under {body.edges[bucket_idx]}"
            )
        path = f"`{applied_value}` falls in **{interval}** → **{bucket_name}**"

    with cols[1]:
        st.markdown("**Input sent to rule:**")
        if applied_null:
            st.code("null", language=None)
        else:
            st.code(repr(applied_value), language=None)

        st.markdown("**Output:**")
        if pd.isna(output):
            st.code("null (NaN)", language=None)
        else:
            st.success(str(output))

        st.caption(f"Why: {path}")

    with cols[2]:
        st.markdown(
            "**Bucket table** &nbsp; (arrow marks the bucket this value lands in)"
        )
        rows = []
        for i, label in enumerate(body.labels):
            if i == 0:
                interval = f"below {body.edges[0]}"
            elif i == len(body.labels) - 1:
                interval = f"{body.edges[i - 1]} and above"
            else:
                interval = f"{body.edges[i - 1]} to under {body.edges[i]}"
            in_bucket = (
                (not applied_null)
                and (not pd.isna(output))
                and (str(output) == label)
            )
            rows.append({
                "Bucket": ("→ " if in_bucket else "  ") + label,
                "Range": interval,
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Flag preview
# ---------------------------------------------------------------------------


def _render_flag_preview(body_dict: dict, key_prefix: str) -> None:
    try:
        body = FlagBody.model_validate(body_dict)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not parse rule body for preview: {exc}")
        return

    mapping = body.map or {}
    sample_options = list(mapping.keys()) + ["(other)", "(null)"]

    draft_choice_key = f"{key_prefix}_flag_choice"
    draft_custom_key = f"{key_prefix}_flag_custom"
    applied_key = f"{key_prefix}_flag_applied"

    # Seed sensible defaults if first render.
    st.session_state.setdefault(draft_choice_key, sample_options[0])
    # Important: do NOT pass `value=` to text_input -- it would override
    # what the user typed on subsequent reruns. We only seed once here.
    st.session_state.setdefault(draft_custom_key, "")
    st.session_state.setdefault(applied_key, ("__init__", None))

    cols = st.columns([1, 1, 2])
    with cols[0]:
        st.selectbox(
            "Sample input value",
            options=sample_options,
            key=draft_choice_key,
            help=(
                "Pick a value to send through the rule. Choose '(other)' "
                "to test an unmapped input, or '(null)' for missing."
            ),
        )
        if st.session_state[draft_choice_key] == "(other)":
            st.text_input(
                "Custom value",
                key=draft_custom_key,
                placeholder="type a value, e.g. unknown",
                help=(
                    "Free-text input. After typing, click **Test** to "
                    "send it through the rule."
                ),
            )
        test_clicked = st.button(
            "▶ Test this input",
            key=f"{key_prefix}_flag_test",
            type="primary",
            use_container_width=True,
            help="Send the input above through the rule.",
        )

    # Derive what the rule should run against, given current draft state.
    draft_choice = st.session_state[draft_choice_key]
    draft_custom = st.session_state[draft_custom_key]
    if draft_choice == "(other)":
        draft_marker = ("other", draft_custom)
    elif draft_choice == "(null)":
        draft_marker = ("null", None)
    else:
        draft_marker = ("mapped", draft_choice)

    if test_clicked or st.session_state[applied_key] == ("__init__", None):
        st.session_state[applied_key] = (draft_marker[0], draft_marker[1])
    applied_marker, applied_payload = st.session_state[applied_key]

    if applied_marker == "__init__":
        # First render with no Test click yet: show neutral state.
        with cols[1]:
            st.info(
                "Click **Test** to run the rule against your selected input."
            )
        return

    # Yellow banner when the user has edited inputs but not clicked Test yet.
    if draft_marker != (applied_marker, applied_payload):
        with cols[0]:
            st.warning("⏳ Click **Test** to apply your changes.")

    # Reconstruct the applied sample_value from the applied marker.
    if applied_marker == "mapped":
        applied_value: object = applied_payload
    elif applied_marker == "null":
        applied_value = None
    else:  # "other"
        applied_value = applied_payload if applied_payload != "" else None

    sample = pd.DataFrame({"value": [applied_value]})
    try:
        result = apply_flag(sample, target="result", source="value", body=body)
        output = result["result"].iloc[0]
    except Exception as exc:  # noqa: BLE001
        with cols[1]:
            st.error(f"Rule raised an error: {exc}")
        return

    # Why caption.
    if applied_value is None:
        path = "missing value → null handling"
    elif applied_value in mapping:
        path = (
            f"matched mapping `{applied_value}` → "
            f"`{mapping[applied_value]}`"
        )
    else:
        uh = body.unmapped_handling.value
        if uh == "value":
            path = (
                f"`{applied_value}` is not in the mapping → unmapped fallback "
                f"`{body.unmapped_value}`"
            )
        elif uh == "null":
            path = f"`{applied_value}` is not in the mapping → null"
        elif uh == "error":
            path = f"`{applied_value}` is not in the mapping → raises an error"
        else:
            path = f"`{applied_value}` is not in the mapping → {uh}"

    with cols[1]:
        st.markdown("**Input sent to rule:**")
        if applied_value is None:
            st.code("null", language=None)
        else:
            st.code(repr(applied_value), language=None)

        st.markdown("**Output:**")
        if pd.isna(output):
            st.code("null (NaN)", language=None)
        else:
            st.success(str(output))

        st.caption(f"Why: {path}")

    with cols[2]:
        st.markdown(
            "**Mapping table** &nbsp; (arrow marks the path taken)"
        )
        rows = []
        for k, v in mapping.items():
            rows.append({
                "Input": ("→ " if k == applied_value else "  ") + str(k),
                "Output": str(v),
            })
        unmapped_label = ""
        if body.unmapped_handling.value == "value":
            unmapped_label = str(body.unmapped_value)
        elif body.unmapped_handling.value == "null":
            unmapped_label = "null"
        elif body.unmapped_handling.value == "error":
            unmapped_label = "error"
        in_unmapped = (
            applied_value is not None and applied_value not in mapping
        )
        rows.append({
            "Input": ("→ " if in_unmapped else "  ") + "(any other value)",
            "Output": unmapped_label or "—",
        })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Duration preview
# ---------------------------------------------------------------------------


def _render_duration_preview(body_dict: dict, key_prefix: str) -> None:
    """Try-it for duration rules. Two date inputs → numeric delta."""
    try:
        body = DurationBody.model_validate(body_dict)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not parse rule body for preview: {exc}")
        return

    start_key = f"{key_prefix}_dur_start"
    end_key = f"{key_prefix}_dur_end"
    null_key = f"{key_prefix}_dur_null"
    applied_key = f"{key_prefix}_dur_applied"

    today = pd.Timestamp.today().normalize().date()
    st.session_state.setdefault(start_key, today)
    st.session_state.setdefault(end_key, today)
    st.session_state.setdefault(null_key, False)
    st.session_state.setdefault(applied_key, None)

    cols = st.columns([1, 1, 2])
    with cols[0]:
        st.date_input(
            f"`{body.start_column}` (start date)",
            key=start_key,
            help=f"Earlier of the two endpoints. Mapped to body field `{body.start_column}`.",
        )
        st.date_input(
            f"`{body.end_column}` (end date)",
            key=end_key,
            help=f"Later of the two endpoints. Mapped to body field `{body.end_column}`.",
        )
        st.checkbox(
            "Try with one endpoint missing",
            key=null_key,
            help="Drops the end date to NaT to see how the rule handles a partial row.",
        )
        test_clicked = st.button(
            "▶ Test this input",
            key=f"{key_prefix}_dur_test",
            type="primary",
            use_container_width=True,
        )

    draft_marker = (
        st.session_state[start_key],
        st.session_state[end_key],
        st.session_state[null_key],
    )
    if test_clicked or st.session_state[applied_key] is None:
        st.session_state[applied_key] = draft_marker
    applied_marker = st.session_state[applied_key]

    if applied_marker is None:
        with cols[1]:
            st.info("Click **Test** to compute the delta.")
        return

    if draft_marker != applied_marker:
        with cols[0]:
            st.warning("⏳ Click **Test** to apply your changes.")

    applied_start, applied_end, applied_null = applied_marker

    # Build a one-row DataFrame using the body's expected column names.
    sample = pd.DataFrame({
        body.start_column: [pd.Timestamp(applied_start)],
        body.end_column:   [pd.NaT if applied_null else pd.Timestamp(applied_end)],
    })
    try:
        result = apply_duration(
            sample, target="result", source=body.start_column, body=body
        )
        output = result["result"].iloc[0]
    except Exception as exc:  # noqa: BLE001
        with cols[1]:
            st.error(f"Rule raised an error: {exc}")
        return

    with cols[1]:
        st.markdown("**Inputs sent to rule:**")
        st.code(
            f"{body.start_column} = {applied_start}\n"
            f"{body.end_column}   = {'null' if applied_null else applied_end}",
            language=None,
        )
        st.markdown("**Output:**")
        if pd.isna(output):
            st.code("null (NaN)", language=None)
        else:
            st.success(f"{output} {body.unit.value}")

        if applied_null:
            path = "one endpoint is missing → null handling"
        else:
            delta_days = (pd.Timestamp(applied_end) - pd.Timestamp(applied_start)).days
            path = (
                f"{applied_end} − {applied_start} = {delta_days} days "
                f"→ {output} {body.unit.value}"
            )
        st.caption(f"Why: {path}")

    with cols[2]:
        st.markdown("**Rule recipe**")
        rows = [
            {"Field": "start_column",  "Value": body.start_column},
            {"Field": "end_column",    "Value": body.end_column},
            {"Field": "unit",          "Value": body.unit.value},
            {"Field": "null_handling", "Value": body.null_handling.value},
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Compound preview
# ---------------------------------------------------------------------------


def _render_compound_preview(body_dict: dict, key_prefix: str) -> None:
    """Try-it for compound rules. One number input per referenced column."""
    try:
        body = CompoundBody.model_validate(body_dict)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not parse rule body for preview: {exc}")
        return

    # Collect distinct columns referenced by any condition. We render one
    # input widget per column so the user sees the row they're testing.
    referenced_cols: list[str] = []
    for cond in body.conditions:
        if cond.column not in referenced_cols:
            referenced_cols.append(cond.column)

    null_key = f"{key_prefix}_cmp_null"
    applied_key = f"{key_prefix}_cmp_applied"
    st.session_state.setdefault(null_key, False)
    st.session_state.setdefault(applied_key, None)

    # Per-column widgets. We use text inputs (one universal widget) so the
    # preview works for numeric AND categorical columns without forcing the
    # user to pick a type — the rule itself does the coercion.
    col_keys = {c: f"{key_prefix}_cmp_col_{c}" for c in referenced_cols}
    for c in referenced_cols:
        st.session_state.setdefault(col_keys[c], "")

    cols = st.columns([1, 1, 2])
    with cols[0]:
        for c in referenced_cols:
            st.text_input(
                f"`{c}` value",
                key=col_keys[c],
                placeholder="e.g. 25 or responder",
                help=f"Sample value for column `{c}`.",
            )
        st.checkbox(
            "Treat all inputs as null",
            key=null_key,
            help="Send NaN for every column to test the null-handling branch.",
        )
        test_clicked = st.button(
            "▶ Test this input",
            key=f"{key_prefix}_cmp_test",
            type="primary",
            use_container_width=True,
        )

    draft_marker = tuple(st.session_state[col_keys[c]] for c in referenced_cols) + (
        st.session_state[null_key],
    )
    if test_clicked or st.session_state[applied_key] is None:
        st.session_state[applied_key] = draft_marker
    applied_marker = st.session_state[applied_key]

    if applied_marker is None:
        with cols[1]:
            st.info("Click **Test** to evaluate the predicate.")
        return

    if draft_marker != applied_marker:
        with cols[0]:
            st.warning("⏳ Click **Test** to apply your changes.")

    applied_null = applied_marker[-1]
    applied_values = applied_marker[:-1]

    # Build one-row DataFrame. Coerce numeric-looking strings to numbers so
    # `age >= 18` works as the user expects.
    def _coerce(raw: str) -> object:
        if applied_null or raw == "":
            return None
        try:
            f = float(raw)
            return int(f) if f.is_integer() else f
        except ValueError:
            return raw

    sample = pd.DataFrame({
        c: [_coerce(applied_values[i])] for i, c in enumerate(referenced_cols)
    })
    try:
        result = apply_compound(
            sample, target="result", source=referenced_cols[0], body=body
        )
        output = result["result"].iloc[0]
    except Exception as exc:  # noqa: BLE001
        with cols[1]:
            st.error(f"Rule raised an error: {exc}")
        return

    with cols[1]:
        st.markdown("**Inputs sent to rule:**")
        st.code(
            "\n".join(
                f"{c} = {'null' if (applied_null or applied_values[i] == '') else applied_values[i]}"
                for i, c in enumerate(referenced_cols)
            ),
            language=None,
        )
        st.markdown("**Output:**")
        if output is None or (isinstance(output, float) and pd.isna(output)):
            st.code("null", language=None)
        else:
            st.success(str(output))

        # Why caption — show each condition's truth and the fold.
        per_cond_text: list[str] = []
        for cond, raw in zip(
            body.conditions, [_coerce(applied_values[referenced_cols.index(c.column)])
                              for c in body.conditions], strict=False,
        ):
            per_cond_text.append(
                f"`{cond.column} {cond.op.value} {cond.value if cond.value is not None else ''}`"
                f" with value `{raw}`"
            )
        st.caption(
            f"Why: {body.combinator.value.upper()} over " +
            " · ".join(per_cond_text)
        )

    with cols[2]:
        st.markdown("**Rule conditions**")
        rows = [
            {"Column": c.column, "Op": c.op.value, "Value": "" if c.value is None else str(c.value)}
            for c in body.conditions
        ]
        rows.append({"Column": f"combinator: {body.combinator.value}", "Op": "", "Value": ""})
        rows.append({"Column": f"true → {body.true_value} / false → {body.false_value}", "Op": "", "Value": ""})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Risk-score preview
# ---------------------------------------------------------------------------


def _render_risk_score_preview(body_dict: dict, key_prefix: str) -> None:
    """Try-it for risk_score rules. Per-column inputs; shows which tier wins."""
    try:
        body = RiskScoreBody.model_validate(body_dict)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not parse rule body for preview: {exc}")
        return

    referenced_cols: list[str] = []
    for tier in body.tiers:
        for cond in tier.conditions:
            if cond.column not in referenced_cols:
                referenced_cols.append(cond.column)

    applied_key = f"{key_prefix}_risk_applied"
    st.session_state.setdefault(applied_key, None)
    col_keys = {c: f"{key_prefix}_risk_col_{c}" for c in referenced_cols}
    for c in referenced_cols:
        st.session_state.setdefault(col_keys[c], "")

    cols = st.columns([1, 1, 2])
    with cols[0]:
        for c in referenced_cols:
            st.text_input(
                f"`{c}` value",
                key=col_keys[c],
                placeholder="e.g. 70 or 80",
                help=f"Sample value for column `{c}`.",
            )
        test_clicked = st.button(
            "▶ Test this input",
            key=f"{key_prefix}_risk_test",
            type="primary",
            use_container_width=True,
        )

    draft_marker = tuple(st.session_state[col_keys[c]] for c in referenced_cols)
    if test_clicked or st.session_state[applied_key] is None:
        st.session_state[applied_key] = draft_marker
    applied_marker = st.session_state[applied_key]

    if applied_marker is None:
        with cols[1]:
            st.info("Click **Test** to find the winning tier.")
        return

    if draft_marker != applied_marker:
        with cols[0]:
            st.warning("⏳ Click **Test** to apply your changes.")

    def _coerce(raw: str) -> object:
        if raw == "":
            return None
        try:
            f = float(raw)
            return int(f) if f.is_integer() else f
        except ValueError:
            return raw

    sample = pd.DataFrame({
        c: [_coerce(applied_marker[i])] for i, c in enumerate(referenced_cols)
    })
    try:
        result = apply_risk_score(
            sample, target="result", source=referenced_cols[0], body=body
        )
        output = result["result"].iloc[0]
    except Exception as exc:  # noqa: BLE001
        with cols[1]:
            st.error(f"Rule raised an error: {exc}")
        return

    # Determine which tier won so we can mark it in the recipe table.
    winning_tier = None
    if output is not None and not (isinstance(output, float) and pd.isna(output)):
        for tier in body.tiers:
            if tier.label == output:
                winning_tier = tier.label
                break

    with cols[1]:
        st.markdown("**Inputs sent to rule:**")
        st.code(
            "\n".join(
                f"{c} = {'null' if applied_marker[i] == '' else applied_marker[i]}"
                for i, c in enumerate(referenced_cols)
            ),
            language=None,
        )
        st.markdown("**Output:**")
        if output is None or (isinstance(output, float) and pd.isna(output)):
            st.code("null", language=None)
        else:
            st.success(str(output))

        if winning_tier is not None:
            path = f"first matching tier: **{winning_tier}**"
        elif output == body.fallback_label:
            path = f"no tier matched → fallback **{body.fallback_label}**"
        else:
            path = "no tier resolved → null handling"
        st.caption(f"Why: {path}")

    with cols[2]:
        st.markdown(
            "**Risk ladder** &nbsp; (arrow marks the winning tier)"
        )
        rows = []
        for tier in body.tiers:
            cond_str = f" {tier.combinator.value.upper()} ".join(
                f"{c.column} {c.op.value} {c.value if c.value is not None else ''}".strip()
                for c in tier.conditions
            )
            rows.append({
                "Tier": ("→ " if tier.label == winning_tier else "  ") + tier.label,
                "Condition": cond_str,
            })
        rows.append({
            "Tier": ("→ " if (winning_tier is None and output == body.fallback_label) else "  ")
                    + f"(fallback) {body.fallback_label}",
            "Condition": "no tier above matched",
        })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


_RENDERERS = {
    "bin": _render_bin_preview,
    "flag": _render_flag_preview,
    "duration": _render_duration_preview,
    "compound": _render_compound_preview,
    "risk_score": _render_risk_score_preview,
}


def render(rule_kind: str, body_dict: dict, key_prefix: str) -> None:
    """Render the appropriate 'Try it' preview for a given rule kind.
    Unknown rule kinds fall back to an info message so the page never
    breaks if a new rule kind is added without a preview yet.
    """
    fn = _RENDERERS.get(rule_kind)
    if fn is None:
        st.info(
            f"Interactive preview not yet available for `{rule_kind}` rules. "
            "See the raw rule body above for full details."
        )
        return
    fn(body_dict, key_prefix=key_prefix)
