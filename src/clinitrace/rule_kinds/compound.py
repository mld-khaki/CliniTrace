"""compound rule_kind: boolean combination of per-column predicates.

Body schema:
    conditions:  list of {column, op, value} predicates.
    combinator:  how to combine condition results ({and, or}).
    true_value:  output when the combined predicate is True.
    false_value: output when the combined predicate is False.
    null_handling: how to treat rows where the predicate's truth value is
                   undefined because one of its operands is null
                   ({null, false, true, error}).

Apply semantics:
    Each row of df is evaluated against each condition. Comparison operators
    (==, !=, >=, <=, >, <) follow standard Python semantics, with the
    important exception that NaN-vs-anything evaluates to *missing*, not
    False. The combinator then folds the per-condition truths:
      - AND: True iff all conditions True; False if any False; Missing otherwise.
      - OR:  True if any condition True; False iff all conditions False; Missing otherwise.
    Missing outcomes are routed through null_handling, which is the
    architectural slot for "what counts as in-population when a key value is
    unknown" — a clinical decision, not a code decision.

Use case: ANALYSIS_POP_FLAG. The canonical example is
    "age >= 18 AND response IS NOT NULL" → 'Y' else 'N'.
This rule_kind is deliberately not a general expression language: each
condition compares ONE column to ONE constant, the combinator is flat (no
nesting), and the output is a binary label. That keeps the rule body
auditable at a glance and the L2 coverage check tractable.

Why body-carried column refs: see duration.py module docstring.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from clinitrace.rule_kinds.errors import NullInputError


class CompoundOp(str, Enum):
    """Supported per-condition comparison operators."""

    EQ = "=="
    NE = "!="
    GE = ">="
    LE = "<="
    GT = ">"
    LT = "<"
    IS_NULL = "is_null"      # value field ignored
    NOT_NULL = "not_null"    # value field ignored
    IN = "in"                # value is a list


class CompoundCombinator(str, Enum):
    """How condition results are combined into the final row truth."""

    AND = "and"
    OR = "or"


class CompoundNullHandling(str, Enum):
    """How the rule treats rows where the combined truth value is undefined.

    'null'  : emit NaN (the rule has no opinion).
    'false' : treat undefined as False (default-exclude — common for
              ANALYSIS_POP_FLAG where uncertain rows should be excluded).
    'true'  : treat undefined as True (default-include — rare; available for
              completeness so the spec author can choose explicitly).
    'error' : raise NullInputError (catch-it-early posture).
    """

    NULL = "null"
    FALSE = "false"
    TRUE = "true"
    ERROR = "error"


class CompoundCondition(BaseModel):
    """One predicate: <column> <op> <value>."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    column: str = Field(..., min_length=1)
    op: CompoundOp
    value: Any = None  # Required for binary ops; ignored for is_null/not_null.


