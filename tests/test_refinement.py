"""Unit tests for the Refinement agent.

R is dead-code in the demo because L1's Pydantic validators catch every body
shape that L_p would later fail on. These tests exercise R in isolation,
demonstrating the patch dispatch + the escalate paths. The orchestrator-level
exercises of R + adaptive early-stop live in
`test_orchestrator_retry_loop.py`.
"""

from __future__ import annotations

import pytest

from clinitrace.agents import refinement as r
from clinitrace.rule_kinds.bin import BinBody
from clinitrace.rule_kinds.flag import FlagBody
from clinitrace.verification.findings import Finding, Layer, Severity


def _finding(rule_kind_id: str, derivation: str = "T") -> Finding:
    return Finding(
        layer=Layer.L_P,
        derivation=derivation,
        property_id=rule_kind_id,
        severity=Severity.ERROR,
        message="synthetic",
    )


def test_body_hash_stable_across_calls() -> None:
    body = BinBody(edges=[18, 65], labels=["m", "a", "s"])
    assert r.body_hash(body) == r.body_hash(body)
    assert r.body_hash(body) == r.body_hash(body.model_dump(mode="json"))


def test_body_hash_changes_with_content() -> None:
    a = BinBody(edges=[18, 65], labels=["m", "a", "s"])
    b = BinBody(edges=[18, 70], labels=["m", "a", "s"])
    assert r.body_hash(a) != r.body_hash(b)


def test_findings_signature_stable_across_orderings() -> None:
    f1 = _finding("P-bin-1", "X")
    f2 = _finding("P-bin-2", "X")
    assert r.findings_signature([f1, f2]) == r.findings_signature([f2, f1])


def test_findings_signature_differs_across_property_ids() -> None:
    sig_a = r.findings_signature([_finding("P-bin-1")])
    sig_b = r.findings_signature([_finding("P-bin-2")])
    assert sig_a != sig_b


def test_refine_no_findings_escalates() -> None:
    body = BinBody(edges=[18], labels=["lo", "hi"])
    out = r.refine(rule_kind="bin", body=body, findings=[])
    assert out.escalate
    assert "no findings" in out.reason


def test_refine_unrecognized_finding_escalates() -> None:
    body = BinBody(edges=[18], labels=["lo", "hi"])
    out = r.refine(
        rule_kind="bin",
        body=body,
        findings=[_finding("P-bin-1")],  # P-bin-1 has no _PATCH_RULES entry
    )
    assert out.escalate
    assert "no deterministic patch" in out.reason


def test_refine_applies_known_patch_for_bin_p2() -> None:
    # Pydantic forbids constructing a BinBody with null_handling=LABEL +
    # null_label=None, so we feed R the dict shape directly via a fake body.
    # Here we simulate the case where the body started with LABEL+null_label
    # and R applies the P-bin-2 patch ('null_handling' -> 'null'), which
    # requires clearing null_label to match the LABEL->NULL transition.
    body = BinBody(
        edges=[18],
        labels=["lo", "hi"],
        null_handling="label",
        null_label="missing",
    )
    out = r.refine(rule_kind="bin", body=body, findings=[_finding("P-bin-2")])
    # Patch sets null_handling='null' but leaves null_label set, which violates
    # BinBody's null_label_consistency invariant -> body fails to re-validate
    # -> escalate.
    assert out.escalate
    assert "did not validate" in out.reason


def test_refine_flag_p_flag_3_patches_unmapped_handling() -> None:
    body = FlagBody(
        map={"a": "1"},
        unmapped_handling="error",
    )
    out = r.refine(rule_kind="flag", body=body, findings=[_finding("P-flag-3")])
    assert not out.escalate
    assert out.revised_body is not None
    assert out.revised_body["unmapped_handling"] == "null"
    # The patched body must re-validate as a FlagBody.
    FlagBody.model_validate(out.revised_body)


def test_refine_does_not_validate_if_patched_body_is_invalid() -> None:
    # Construct a flag body with null_handling=VALUE (and null_value set).
    body = FlagBody(
        map={"a": "1"},
        null_handling="value",
        null_value="X",
    )
    # The P-flag-2 patch flips null_handling to "null" but leaves null_value
    # set, which violates FlagBody's null_value_consistency.
    out = r.refine(rule_kind="flag", body=body, findings=[_finding("P-flag-2")])
    assert out.escalate
    assert "did not validate" in out.reason


@pytest.mark.parametrize(
    "rule_kind, finding_id",
    [
        ("bin", "P-bin-99"),  # unknown property
        ("nonexistent_kind", "P-bin-2"),  # unknown rule_kind
    ],
)
def test_refine_unknown_rule_or_finding_escalates(
    rule_kind: str, finding_id: str
) -> None:
    body = BinBody(edges=[18], labels=["lo", "hi"])
    out = r.refine(rule_kind=rule_kind, body=body, findings=[_finding(finding_id)])
    assert out.escalate
