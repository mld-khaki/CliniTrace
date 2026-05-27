"""Finding and Verdict data structures emitted by V.

These are part of the public contract: R consumes findings to propose a
revision, A writes them into the audit trail, and the run summary surfaces
them grouped by derivation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Layer(StrEnum):
    """Which V layer produced a finding."""

    L1 = "L1"
    L2 = "L2"
    L_P = "L_p"


class Severity(StrEnum):
    """Severity of a finding. Any non-INFO finding fails the verdict."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Finding(BaseModel):
    """One verification finding.

    layer: which V layer produced this finding.
    derivation: target column name (which derivation this finding is about).
    property_id: identifier of the specific check (e.g. "P-bin-1") or layer
        check name (e.g. "L1.body_validation").
    severity: see Severity.
    message: human-readable explanation.
    sample: representative failing inputs/outputs (small, JSON-serializable).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: Layer
    derivation: str
    property_id: str
    severity: Severity
    message: str
    sample: dict[str, Any] = Field(default_factory=dict)


class Verdict(BaseModel):
    """V's terminal verdict for a single derivation.

    passed: True iff no Finding has severity >= ERROR.
    findings: every finding produced across L1 / L2 / L_p for this derivation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    derivation: str
    passed: bool
    findings: list[Finding] = Field(default_factory=list)

    @classmethod
    def from_findings(cls, derivation: str, findings: list[Finding]) -> Verdict:
        passed = not any(f.severity == Severity.ERROR for f in findings)
        return cls(derivation=derivation, passed=passed, findings=findings)
