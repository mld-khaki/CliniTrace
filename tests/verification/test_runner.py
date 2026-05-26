"""Tests for the verification runner (L1 + L_p composition)."""

from __future__ import annotations

import pandas as pd

from clinitrace.rule_kinds.bin import BinBody
from clinitrace.rule_kinds.flag import FlagBody
from clinitrace.verification import verify_rule_instance


def test_bin_verdict_passes_for_clean_body() -> None:
    body = BinBody(edges=[18, 65], labels=["minor", "adult", "senior"])
    sample = pd.DataFrame({"age": [10, 30, 70]})
    verdict = verify_rule_instance(
        target="age_group", rule_kind="bin", body=body, source="age", sample=sample
    )
    assert verdict.passed
    assert verdict.findings == []


def test_flag_verdict_passes_for_clean_body() -> None:
    body = FlagBody(map={"responder": "Y", "non_responder": "N"})
    sample = pd.DataFrame({"response": ["responder", "non_responder"]})
    verdict = verify_rule_instance(
        target="response_flag",
        rule_kind="flag",
        body=body,
        source="response",
        sample=sample,
    )
    assert verdict.passed


def test_flag_verdict_passes_with_unmapped_handling_value() -> None:
    body = FlagBody(
        map={"responder": "Y", "non_responder": "N"},
        unmapped_handling="value",
        unmapped_value="U",
    )
    sample = pd.DataFrame({"response": ["responder", "non_responder", "unknown"]})
    verdict = verify_rule_instance(
        target="response_flag",
        rule_kind="flag",
        body=body,
        source="response",
        sample=sample,
    )
    assert verdict.passed


def test_unknown_rule_kind_fails_cleanly() -> None:
    # We can construct an arbitrary BaseModel and ask V about an unregistered
    # rule_kind name; V should refuse via KeyError from the registry.
    body = BinBody(edges=[0], labels=["lo", "hi"])
    sample = pd.DataFrame({"x": [-1, 1]})
    try:
        verify_rule_instance(
            target="t",
            rule_kind="nope",
            body=body,
            source="x",
            sample=sample,
        )
    except KeyError as exc:
        assert "unknown rule_kind" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")
