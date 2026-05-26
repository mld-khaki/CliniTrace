"""Handwritten L1 validation tests for BinBody.

Slice 1 of the rule_kind library. Property tests (Hypothesis) land in slice 3.
"""

import pytest
from pydantic import ValidationError

from clinitrace.rule_kinds.bin import BinBody, BinNullHandling


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def test_valid_two_edge_three_label() -> None:
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    assert body.edges == [18.0, 65.0]
    assert body.labels == ["minor", "adult", "senior"]
    assert body.null_handling == BinNullHandling.NULL
    assert body.null_label is None


def test_valid_single_edge_two_label() -> None:
    body = BinBody(edges=[0], labels=["negative", "non_negative"])
    assert len(body.labels) == 2
    assert len(body.edges) == 1


def test_valid_label_mode_with_null_label() -> None:
    body = BinBody(
        edges=[18, 65],
        labels=["minor", "adult", "senior"],
        null_handling="label",
        null_label="unknown_age",
    )
    assert body.null_handling == BinNullHandling.LABEL
    assert body.null_label == "unknown_age"


def test_valid_error_mode() -> None:
    body = BinBody(
        edges=[18],
        labels=["below", "above"],
        null_handling="error",
    )
    assert body.null_handling == BinNullHandling.ERROR
    assert body.null_label is None


# ---------------------------------------------------------------------------
# Negative: structural mismatches
# ---------------------------------------------------------------------------


def test_rejects_label_count_too_few() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18, 65], labels=["a", "b"])
    assert "len(labels) must equal len(edges) + 1" in str(excinfo.value)


def test_rejects_label_count_too_many() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18], labels=["a", "b", "c"])
    assert "len(labels) must equal len(edges) + 1" in str(excinfo.value)


def test_rejects_empty_edges() -> None:
    with pytest.raises(ValidationError):
        BinBody(edges=[], labels=["only_one"])


# ---------------------------------------------------------------------------
# Negative: edge ordering
# ---------------------------------------------------------------------------


def test_rejects_decreasing_edges() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[65, 18], labels=["a", "b", "c"])
    assert "strictly increasing" in str(excinfo.value)


def test_rejects_equal_edges() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18, 18, 65], labels=["a", "b", "c", "d"])
    assert "strictly increasing" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Negative: label uniqueness
# ---------------------------------------------------------------------------


def test_rejects_duplicate_labels() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18, 65], labels=["minor", "adult", "minor"])
    assert "labels must be unique" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Negative: null_handling consistency
# ---------------------------------------------------------------------------


def test_rejects_label_mode_without_null_label() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18], labels=["a", "b"], null_handling="label")
    assert "null_label must be set" in str(excinfo.value)


def test_rejects_null_label_under_null_mode() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(
            edges=[18],
            labels=["a", "b"],
            null_handling="null",
            null_label="missing",
        )
    assert "null_label must be None" in str(excinfo.value)


def test_rejects_null_label_under_error_mode() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(
            edges=[18],
            labels=["a", "b"],
            null_handling="error",
            null_label="missing",
        )
    assert "null_label must be None" in str(excinfo.value)


def test_rejects_invalid_null_handling_value() -> None:
    with pytest.raises(ValidationError):
        BinBody(edges=[18], labels=["a", "b"], null_handling="propagate")


# ---------------------------------------------------------------------------
# Negative: extra fields + immutability
# ---------------------------------------------------------------------------


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BinBody(edges=[18], labels=["a", "b"], null_handeling="null")
    assert "Extra inputs are not permitted" in str(excinfo.value) or "extra" in str(
        excinfo.value
    ).lower()


def test_instance_is_frozen() -> None:
    body = BinBody(edges=[18], labels=["a", "b"])
    with pytest.raises(ValidationError):
        body.edges = [99]  # type: ignore[misc]
