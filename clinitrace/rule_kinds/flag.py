"""flag rule_kind: map a categorical column through an explicit dictionary.

Body schema:
    map: dict from declared input keys (strings) to declared output values.
    null_handling: how null inputs are treated ({null, value, error}).
    null_value: the value emitted when null_handling == "value".
    unmapped_handling: how inputs that are not declared keys are treated.
    unmapped_value: the value emitted when unmapped_handling == "value".

Apply semantics:
    - Every declared key produces its declared value (P-flag-1).
    - Null inputs follow null_handling explicitly (P-flag-2).
    - Inputs that are neither null nor declared follow unmapped_handling (P-flag-3).

There is no implicit default-to-null. The locked decision in _002 is that every
domain partition (declared / unmapped / null) is named in the rule body.

This module ships the L1 schema layer (FlagBody) and the approved Python
function apply_flag. The L_p property suite lives in
clinitrace.verification.properties.flag.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinitrace.rule_kinds.errors import NullInputError


class FlagNullHandling(str, Enum):
    """How apply_flag should treat null inputs."""

    NULL = "null"
    VALUE = "value"
    ERROR = "error"


class FlagUnmappedHandling(str, Enum):
    """How apply_flag should treat inputs that are not declared keys."""

    NULL = "null"
    VALUE = "value"
    ERROR = "error"


class FlagBody(BaseModel):
    """L1 schema for the flag rule_kind.

    Construction-time invariants:
      - map is non-empty.
      - null_value is set iff null_handling == VALUE.
      - unmapped_value is set iff unmapped_handling == VALUE.
      - extra fields are rejected (extra="forbid").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    map: dict[str, str] = Field(..., min_length=1)
    null_handling: FlagNullHandling = FlagNullHandling.NULL
    null_value: str | None = None
    unmapped_handling: FlagUnmappedHandling = FlagUnmappedHandling.NULL
    unmapped_value: str | None = None

    @model_validator(mode="after")
    def null_value_consistency(self) -> FlagBody:
        if self.null_handling == FlagNullHandling.VALUE:
            if self.null_value is None:
                raise ValueError(
                    "null_value must be set when null_handling == 'value'"
                )
        else:
            if self.null_value is not None:
                raise ValueError(
                    f"null_value must be None when null_handling != 'value' "
                    f"(got null_handling={self.null_handling.value!r}, "
                    f"null_value={self.null_value!r})"
                )
        return self

    @model_validator(mode="after")
    def unmapped_value_consistency(self) -> FlagBody:
        if self.unmapped_handling == FlagUnmappedHandling.VALUE:
            if self.unmapped_value is None:
                raise ValueError(
                    "unmapped_value must be set when unmapped_handling == 'value'"
                )
        else:
            if self.unmapped_value is not None:
                raise ValueError(
                    f"unmapped_value must be None when unmapped_handling != 'value' "
                    f"(got unmapped_handling={self.unmapped_handling.value!r}, "
                    f"unmapped_value={self.unmapped_value!r})"
                )
        return self


def apply_flag(
    df: pd.DataFrame,
    target: str,
    source: str,
    body: FlagBody,
) -> pd.DataFrame:
    """Approved Python function for the flag rule_kind.

    Looks up each row's source value in body.map and writes the result to target
    on a copy of df. Null inputs and unmapped inputs each follow their declared
    handling rule. No implicit defaulting.

    Raises:
        KeyError: source is not a column of df.
        NullInputError: a null input is encountered and
            body.null_handling == FlagNullHandling.ERROR.
        ValueError: an unmapped input is encountered and
            body.unmapped_handling == FlagUnmappedHandling.ERROR.
    """
    if source not in df.columns:
        raise KeyError(
            f"source column {source!r} not found in DataFrame; "
            f"available columns: {list(df.columns)}"
        )

    series = df[source]
    is_null = series.isna()
    declared_keys = set(body.map.keys())

    if body.null_handling == FlagNullHandling.ERROR and bool(is_null.any()):
        raise NullInputError(
            f"null input encountered in column {source!r} under "
            f"null_handling='error'; {int(is_null.sum())} of {len(series)} "
            f"rows are null"
        )

    if body.unmapped_handling == FlagUnmappedHandling.ERROR:
        observed = set(series.dropna().astype(str).unique())
        unmapped = observed - declared_keys
        if unmapped:
            raise ValueError(
                f"unmapped input(s) encountered in column {source!r} under "
                f"unmapped_handling='error': {sorted(unmapped)!r} "
                f"(declared keys: {sorted(declared_keys)!r})"
            )

    def _lookup(value: object) -> object:
        if pd.isna(value):
            if body.null_handling == FlagNullHandling.NULL:
                return None
            if body.null_handling == FlagNullHandling.VALUE:
                return body.null_value
            raise AssertionError("error null_handling should have raised earlier")
        key = str(value)
        if key in body.map:
            return body.map[key]
        if body.unmapped_handling == FlagUnmappedHandling.NULL:
            return None
        if body.unmapped_handling == FlagUnmappedHandling.VALUE:
            return body.unmapped_value
        raise AssertionError("error unmapped_handling should have raised earlier")

    out = series.map(_lookup).astype(object)
    return df.assign(**{target: out})