class CompoundBody(BaseModel):
    """L1 schema for the compound rule_kind.

    Construction-time invariants:
      - conditions list is non-empty (a zero-condition rule is meaningless).
      - true_value and false_value are non-empty strings (so the output
        column is always reviewer-readable; numerical labels can be written
        as "1"/"0" if the user really wants).
      - binary ops carry a non-null value; IS_NULL/NOT_NULL do not.
      - IN's value is a list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conditions: list[CompoundCondition] = Field(..., min_length=1)
    combinator: CompoundCombinator = CompoundCombinator.AND
    true_value: str = "Y"
    false_value: str = "N"
    null_handling: CompoundNullHandling = CompoundNullHandling.FALSE

    def model_post_init(self, _ctx: object) -> None:  # type: ignore[override]
        # Validate op/value consistency at construction time so a bad rule
        # body fails loud at CG time, not silently at apply time.
        for i, cond in enumerate(self.conditions):
            if cond.op in (CompoundOp.IS_NULL, CompoundOp.NOT_NULL):
                if cond.value is not None:
                    raise ValueError(
                        f"condition[{i}] op={cond.op.value!r} must not carry a value "
                        f"(got {cond.value!r})"
                    )
            elif cond.op == CompoundOp.IN:
                if not isinstance(cond.value, list):
                    raise ValueError(
                        f"condition[{i}] op='in' requires a list value "
                        f"(got {type(cond.value).__name__})"
                    )
            else:
                if cond.value is None:
                    raise ValueError(
                        f"condition[{i}] op={cond.op.value!r} requires a non-null value"
                    )


def _evaluate_condition(series: pd.Series, op: CompoundOp, value: Any) -> pd.Series:
    """Evaluate one condition against a column. Returns a Series of
    {True, False, pd.NA} per row (NA where the operand is null and the op
    is not is_null/not_null).
    """
    is_null = series.isna()

    if op == CompoundOp.IS_NULL:
        return is_null
    if op == CompoundOp.NOT_NULL:
        return ~is_null

    # For ordering ops, coerce to numeric so date strings / mixed-typed
    # series don't crash. errors='ignore' would mask real type bugs; we use
    # 'coerce' so a non-numeric cell becomes NaN and feeds null_handling.
    if op in (CompoundOp.GE, CompoundOp.LE, CompoundOp.GT, CompoundOp.LT):
        col = pd.to_numeric(series, errors="coerce")
        result_is_null = is_null | col.isna()
        if op == CompoundOp.GE:
            r = col >= value
        elif op == CompoundOp.LE:
            r = col <= value
        elif op == CompoundOp.GT:
            r = col > value
        else:
            r = col < value
        return r.where(~result_is_null, other=pd.NA).astype("boolean")

    if op == CompoundOp.IN:
        r = series.isin(value)
        return r.where(~is_null, other=pd.NA).astype("boolean")

    # EQ / NE: compare as strings if the column is object-dtype, else as-is.
    # This makes `response == 'responder'` work even when response is loaded
    # as object dtype with mixed nulls.
    if series.dtype == object:
        col = series.astype(str)
        cmp = str(value)
    else:
        col = series
        cmp = value
    if op == CompoundOp.EQ:
        r = col == cmp
    else:
        r = col != cmp
    return r.where(~is_null, other=pd.NA).astype("boolean")


def apply_compound(
    df: pd.DataFrame,
    target: str,
    source: str,  # noqa: ARG001 — unused; column refs live in body
    body: CompoundBody,
) -> pd.DataFrame:
    """Approved Python function for the compound rule_kind.

    Evaluates each condition, folds them with the combinator, routes
    undefined truth values through null_handling, and writes
    true_value/false_value to a new target column.

    Raises:
        KeyError: a required column is not present in df.
        NullInputError: a row has undefined truth and
            body.null_handling == CompoundNullHandling.ERROR.
    """
    for cond in body.conditions:
        if cond.column not in df.columns:
            raise KeyError(
                f"required column {cond.column!r} not found in DataFrame; "
                f"available columns: {list(df.columns)}"
            )

    truths = [
        _evaluate_condition(df[cond.column], cond.op, cond.value)
        for cond in body.conditions
    ]

    # Three-valued logic (Kleene) so AND/OR with NA produces sensible results.
    if body.combinator == CompoundCombinator.AND:
        # AND(NA, False) = False; AND(NA, True) = NA; AND(NA, NA) = NA.
        combined = truths[0]
        for t in truths[1:]:
            combined = combined & t
    else:
        # OR(NA, True) = True; OR(NA, False) = NA; OR(NA, NA) = NA.
        combined = truths[0]
        for t in truths[1:]:
            combined = combined | t

    is_undefined = combined.isna()

    if body.null_handling == CompoundNullHandling.ERROR and bool(is_undefined.any()):
        raise NullInputError(
            f"undefined truth value encountered under null_handling='error'; "
            f"{int(is_undefined.sum())} of {len(df)} rows have a null operand"
        )

    # Map combined truths to the output values, then patch undefined rows
    # per null_handling.
    # Use bool(v) rather than `v is True` — pandas-boolean / numpy-bool values
    # are not the Python singleton True, so identity-check would miss them.
    out = pd.Series(
        [body.true_value if bool(v) else body.false_value for v in combined.fillna(False)],
        index=df.index,
        dtype=object,
    )
    if body.null_handling == CompoundNullHandling.NULL:
        out = out.where(~is_undefined, other=None)
    elif body.null_handling == CompoundNullHandling.TRUE:
        out = out.where(~is_undefined, other=body.true_value)
    # FALSE handling is the default mapping above (False -> false_value), so
    # no extra patch is needed.

    return df.assign(**{target: out})
