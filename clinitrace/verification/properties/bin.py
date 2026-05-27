"""L_p property suite for the `bin` rule_kind.

Contracts from property_test_contracts.md section 1:
  P-bin-1: every non-null input maps to exactly one declared label.
  P-bin-2: null handling is explicit.
  P-bin-3: output set is a subset of declared labels (plus permitted null/label).
  P-bin-4: deterministic across invocations.

Runs against deterministic synthetic batches (fixed seed) so a V run on the
same rule instance always produces the same findings.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import pandas as pd
from pydantic import BaseModel

from clinitrace.rule_kinds.bin import BinBody, BinNullHandling
from clinitrace.rule_kinds.errors import NullInputError
from clinitrace.verification.findings import Finding, Layer, Severity

_SEED = 0xB1FFAB1E
_BATCH_SIZE = 100


def _numeric_batch(body: BinBody) -> pd.Series:
    rng = random.Random(_SEED)
    lo = min(body.edges) - 5.0
    hi = max(body.edges) + 5.0
    values: list[float] = list(body.edges)
    for edge in body.edges:
        values.extend([edge - 1e-9, edge + 1e-9])
    while len(values) < _BATCH_SIZE:
        values.append(rng.uniform(lo, hi))
    return pd.Series(values, dtype=float)


def _err(target: str, pid: str, msg: str, sample: dict | None = None) -> Finding:
    return Finding(
        layer=Layer.L_P,
        derivation=target,
        property_id=pid,
        severity=Severity.ERROR,
        message=msg,
        sample=sample or {},
    )


def _check_p1(target: str, body: BinBody, apply_fn: Callable) -> list[Finding]:
    series = _numeric_batch(body)
    df = pd.DataFrame({"_x": series})
    try:
        out = apply_fn(df, target, "_x", body)
    except Exception as exc:
        return [_err(target, "P-bin-1", f"Running the rule on regular inputs raised an unexpected error: {exc!r}.")]
    labels = set(body.labels)
    findings: list[Finding] = []
    for i, value in enumerate(out[target].tolist()):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            findings.append(
                _err(
                    target,
                    "P-bin-1",
                    "The rule produced a missing output for a regular (non-missing) input.",
                    {"input": float(series.iloc[i])},
                )
            )
            break
        if value not in labels:
            findings.append(
                _err(
                    target,
                    "P-bin-1",
                    f"The rule produced {value!r}, which is not in the declared bucket list {sorted(labels)!r}.",
                    {"input": float(series.iloc[i]), "output": value},
                )
            )
            break
    return findings


def _check_p2(target: str, body: BinBody, apply_fn: Callable) -> list[Finding]:
    df = pd.DataFrame({"_x": [None, None, None]}, dtype=object)
    df["_x"] = pd.to_numeric(df["_x"], errors="coerce")
    if body.null_handling == BinNullHandling.ERROR:
        try:
            apply_fn(df, target, "_x", body)
        except NullInputError:
            return []
        except Exception as exc:
            return [
                _err(
                    target,
                    "P-bin-2",
                    f"The rule should raise a missing-input error for missing inputs, but raised a different kind of error ({type(exc).__name__}) instead.",
                )
            ]
        return [_err(target, "P-bin-2", "The rule declares it should raise an error for missing inputs, but accepted a missing input without raising.")]
    try:
        out = apply_fn(df, target, "_x", body)
    except Exception as exc:
        return [_err(target, "P-bin-2", f"Running the rule on a missing input raised an unexpected error: {exc!r}.")]
    values = list(out[target])
    if body.null_handling == BinNullHandling.NULL:
        for v in values:
            if not (v is None or (isinstance(v, float) and math.isnan(v))):
                return [
                    _err(
                        target,
                        "P-bin-2",
                        f"The rule declares missing inputs should stay missing, but produced output {v!r} instead.",
                    )
                ]
        return []
    if body.null_handling == BinNullHandling.LABEL:
        for v in values:
            if v != body.null_label:
                return [
                    _err(
                        target,
                        "P-bin-2",
                        f"The rule declares missing inputs should produce label {body.null_label!r}, but produced {v!r} instead.",
                    )
                ]
        return []
    return []


def _check_p3(target: str, body: BinBody, apply_fn: Callable) -> list[Finding]:
    series = _numeric_batch(body)
    nulls = pd.Series([None] * 5, dtype=float)
    full = pd.concat([series, nulls], ignore_index=True)
    df = pd.DataFrame({"_x": full})
    try:
        out = apply_fn(df, target, "_x", body)
    except NullInputError:
        return []
    except Exception as exc:
        return [_err(target, "P-bin-3", f"Running the rule on a synthetic input raised an unexpected error: {exc!r}.")]
    allowed = set(body.labels)
    if body.null_handling == BinNullHandling.LABEL:
        allowed.add(body.null_label)  # type: ignore[arg-type]
    for v in out[target]:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            if body.null_handling == BinNullHandling.NULL:
                continue
            return [
                _err(
                    target,
                    "P-bin-3",
                    f"The rule produced a missing output even though it declares null_handling={body.null_handling.value!r}.",
                )
            ]
        if v not in allowed:
            return [
                _err(
                    target,
                    "P-bin-3",
                    f"The rule produced {v!r}, which is not in the declared bucket list {sorted(allowed)!r}.",
                )
            ]
    return []


def _check_p4(target: str, body: BinBody, apply_fn: Callable) -> list[Finding]:
    series = _numeric_batch(body)
    df = pd.DataFrame({"_x": series})
    try:
        a = apply_fn(df, target, "_x", body)[target].tolist()
        b = apply_fn(df, target, "_x", body)[target].tolist()
    except NullInputError:
        return []
    except Exception as exc:
        return [_err(target, "P-bin-4", f"Running the rule on a synthetic input raised an unexpected error: {exc!r}.")]
    if a != b:
        return [_err(target, "P-bin-4", "Running the rule twice on the same input gave different answers (this rule is not deterministic).")]
    return []


def run(target: str, body: BaseModel, apply_fn: Callable) -> list[Finding]:
    """Run the bin L_p property suite. Returns all findings (possibly empty)."""
    if not isinstance(body, BinBody):
        return [
            _err(
                target,
                "L_p.dispatch",
                f"Internal error: the bucketing test suite was invoked with the wrong rule type ({type(body).__name__}).",
            )
        ]
    findings: list[Finding] = []
    findings.extend(_check_p1(target, body, apply_fn))
    findings.extend(_check_p2(target, body, apply_fn))
    findings.extend(_check_p3(target, body, apply_fn))
    findings.extend(_check_p4(target, body, apply_fn))
    return findings
