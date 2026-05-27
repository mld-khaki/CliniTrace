"""Rule kinds: the deterministic derivation library.

Each rule_kind ships with:
  - a Pydantic body model (L1 schema validation)
  - an approved Python function (executed by the Orchestrator)
  - a property suite (Hypothesis-driven, exercised by Verification's L_p layer)

The five rule_kinds declared in _002 section 2.2:
  - bin       : numeric → categorical buckets (e.g. AGE_GROUP).
  - flag      : categorical → fixed label (e.g. RESPONSE_FLAG).
  - duration  : (start_date, end_date) → numeric delta (e.g. TREATMENT_DURATION).
  - compound  : boolean AND/OR of column predicates (e.g. ANALYSIS_POP_FLAG).
  - risk_score: tier-priority categorisation across columns (e.g. RISK_GROUP).

`REGISTRY` is the canonical (rule_kind name) -> (body class, apply function)
mapping. Agents must look up rule_kinds here; never hard-code per-kind logic
outside the rule_kinds package.

Note on the apply() signature:
  All rules share apply(df, target, source, body). For single-source rules
  (bin/flag) the `source` parameter names the input column. Multi-source
  rules (duration/compound/risk_score) ignore `source` and carry their
  column references inside the body itself (e.g. start_column/end_column on
  DurationBody, condition.column on CompoundCondition). The orchestrator
  supplies a sample DataFrame containing every column listed in
  entry.inputs, so multi-source rules can read whatever they need.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

import pandas as pd
from pydantic import BaseModel

from clinitrace.rule_kinds.bin import BinBody, apply_bin
from clinitrace.rule_kinds.compound import CompoundBody, apply_compound
from clinitrace.rule_kinds.duration import DurationBody, apply_duration
from clinitrace.rule_kinds.flag import FlagBody, apply_flag
from clinitrace.rule_kinds.risk_score import RiskScoreBody, apply_risk_score


class RuleKindEntry(NamedTuple):
    """A registered rule_kind: its body class and approved apply function."""

    body_cls: type[BaseModel]
    apply: Callable[[pd.DataFrame, str, str, BaseModel], pd.DataFrame]
    referenced_columns: Callable[[list[str], BaseModel | dict[str, Any]], list[str]]


def _unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _as_dict(body: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, BaseModel):
        return body.model_dump(mode="json")
    return body


def _single_source_columns(inputs: list[str], body: BaseModel | dict[str, Any]) -> list[str]:
    return _unique(inputs)


def _duration_columns(inputs: list[str], body: BaseModel | dict[str, Any]) -> list[str]:
    raw = _as_dict(body)
    return _unique([*inputs, raw.get("start_column"), raw.get("end_column")])


def _compound_columns(inputs: list[str], body: BaseModel | dict[str, Any]) -> list[str]:
    raw = _as_dict(body)
    columns = list(inputs)
    for cond in raw.get("conditions") or []:
        if isinstance(cond, dict):
            columns.append(cond.get("column"))
        elif hasattr(cond, "column"):
            columns.append(cond.column)
    return _unique(columns)


def _risk_score_columns(inputs: list[str], body: BaseModel | dict[str, Any]) -> list[str]:
    raw = _as_dict(body)
    columns = list(inputs)
    for tier in raw.get("tiers") or []:
        conditions = tier.get("conditions") if isinstance(tier, dict) else getattr(tier, "conditions", [])
        for cond in conditions or []:
            if isinstance(cond, dict):
                columns.append(cond.get("column"))
            elif hasattr(cond, "column"):
                columns.append(cond.column)
    return _unique(columns)


REGISTRY: dict[str, RuleKindEntry] = {
    "bin": RuleKindEntry(body_cls=BinBody, apply=apply_bin, referenced_columns=_single_source_columns),  # type: ignore[arg-type]
    "flag": RuleKindEntry(body_cls=FlagBody, apply=apply_flag, referenced_columns=_single_source_columns),  # type: ignore[arg-type]
    "duration": RuleKindEntry(body_cls=DurationBody, apply=apply_duration, referenced_columns=_duration_columns),  # type: ignore[arg-type]
    "compound": RuleKindEntry(body_cls=CompoundBody, apply=apply_compound, referenced_columns=_compound_columns),  # type: ignore[arg-type]
    "risk_score": RuleKindEntry(body_cls=RiskScoreBody, apply=apply_risk_score, referenced_columns=_risk_score_columns),  # type: ignore[arg-type]
}


def known_rule_kinds() -> list[str]:
    """Names of the rule_kinds shipped in this build. Stable ordering."""
    return sorted(REGISTRY.keys())


def get(rule_kind: str) -> RuleKindEntry:
    """Look up a rule_kind by name. Raises KeyError on miss."""
    if rule_kind not in REGISTRY:
        raise KeyError(
            f"unknown rule_kind {rule_kind!r}; "
            f"known: {known_rule_kinds()}"
        )
    return REGISTRY[rule_kind]
