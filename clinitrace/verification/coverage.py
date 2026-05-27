"""L2 spec-coverage layer.

_002 section 6.1: "L2 spec-coverage: every value in the input domain has a
defined output. No implicit defaults."

For bin and flag, the L1 Pydantic validators already enforce explicit handling
for every domain partition (null_handling required, value_handling required
when value mode is selected, null_label required when label mode is selected).
L2 here is the explicit "no implicit defaults" assertion -- redundant with L1
for these rule_kinds, but architecturally separate so future rule_kinds
(especially `expression`, where the body alone does not bound the domain) can
land a real coverage check in this slot.

A failing L2 finding indicates a rule_body that L1 should not have accepted;
it surfaces as ERROR severity so the fail-closed pipeline halts the derivation
the same way an L1 or L_p failure would.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from clinitrace.rule_kinds.bin import BinBody, BinNullHandling
from clinitrace.rule_kinds.flag import FlagBody, FlagNullHandling, FlagUnmappedHandling
from clinitrace.verification.findings import Finding, Layer, Severity


def _err(target: str, pid: str, msg: str) -> Finding:
    return Finding(
        layer=Layer.L2,
        derivation=target,
        property_id=pid,
        severity=Severity.ERROR,
        message=msg,
    )


def _l2_bin(target: str, body: BinBody) -> list[Finding]:
    findings: list[Finding] = []
    # Every numeric value falls into some bin (edges cover the real line).
    # Null handling must be explicit.
    if body.null_handling not in BinNullHandling.__members__.values():
        findings.append(
            _err(target, "L2.bin.null_handling_explicit", "The rule does not say how to handle missing values.")
        )
    # If LABEL mode is chosen, null_label must be set (L1 enforces too).
    if body.null_handling == BinNullHandling.LABEL and body.null_label is None:
        findings.append(
            _err(
                target,
                "L2.bin.null_label_present",
                "When missing values are present, the rule should substitute a label, but no label is declared.",
            )
        )
    return findings


def _l2_flag(target: str, body: FlagBody) -> list[Finding]:
    findings: list[Finding] = []
    # null_handling must be explicit.
    if body.null_handling not in FlagNullHandling.__members__.values():
        findings.append(
            _err(target, "L2.flag.null_handling_explicit", "The rule does not say how to handle missing values.")
        )
    # unmapped_handling must be explicit. THIS is the canonical L2 check for
    # flag: a rule that does not declare unmapped behaviour would let an
    # unknown input silently default to null.
    if body.unmapped_handling not in FlagUnmappedHandling.__members__.values():
        findings.append(
            _err(
                target,
                "L2.flag.unmapped_handling_explicit",
                "The rule does not say what to do when an input is not one of the declared values (it would silently treat them as missing).",
            )
        )
    if (
        body.null_handling == FlagNullHandling.VALUE
        and body.null_value is None
    ):
        findings.append(
            _err(
                target,
                "L2.flag.null_value_present",
                "When missing values are present, the rule should substitute a value, but no value is declared.",
            )
        )
    if (
        body.unmapped_handling == FlagUnmappedHandling.VALUE
        and body.unmapped_value is None
    ):
        findings.append(
            _err(
                target,
                "L2.flag.unmapped_value_present",
                "When unmapped values are present, the rule should substitute a value, but no value is declared.",
            )
        )
    return findings


_L2_DISPATCH: dict[str, Callable[[str, BaseModel], list[Finding]]] = {
    "bin": _l2_bin,  # type: ignore[dict-item]
    "flag": _l2_flag,  # type: ignore[dict-item]
}


def run_l2(rule_kind: str, target: str, body: BaseModel) -> list[Finding]:
    """Run L2 for a typed body. Returns findings (empty if coverage holds).

    Rule_kinds with no registered L2 check return empty findings. New
    rule_kinds (expression, mapping) should add an entry to _L2_DISPATCH.
    """
    checker = _L2_DISPATCH.get(rule_kind)
    if checker is None:
        return []
    return checker(target, body)
