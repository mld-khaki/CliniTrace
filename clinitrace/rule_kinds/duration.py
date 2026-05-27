"""duration rule_kind: compute the time delta between two date columns.

Body schema:
    start_column: name of the column holding the earlier timestamp.
    end_column:   name of the column holding the later timestamp.
    unit:         days | weeks | months | years (months ~ 30 d, years ~ 365 d).
    null_handling: how to treat rows where either input is null
                   ({null, error}). 'null' emits NaN; 'error' raises.

Apply semantics:
    - Both columns are coerced to pandas datetime (errors=coerce).
    - delta = end - start, expressed in the requested unit, rounded to int
      when integer-valued, else float.
    - When either side is missing, output follows null_handling.
    - Negative durations are permitted (a clinical end-before-start situation
      is a data issue surfaced downstream, not a contract violation).

Why body-carried column refs (and not the apply() `source` parameter)?
    bin/flag are single-source: their `source` parameter names the one column
    they read. duration is multi-source — start AND end. Stuffing both into
    `source` would either re-invent a delimiter or break the apply signature
    for every other rule_kind. Carrying explicit `start_column` /
    `end_column` in the body is self-documenting and keeps the registry
    contract uniform.

Naming note: we register this as `duration` (matching _002 section 2.2's
five-rule plan) rather than `date_diff` — the latter is too narrow a label
for a rule that fronts a clinical concept like TREATMENT_DURATION.
"""

from __future__ import annotations

from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from clinitrace.rule_kinds.errors import NullInputError


class DurationUnit(StrEnum):
    """Output unit for the computed delta."""

    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"  # approximated as 30 days, see module docstring
    YEARS = "years"    # approximated as 365 days


class DurationNullHandling(StrEnum):
    """How apply_duration treats rows with at least one null endpoint."""

    NULL = "null"
    ERROR = "error"


# Conversion factors from days to the requested unit. Months / years use the
# standard "approximate" clinical-reporting denominators; if a more careful
# calendar-aware conversion is needed (e.g. ICH age in years), a future
# `calendar_aware: bool` field can extend the body without breaking existing
# rules.
_DAYS_PER_UNIT: dict[DurationUnit, float] = {
    DurationUnit.DAYS: 1.0,
    DurationUnit.WEEKS: 7.0,
    DurationUnit.MONTHS: 30.0,
    DurationUnit.YEARS: 365.0,
}


class DurationBody(BaseModel):
    """L1 schema for the duration rule_kind.

    Construction-time invariants:
      - start_column / end_column are non-empty and distinct.
      - unit is one of the declared enum members.
      - extra fields are rejected (extra="forbid").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_column: str = Field(..., min_length=1)
    end_column: str = Field(..., min_length=1)
    unit: DurationUnit = DurationUnit.DAYS
    null_handling: DurationNullHandling = DurationNullHandling.NULL

    def _validate_distinct(self) -> DurationBody:
        if self.start_column == self.end_column:
            raise ValueError(
                f"start_column and end_column must be different "
                f"(both are {self.start_column!r})"
            )
        return self

    def model_post_init(self, _ctx: object) -> None:  # type: ignore[override]
        # Pydantic v2 frozen-model-friendly equivalent of @model_validator.
        # Raises in __init__, so the body is never constructed in a bad state.
        if self.start_column == self.end_column:
            raise ValueError(
                f"start_column and end_column must be different "
                f"(both are {self.start_column!r})"
            )


def apply_duration(
    df: pd.DataFrame,
    target: str,
    source: str,  # noqa: ARG001 — unused; column refs live in body (see module docstring)
    body: DurationBody,
) -> pd.DataFrame:
    """Approved Python function for the duration rule_kind.

    Reads body.start_column and body.end_column from df, converts to datetime,
    computes (end - start) in body.unit, and writes the result to target.

    Raises:
        KeyError: a required column is not present in df.
        NullInputError: a row has a null endpoint and
            body.null_handling == DurationNullHandling.ERROR.
    """
    for col in (body.start_column, body.end_column):
        if col not in df.columns:
            raise KeyError(
                f"required column {col!r} not found in DataFrame; "
                f"available columns: {list(df.columns)}"
            )

    # errors="coerce" turns unparseable cells into NaT, which propagates as
    # null in the subsequent arithmetic. Combined with null_handling this
    # gives the caller one knob to govern both 'missing' and 'malformed'.
    start = pd.to_datetime(df[body.start_column], errors="coerce")
    end = pd.to_datetime(df[body.end_column], errors="coerce")

    is_null = start.isna() | end.isna()

    if body.null_handling == DurationNullHandling.ERROR and bool(is_null.any()):
        raise NullInputError(
            f"null/unparseable endpoint encountered under null_handling='error'; "
            f"{int(is_null.sum())} of {len(df)} rows have a missing start or end"
        )

    delta_days = (end - start).dt.total_seconds() / 86400.0
    divisor = _DAYS_PER_UNIT[body.unit]
    raw = delta_days / divisor

    # Where every value is an integer, present as int (clinical reports prefer
    # "60 days" over "60.0 days"). Where any fractional value exists, keep
    # float so precision is not silently dropped.
    nonnull = raw.dropna()
    if not nonnull.empty and bool((nonnull == nonnull.astype("int64")).all()):
        out = raw.where(~is_null).astype("Int64")
    else:
        out = raw.where(~is_null)

    return df.assign(**{target: out})
