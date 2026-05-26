"""V's top-level entry point. Composes L1 + L2 + L_p per _002 section 6.1.

L1: Pydantic-roundtrip schema check (type, range, null-consistency, extra-
    fields-forbidden) AND apply executes without raising on the run sample.
    The Pydantic check is expected to have already happened in CG; we re-
    validate here as defense in depth, since a typed-but-tampered instance
    is the canonical drift mode.

L2: spec-coverage. Every value in the input domain has a defined output --
    no implicit defaults. For bin/flag this is structurally enforced by L1
    Pydantic validators; the explicit L2 layer asserts the same property
    so the architectural slot is verifiable and future rule_kinds with
    weaker bodies (expression) get a real coverage check.

L_p: per-rule_kind property suite (3-5 invariants per kind) exercised
     against deterministic synthetic batches.

V is fully deterministic. No LLM in the verdict.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ValidationError

from clinitrace.rule_kinds import get as get_rule_kind
from clinitrace.verification.coverage import run_l2
from clinitrace.verification.findings import Finding, Layer, Severity, Verdict
from clinitrace.verification.properties import run_suite


def _summarize_pydantic_errors(errs: list[dict]) -> str:
    """Turn Pydantic's error list into a plain-language summary."""
    if not errs:
        return "the body did not pass validation."
    parts = []
    for err in errs[:3]:  # cap to 3 to keep the message readable
        loc = ".".join(str(x) for x in err.get("loc", ()) if x)
        msg = err.get("msg", "")
        if loc:
            parts.append(f"'{loc}' -> {msg}")
        else:
            parts.append(msg)
    suffix = "" if len(errs) <= 3 else f" (and {len(errs) - 3} more)"
    return "; ".join(parts) + suffix

def _l1_findings(
    target: str,
    rule_kind: str,
    body: BaseModel,
    sample: pd.DataFrame,
    source: str,
) -> list[Finding]:
    findings: list[Finding] = []
    entry = get_rule_kind(rule_kind)
    try:
        roundtrip = entry.body_cls.model_validate(body.model_dump())
    except ValidationError as exc:
        findings.append(
            Finding(
                layer=Layer.L1,
                derivation=target,
                property_id="L1.body_validation",
                severity=Severity.ERROR,
                message=f"The rule body is not well-formed: {_summarize_pydantic_errors(exc.errors())}",
            )
        )
        return findings

    try:
        out = entry.apply(sample, target, source, roundtrip)
    except Exception as exc:
        findings.append(
            Finding(
                layer=Layer.L1,
                derivation=target,
                property_id="L1.apply_execution",
                severity=Severity.ERROR,
                message=f"Running the rule against a sample raised an unexpected error: {exc}",
            )
        )
        return findings

    if target not in out.columns:
        findings.append(
            Finding(
                layer=Layer.L1,
                derivation=target,
                property_id="L1.target_column_present",
                severity=Severity.ERROR,
                message=f'The rule did not produce the expected output column "{target}".',
            )
        )
        return findings

    if len(out) != len(sample):
        findings.append(
            Finding(
                layer=Layer.L1,
                derivation=target,
                property_id="L1.row_count_preserved",
                severity=Severity.ERROR,
                message=(
                    f"Row count changed during the rule's execution: {len(sample)} input rows became {len(out)} output rows."
                ),
            )
        )

    return findings


def verify_rule_instance(
    target: str,
    rule_kind: str,
    body: BaseModel,
    source: str,
    sample: pd.DataFrame,
) -> Verdict:
    """Run L1 + L_p against a candidate rule instance. Fail-closed at any L1
    finding; otherwise run L_p and combine.

    target: the derived column name.
    rule_kind: rule_kind name (must be in the registry).
    body: the typed rule body (already a Pydantic instance).
    source: the input column (for single-source kinds like bin/flag).
    sample: a small DataFrame containing at least the source column.
    """
    findings = _l1_findings(target, rule_kind, body, sample, source)
    if any(f.severity == Severity.ERROR for f in findings):
        return Verdict.from_findings(target, findings)

    findings.extend(run_l2(rule_kind, target, body))
    if any(f.severity == Severity.ERROR for f in findings):
        return Verdict.from_findings(target, findings)

    entry = get_rule_kind(rule_kind)
    findings.extend(run_suite(rule_kind, target, body, entry.apply))
    return Verdict.from_findings(target, findings)
