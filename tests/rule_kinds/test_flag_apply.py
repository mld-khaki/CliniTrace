"""Behavior tests for apply_flag."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from clinitrace.rule_kinds.errors import NullInputError
from clinitrace.rule_kinds.flag import FlagBody, apply_flag


def test_declared_keys_map_through() -> None:
    df = pd.DataFrame({"response": ["responder", "non_responder", "responder"]})
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    out = apply_flag(df, target="flag", source="response", body=body)
    assert list(out["flag"]) == ["Y", "N", "Y"]


def test_null_handling_null_propagates() -> None:
    df = pd.DataFrame({"response": ["responder", None, "non_responder"]}, dtype=object)
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    out = apply_flag(df, target="flag", source="response", body=body)
    assert out["flag"].iloc[0] == "Y"
    assert pd.isna(out["flag"].iloc[1])
    assert out["flag"].iloc[2] == "N"


def test_null_handling_value_substitutes() -> None:
    df = pd.DataFrame({"response": ["responder", None]}, dtype=object)
    body = FlagBody(
        map={"responder": "Y"},
        null_handling="value",
        null_value="MISSING",
    )
    out = apply_flag(df, target="flag", source="response", body=body)
    assert list(out["flag"]) == ["Y", "MISSING"]


def test_null_handling_error_raises_only_when_null_present() -> None:
    body = FlagBody(map={"a": "1"}, null_handling="error")
    df_clean = pd.DataFrame({"x": ["a", "a"]})
    out = apply_flag(df_clean, target="f", source="x", body=body)
    assert list(out["f"]) == ["1", "1"]

    df_with_null = pd.DataFrame({"x": ["a", None]}, dtype=object)
    with pytest.raises(NullInputError):
        apply_flag(df_with_null, target="f", source="x", body=body)


def test_unmapped_handling_null() -> None:
    df = pd.DataFrame({"response": ["responder", "unknown"]})
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    out = apply_flag(df, target="flag", source="response", body=body)
    assert out["flag"].iloc[0] == "Y"
    assert pd.isna(out["flag"].iloc[1])


def test_unmapped_handling_value() -> None:
    df = pd.DataFrame({"response": ["responder", "unknown"]})
    body = FlagBody(
        map={"responder": "Y", "non_responder": "N"},
        unmapped_handling="value",
        unmapped_value="U",
    )
    out = apply_flag(df, target="flag", source="response", body=body)
    assert list(out["flag"]) == ["Y", "U"]


def test_unmapped_handling_error() -> None:
    df = pd.DataFrame({"response": ["responder", "unknown"]})
    body = FlagBody(
        map={"responder": "Y", "non_responder": "N"},
        unmapped_handling="error",
    )
    with pytest.raises(ValueError):
        apply_flag(df, target="flag", source="response", body=body)


def test_missing_source_column_raises() -> None:
    df = pd.DataFrame({"other": ["a"]})
    body = FlagBody(map={"a": "1"})
    with pytest.raises(KeyError):
        apply_flag(df, target="f", source="response", body=body)


def test_input_dataframe_not_mutated() -> None:
    df = pd.DataFrame({"response": ["responder"]})
    df_before = df.copy()
    body = FlagBody(map={"responder": "Y"})
    _ = apply_flag(df, target="flag", source="response", body=body)
    pd.testing.assert_frame_equal(df, df_before)


def test_empty_dataframe_returns_empty_target() -> None:
    df = pd.DataFrame({"response": pd.Series([], dtype=object)})
    body = FlagBody(map={"a": "1"})
    out = apply_flag(df, target="flag", source="response", body=body)
    assert "flag" in out.columns
    assert len(out) == 0


def test_idempotent_under_repeated_application() -> None:
    df = pd.DataFrame({"response": ["responder", "non_responder", None]}, dtype=object)
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    a = apply_flag(df, target="f1", source="response", body=body)
    b = apply_flag(a, target="f2", source="response", body=body)
    for col in ("f1", "f2"):
        assert b[col].iloc[0] == "Y"
        assert b[col].iloc[1] == "N"
        assert pd.isna(b[col].iloc[2])
    _ = math  # keep import path consistent with bin tests
