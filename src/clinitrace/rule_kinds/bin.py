"""bin rule_kind: discretize a numeric column into named buckets.

Body schema:
    edges: list of interior boundary cut points (strictly increasing).
    labels: bucket names, one per resulting bin.
    null_handling: how null inputs are treated ({null, label, error}).
    null_label: the label used when null_handling == "label".

Half-open interval semantics (enforced by apply_bin):
    edges = [18, 65], labels = ["minor", "adult", "senior"]
    produces three half-open intervals:
        (-inf, 18)  -> "minor"
        [18, 65)    -> "adult"
        [65, +inf)  -> "senior"

Convention is half-open right (intervals are [a, b)). This matches clinical
intuition like "age 65+" meaning >= 65. To support the other convention
(a, b], a `closed` field would be added to BinBody; not in scope for now.

This module ships the L1 schema layer and the approved Python function
apply_bin. The L_p property suite arrives in slice 3.
"""

from __future__ import annotations

import math
from enum import Enum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinitrace.rule_kinds.errors import NullInputError


class BinNullHandling(str, Enum):
    """How apply_bin should treat null inputs."""

    NULL = "null"
    LABEL = "label"
    ERROR = "error"


class BinBody(BaseModel):
    """L1 schema for the bin rule_kind.

    Validation rules enforced at construction time:
      - edges is strictly increasing.
      - labels are unique.
      - len(labels) == len(edges) + 1.
      - null_label is set iff null_handling == LABEL.
      - Unknown fields are rejected (extra="forbid") so spec typos fail loud.

    Instances are frozen so they can be safely passed across agent boundaries.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edges: list[float] = Field(..., min_length=1)
    labels: list[str] = Field(..., min_length=2)
    null_handling: BinNullHandling = BinNullHandling.NULL
    null_label: str | None = None

    @field_validator("edges")
    @classmethod
    def edges_strictly_increasing(cls, v: list[float]) -> list[float]:
        for a, b in zip(v, v[1:], strict=False):
            if not a < b:
                raise ValueError(
                    f"edges must be strictly increasing; got {v}"
                )
        return v

    @field_validator("labels")
    @classmethod
    def labels_unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError(f"labels must be unique; got {v}")
        return v

    @model_validator(mode="after")
    def labels_match_edges(self) -> BinBody:
        expected = len(self.edges) + 1
        if len(self.labels) != expected:
            raise ValueError(
                f"len(labels) must equal len(edges) + 1; "
                f"got {len(self.labels)} labels and {len(self.edges)} edges "
                f"(expected {expected} labels)"
            )
        return self

    @model_validator(mode="after")
    def null_label_consistency(self) -> BinBody:
        if self.null_handling == BinNullHandling.LABEL:
            if self.null_label is None:
                raise ValueError(
                    "null_label must be set when null_handling == 'label'"
                )
        else:
            if self.null_label is not None:
                raise ValueError(
                    f"null_label must be None when null_handling != 'label' "
                    f"(got null_handling={self.null_handling.value!r}, "
                    f"null_label={self.null_label!r})"
                )
        return self


def apply_bin(
    df: pd.DataFrame,
    target: str,
    source: str,
    body: BinBody,
) -> pd.DataFrame:
    """Approved Python function for the bin rule_kind.

    Assigns each row of df[source] to the bin label whose half-open interval
    contains it, per body.edges and body.labels, and writes the result to a new
    column target on a copy of df.

    Half-open right semantics: an input value equal to an edge maps to the
    bucket above that edge (see module docstring for the worked example).

    Null inputs are handled per body.null_handling:
      - NULL: output is pandas NaN.
      - LABEL: output is body.null_label.
      - ERROR: NullInputError is raised before any value is computed.

    Raises:
        KeyError: source is not a column of df.
        NullInputError: a null input is encountered and
            body.null_handling == BinNullHandling.ERROR.
    """
    if source not in df.columns:
        raise KeyError(
            f"source column {source!r} not found in DataFrame; "
            f"available columns: {list(df.columns)}"
        )

    series = df[source]
    is_null = series.isna()

    if body.null_handling == BinNullHandling.ERROR and bool(is_null.any()):
        raise NullInputError(
            f"null input encountered in column {source!r} under "
            f"null_handling='error'; {int(is_null.sum())} of {len(series)} "
            f"rows are null"
        )

    full_edges = [-math.inf, *body.edges, math.inf]
    binned = pd.cut(
        series,
        bins=full_edges,
        labels=list(body.labels),
        right=False,
        include_lowest=True,
        ordered=False,
    )
    out = binned.astype(object)

    if body.null_handling == BinNullHandling.LABEL:
        assert body.null_label is not None
        out = out.where(~is_null, body.null_label)

    return df.assign(**{target: out})
