"""L_p property suite for the `flag` rule_kind.

Contracts from property_test_contracts.md section 2:
  P-flag-1: every declared key maps to its defined value.
  P-flag-2: null handling is explicit.
  P-flag-3: unmapped handling is explicit.
  P-flag-4: output set is a subset of declared values (plus permitted null/unmapped_value).
  P-flag-5: deterministic across invocations.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import pandas as pd
from pydantic import BaseModel

from clinitrace.rule_kinds.errors import NullInputError
from clinitrace.rule_kinds.flag import FlagBody, FlagNullHandling, FlagUnmappedHandling
from clinitrace.verification.findings import Finding, Layer, Severity

_SEED = 0xF1A6B1FE


def _err(target: str, pid: str, msg: str, sample: dict | None = None) -> Finding:
    return Finding(
        layer=Layer.L_P,
        derivation=target,
        property_id=pid,
        severity=Severity.ERROR,
        message=msg,
        sample=sample or {},
    )


def _unmapped_strings(body: FlagBody, n: int = 10) -> list[str]:
    rng = random.Random(_SEED)
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        candidate = f"__unmapped_{rng.randrange(10_000_000):07d}__"
        if candidate not in body.map and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def _check_p1(target: str, body: FlagBody, apply_fn: Callable) -> list[Finding]:
    keys = list(body.map.keys())
    df = pd.DataFrame({"_x": keys})
    try:
        out = apply_fn(df, target, "_x", body)
    except Exception as exc:
        return [_err(target, "P-flag-1", f"Running the rule on declared input values raised an unexpected error: {exc!r}.")]
    for key, observed in zip(keys, out[target].tolist(), strict=True):
        expected = body.map[key]
        if observed != expected:
            return [
                _err(
                    target,
                    "P-flag-1",
                    f"The rule declares {key!r} should map to {expected!r}, but produced {observed!r} instead.",
                    {"key": key, "observed": observed, "expected": expected},
                )
            ]
    return []


def _check_p2(target: str, body: FlagBody, apply_fn: Callable) -> list[Finding]:
    df = pd.DataFrame({"_x": [None, None, None]}, dtype=object)
    if body.null_handling == FlagNullHandling.ERROR:
        try:
            apply_fn(df, target, "_x", body)
        except NullInputError:
            return []
        except Exception as exc:
            return [
                _err(
                    target,
                    "P-flag-2",
                    f"The rule should raise a missing-input error for missing inputs, but raised a different kind of error ({type(exc).__name__}) instead.",
                )
            ]
        return [_err(target, "P-flag-2", "The rule declares it should raise an error for missing inputs, but accepted a missing input without raising.")]
    try:
        out = apply_fn(df, target, "_x", body)
    except Exception as exc:
        return [_err(target, "P-flag-2", f"Running the rule on a missing input raised an unexpected error: {exc!r}.")]
    values = list(out[target])
    if body.null_handling == FlagNullHandling.NULL:
        for v in values:
            if not (v is None or (isinstance(v, float) and math.isnan(v))):
                return [_err(target, "P-flag-2", f"The rule declares missing inputs should stay missing, but produced output {v!r} instead.")]
        return []
    if body.null_handling == FlagNullHandling.VALUE:
        for v in values:
            if v != body.null_value:
                return [
                    _err(
                        target,
                        "P-flag-2",
                        f"The rule declares missing inputs should produce {body.null_value!r}, but produced {v!r} instead.",
                    )
                ]
        return []
    return []


def _check_p3(target: str, body: FlagBody, apply_fn: Callable) -> list[Finding]:
    unmapped = _unmapped_strings(body)
    df = pd.DataFrame({"_x": unmapped})
    if body.unmapped_handling == FlagUnmappedHandling.ERROR:
        try:
            apply_fn(df, target, "_x", body)
        except ValueError:
            return []
        except Exception as exc:
            return [
                _err(
                    target,
                    "P-flag-3",
                    f"The rule should raise an unmapped-input error for unknown values, but raised a different kind of error ({type(exc).__name__}) instead.",
                )
            ]
        return [
            _err(
                target,
                "P-flag-3",
                "The rule declares it should raise an error for unknown input values, but accepted one without raising.",
            )
        ]
    try:
        out = apply_fn(df, target, "_x", body)
    except Exception as exc:
        return [_err(target, "P-flag-3", f"Running the rule on an unknown input value raised an unexpected error: {exc!r}.")]
    values = list(out[target])
    if body.unmapped_handling == FlagUnmappedHandling.NULL:
        for v in values:
            if not (v is None or (isinstance(v, float) and math.isnan(v))):
                return [
                    _err(
                        target,
                        "P-flag-3",
                        f"The rule declares unknown inputs should be left missing, but produced {v!r} instead.",
                    )
                ]
        return []
    if body.unmapped_handling == FlagUnmappedHandling.VALUE:
        for v in values:
            if v != body.unmapped_value:
                return [
                    _err(
                        target,
                        "P-flag-3",
                        f"The rule declares unknown inputs should produce {body.unmapped_value!r}, but produced {v!r} instead.",
                    )
                ]
        return []
    return []


def _check_p4(target: str, body: FlagBody, apply_fn: Callable) -> list[Finding]:
    keys = list(body.map.keys())
    unmapped = _unmapped_strings(body, n=5)
    inputs = keys + unmapped + [None] * 3
    df = pd.DataFrame({"_x": inputs}, dtype=object)
    try:
        out = apply_fn(df, target, "_x", body)
    except (NullInputError, ValueError):
        return []
    except Exception as exc:
        return [_err(target, "P-flag-4", f"Running the rule on a synthetic input raised an unexpected error: {exc!r}.")]
    allowed: set[object] = set(body.map.values())
    if body.null_handling == FlagNullHandling.VALUE and body.null_value is not None:
        allowed.add(body.null_value)
    if (
        body.unmapped_handling == FlagUnmappedHandling.VALUE
        and body.unmapped_value is not None
    ):
        allowed.add(body.unmapped_value)
    null_allowed = (
        body.null_handling == FlagNullHandling.NULL
        or body.unmapped_handling == FlagUnmappedHandling.NULL
    )
    for v in out[target]:
        is_nullish = v is None or (isinstance(v, float) and math.isnan(v))
        if is_nullish:
            if not null_allowed:
                return [
                    _err(
                        target,
                        "P-flag-4",
                        "The rule produced a missing output, but no handling path declares missing values.",
                    )
                ]
            continue
        if v not in allowed:
            return [
                _err(
                    target,
                    "P-flag-4",
                    f"The rule produced {v!r}, which is not in the declared output set {sorted(map(str, allowed))!r}.",
                )
            ]
    return []


def _check_p5(target: str, body: FlagBody, apply_fn: Callable) -> list[Finding]:
    keys = list(body.map.keys())
    df = pd.DataFrame({"_x": keys})
    try:
        a = apply_fn(df, target, "_x", body)[target].tolist()
        b = apply_fn(df, target, "_x", body)[target].tolist()
    except Exception as exc:
        return [_err(target, "P-flag-5", f"Running the rule on a synthetic input raised an unexpected error: {exc!r}.")]
    if a != b:
        return [_err(target, "P-flag-5", "Running the rule twice on the same input gave different answers (this rule is not deterministic).")]
    return []


def run(target: str, body: BaseModel, apply_fn: Callable) -> list[Finding]:
    if not isinstance(body, FlagBody):
        return [
            _err(
                target,
                "L_p.dispatch",
                f"Internal error: the value-mapping test suite was invoked with the wrong rule type ({type(body).__name__}).",
            )
        ]
    findings: list[Finding] = []
    findings.extend(_check_p1(target, body, apply_fn))
    findings.extend(_check_p2(target, body, apply_fn))
    findings.extend(_check_p3(target, body, apply_fn))
    findings.extend(_check_p4(target, body, apply_fn))
    findings.extend(_check_p5(target, body, apply_fn))
    return findings
