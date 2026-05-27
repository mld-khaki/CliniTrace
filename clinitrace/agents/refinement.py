"""Refinement / Debugging (R) -- _002 section 3.4.

In: a failed rule instance + V findings.
Out: a revised rule instance.

Bound: at most 3 retries per derivation. Adaptive early-stop: if the rule-body
hash AND the findings set are unchanged across two consecutive iterations,
R escalates to HITL immediately rather than burning further retries.

This MVP ships a structured rule-based refiner that handles the canonical
failure modes for bin/flag (missing null_handling, missing null_label,
missing unmapped_handling). For more open-ended failures the next slice
adds an LLM-backed refiner; the orchestrator interface stays the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from clinitrace.rule_kinds import get as get_rule_kind
from clinitrace.verification.findings import Finding


@dataclass(frozen=True)
class RefinementOutput:
    """R's output: a revised body dict, or escalate=True if R is stuck."""

    revised_body: dict[str, Any] | None
    escalate: bool
    reason: str
    note: str


def body_hash(body: BaseModel | dict[str, Any]) -> str:
    payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def findings_signature(findings: list[Finding]) -> str:
    keys = sorted((f.layer.value, f.property_id, f.derivation) for f in findings)
    canonical = json.dumps(keys, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


_PATCH_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("bin", "P-bin-2"): {"null_handling": "null"},
    ("flag", "P-flag-2"): {"null_handling": "null"},
    ("flag", "P-flag-3"): {"unmapped_handling": "null"},
}


def refine(
    *,
    rule_kind: str,
    body: BaseModel,
    findings: list[Finding],
) -> RefinementOutput:
    """Propose a revised body from V findings.

    Strategy for the MVP:
      - For each finding, look up a deterministic patch in _PATCH_RULES.
      - Apply patches in order. If a patch produces a body that re-validates,
        return it.
      - If no patch applies or the patched body still fails to validate,
        escalate.
    """
    if not findings:
        return RefinementOutput(
            revised_body=None,
            escalate=True,
            reason="no findings; nothing to refine",
            note="",
        )

    body_dict = body.model_dump(mode="json")
    candidate = dict(body_dict)
    applied: list[str] = []

    for finding in findings:
        key = (rule_kind, finding.property_id)
        patch = _PATCH_RULES.get(key)
        if not patch:
            continue
        candidate.update(patch)
        applied.append(f"{finding.property_id}: {patch!r}")

    if not applied:
        return RefinementOutput(
            revised_body=None,
            escalate=True,
            reason=(
                "no deterministic patch matches the findings "
                f"({[f.property_id for f in findings]!r})"
            ),
            note="",
        )

    body_cls = get_rule_kind(rule_kind).body_cls
    try:
        body_cls.model_validate(candidate)
    except Exception as exc:
        return RefinementOutput(
            revised_body=None,
            escalate=True,
            reason=f"patched body did not validate: {exc!r}",
            note="; ".join(applied),
        )

    return RefinementOutput(
        revised_body=candidate,
        escalate=False,
        reason="applied deterministic patches",
        note="; ".join(applied),
    )
