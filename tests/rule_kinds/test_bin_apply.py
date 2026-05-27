"""Handwritten unit tests for apply_bin.

Slice 2 of the rule_kind library. Property tests (Hypothesis) land in slice 3.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from clinitrace.rule_kinds.bin import BinBody, apply_bin
from clinitrace.rule_kinds.errors import NullInputError

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_three_bucket_age_binning() -> None:
    df = pd.DataFrame({"age": [10, 30, 50, 70, 90]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["minor", "adult", "adult", "senior", "senior"]


def test_single_edge_sign_split() -> None:
    df = pd.DataFrame({"x": [-2.5, -0.0001, 0, 0.0001, 100]})
    body = BinBody(edges=[0], labels=["neg", "non_neg"])
    out = apply_bin(df, target="sign", source="x", body=body)
    assert list(out["sign"]) == ["neg", "neg", "non_neg", "non_neg", "non_neg"]


# ---------------------------------------------------------------------------
# Boundary semantics: half-open right ([a, b))
# ---------------------------------------------------------------------------


def test_value_equal_to_edge_maps_to_upper_bucket() -> None:
    """edge 18 -> value 18 in 'adult', not 'minor'."""
    df = pd.DataFrame({"age": [17.9999, 18.0, 18.0001]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["minor", "adult", "adult"]


def test_value_at_last_edge_maps_to_top_bucket() -> None:
    df = pd.DataFrame({"age": [64.9999, 65.0, 65.0001]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["adult", "senior", "senior"]


# ---------------------------------------------------------------------------
# Extremes
# ---------------------------------------------------------------------------


def test_value_far_below_first_edge() -> None:
    df = pd.DataFrame({"x": [-1e9, -1e6, -1.0]})
    body = BinBody(edges=[0], labels=["neg", "non_neg"])
    out = apply_bin(df, target="sign", source="x", body=body)
    assert list(out["sign"]) == ["neg", "neg", "neg"]


def test_value_far_above_last_edge() -> None:
    df = pd.DataFrame({"x": [1e6, 1e9, 1e15]})
    body = BinBody(edges=[0], labels=["neg", "non_neg"])
    out = apply_bin(df, target="sign", source="x", body=body)
    assert list(out["sign"]) == ["non_neg", "non_neg", "non_neg"]


# ---------------------------------------------------------------------------
# null_handling modes
# ---------------------------------------------------------------------------


def test_null_handling_null_propagates() -> None:
    df = pd.DataFrame({"age": [10.0, math.nan, 70.0]})
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="null",
    )
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert out["age_group"].iloc[0] == "minor"
    assert pd.isna(out["age_group"].iloc[1])
    assert out["age_group"].iloc[2] == "senior"


def test_null_handling_label_substitutes() -> None:
    df = pd.DataFrame({"age": [10.0, math.nan, 70.0]})
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="label",
        null_label="unknown_age",
    )
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["minor", "unknown_age", "senior"]


def test_null_handling_error_raises() -> None:
    df = pd.DataFrame({"age": [10.0, math.nan, 70.0]})
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="error",
    )
    with pytest.raises(NullInputError) as excinfo:
        apply_bin(df, target="age_group", source="age", body=body)
    assert "null input encountered" in str(excinfo.value)
    assert "1 of 3 rows are null" in str(excinfo.value)


def test_null_handling_error_does_not_raise_on_clean_input() -> None:
    df = pd.DataFrame({"age": [10.0, 30.0, 70.0]})
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="error",
    )
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["minor", "adult", "senior"]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_source_column_raises_keyerror() -> None:
    df = pd.DataFrame({"weight": [60, 70]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    with pytest.raises(KeyError) as excinfo:
        apply_bin(df, target="age_group", source="age", body=body)
    assert "age" in str(excinfo.value)
    assert "weight" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Functional guarantees
# ---------------------------------------------------------------------------


def test_input_dataframe_not_mutated() -> None:
    df = pd.DataFrame({"age": [10, 30, 70]})
    df_before = df.copy()
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    _ = apply_bin(df, target="age_group", source="age", body=body)
    pd.testing.assert_frame_equal(df, df_before)
    assert "age_group" not in df.columns


def test_idempotent_when_applied_twice_with_distinct_targets() -> None:
    """apply_bin twice with the same body and source gives the same result."""
    df = pd.DataFrame({"age": [10, 30, 50, 70, 90]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    first = apply_bin(df, target="g1", source="age", body=body)
    second = apply_bin(first, target="g2", source="age", body=body)
    assert list(second["g1"]) == list(second["g2"])


def test_empty_dataframe_returns_empty_target_column() -> None:
    df = pd.DataFrame({"age": pd.Series([], dtype=float)})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert "age_group" in out.columns
    assert len(out) == 0


def test_all_null_under_label_mode() -> None:
    df = pd.DataFrame({"age": [math.nan, math.nan, math.nan]})
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="label",
        null_label="unknown_age",
    )
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["unknown_age"] * 3


def test_output_uses_object_dtype_not_categorical() -> None:
    """Downstream code shouldn't need to know about pd.Categorical."""
    df = pd.DataFrame({"age": [10, 30, 70]})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert out["age_group"].dtype == object


def test_target_column_overwrites_existing() -> None:
    """If target already exists, it is replaced; original column is gone."""
    df = pd.DataFrame({"age": [10, 30, 70], "age_group": ["wrong"] * 3})
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    out = apply_bin(df, target="age_group", source="age", body=body)
    assert list(out["age_group"]) == ["minor", "adult", "senior"]


# numpy import is used implicitly via pandas NaN; keep the symbol to confirm
# the import path stays clean if the test module is read top-to-bottom.
_ = np
