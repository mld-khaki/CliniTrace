"""L1 validation tests for FlagBody."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinitrace.rule_kinds.flag import (
    FlagBody,
    FlagNullHandling,
    FlagUnmappedHandling,
)


def test_minimal_valid_body() -> None:
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    assert body.null_handling == FlagNullHandling.NULL
    assert body.unmapped_handling == FlagUnmappedHandling.NULL
    assert body.null_value is None
    assert body.unmapped_value is None


def test_explicit_value_modes() -> None:
    body = FlagBody(
        map={"a": "1"},
        null_handling="value",
        null_value="MISSING",
        unmapped_handling="value",
        unmapped_value="OTHER",
    )
    assert body.null_value == "MISSING"
    assert body.unmapped_value == "OTHER"


def test_rejects_empty_map() -> None:
    with pytest.raises(ValidationError):
        FlagBody(map={})


def test_rejects_null_value_set_under_null_mode() -> None:
    with pytest.raises(ValidationError) as exc:
        FlagBody(map={"a": "1"}, null_handling="null", null_value="X")
    assert "null_value must be None" in str(exc.value)


def test_rejects_null_value_missing_under_value_mode() -> None:
    with pytest.raises(ValidationError) as exc:
        FlagBody(map={"a": "1"}, null_handling="value")
    assert "null_value must be set" in str(exc.value)


def test_rejects_unmapped_value_set_under_null_mode() -> None:
    with pytest.raises(ValidationError) as exc:
        FlagBody(map={"a": "1"}, unmapped_handling="null", unmapped_value="X")
    assert "unmapped_value must be None" in str(exc.value)


def test_rejects_unmapped_value_missing_under_value_mode() -> None:
    with pytest.raises(ValidationError) as exc:
        FlagBody(map={"a": "1"}, unmapped_handling="value")
    assert "unmapped_value must be set" in str(exc.value)


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        FlagBody(map={"a": "1"}, extra_thing=True)


def test_instance_is_frozen() -> None:
    body = FlagBody(map={"a": "1"})
    with pytest.raises(ValidationError):
        body.map = {"b": "2"}  # type: ignore[misc]
