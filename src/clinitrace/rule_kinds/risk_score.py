"""risk_score rule_kind: tier-priority categorisation across multiple columns.

Body schema:
    tiers:          ordered list of {label, conditions, combinator}.
                    First tier whose conditions evaluate True for a row wins.
    fallback_label: label used when no tier matches.
    null_handling:  how to treat rows where every tier evaluates undefined
                    because operands are null ({null, fallback, error}).

Apply semantics:
    For each row:
      1. Walk tiers top-to-bottom.
      2. The first tier whose folded predicate is True assigns its label.
      3. If no tier matches (all False) → fallback_label.
      4. If every tier's predicate is undefined (Kleene NA) → null_handling.

Use case: RISK_GROUP. The canonical example is "high" if (age >= 65 AND
lab_value >= 60), else "medium" if lab_value >= 50, else "low" — a clinical
risk-stratification ladder where ORDER MATTERS.

Why not stack `compound` rules?
    Two reasons:
      1. Ordering: a stack of independent compound rules can't express
         "first match wins". RISK_GROUP needs that — a 70-year-old patient
         with lab_value=80 should be 'high', not both 'high' and 'medium'.
      2. Auditability: one risk_score rule body shows the full ladder in
         one place, so a reviewer can see "what other values could this
         patient have landed on" without joining N separate rules.

Why body-carried column refs: see duration.py module docstring.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

# Re-use compound's condition machinery so the risk-tier semantics match
# what's in apply_compound — same operators, same Kleene NA handling.
from clinitrace.rule_kinds.compound import (
    CompoundCombinator,
    CompoundCondition,
    _evaluate_condition,
)
from clinitrace.rule_kinds.errors import NullInputError


class RiskNullHandling(str, Enum):
    """How the rule treats rows where every tier evaluates undefined."""

    NULL = "null"
    FALLBACK = "fallback"
    ERROR = "error"


class RiskTier(BaseModel):
    """One rung of the risk ladder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(..., min_length=1)
    conditions: list[CompoundCondition] = Field(..., min_length=1)
    combinator: CompoundCombinator = CompoundCombinator.AND


class RiskScoreBody(BaseModel):
    """L1 schema for the risk_score rule_kind.

    Construction-time invariants:
      - At least one tier (a ladder with no rungs has nothing to assign).
      - Tier labels are unique (so the output set is auditable).
      - fallback_label is distinct from every tier label only when the
        author explicitly wants a separate 'unmatched' bucket; we allow
        equality so 'low' can serve as both bottom tier AND fallback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tiers: list[RiskTier] = Field(..., min_length=1)
    fallback_label: str = Field(..., min_length=1)
    null_handling: RiskNullHandling = RiskNullHandling.FALLBACK

    def model_post_init(self, _ctx: object) -> None:  # type: ignore[override]
        labels = [t.label for t in self.tiers]
        if len(set(labels)) != len(labels):
            dupes = sorted({l for l in labels if labels.count(l) > 1})
            raise ValueError(f"tier labels must be unique; duplicates: {dupes!r}")


def _evaluate_tier(df: pd.DataFrame, tier: RiskTier) -> pd.Series:
    """Return a boolean (or pd.NA) Series of whether each row matches tier."""
    truths = [
        _evaluate_condition(df[cond.column], cond.op, cond.value)
        for cond in tier.conditions
    ]
    if tier.combinator == CompoundCombinator.AND:
        combined = truths[0]
        for t in truths[1:]:
            combined = combined & t
    else:
        combined = truths[0]
        for t in truths[1:]:
            combined = combined | t
    return combined


def apply_risk_score(
    df: pd.DataFrame,
    target: str,
    source: str,  # noqa: ARG001 — unused; column refs live in body
    body: RiskScoreBody,
) -> pd.DataFrame:
    """Approved Python function for the risk_score rule_kind.

    Walks the tier ladder top-to-bottom; assigns each row the first matching
    tier's label. Unmatched rows get fallback_label. Rows with undefined
    truth across all tiers route through null_handling.

    Raises:
        KeyError: a required column is not present in df.
        NullInputError: at least one row has undefined truth across every
            tier and body.null_handling == RiskNullHandling.ERROR.
    """
    # Validate every referenced column exists before any work.
    required = {cond.column for tier in body.tiers for cond in tier.conditions}
    for col in required:
        if col not in df.columns:
            raise KeyError(
                f"required column {col!r} not found in DataFrame; "
                f"available columns: {list(df.columns)}"
            )

    # Default everyone to fallback. We then overwrite where a tier wins.
    # `assigned` tracks which rows have already been claimed by an earlier
    # tier — under "first match wins", later tiers must NOT overwrite.
    out = pd.Series([body.fallback_label] * len(df), index=df.index, dtype=object)
    assigned = pd.Series([False] * len(df), index=df.index)
    all_undefined = pd.Series([True] * len(df), index=df.index)

    for tier in body.tiers:
        truths = _evaluate_tier(df, tier)
        # all_undefined stays True only where every tier so far has been NA.
        all_undefined = all_undefined & truths.isna()
        # Where truths is True AND the row isn't already assigned → claim it.
        wins = truths.fillna(False) & ~assigned
        out = out.where(~wins, other=tier.label)
        assigned = assigned | wins

    if body.null_handling == RiskNullHandling.ERROR and bool(all_undefined.any()):
        raise NullInputError(
            f"every tier evaluated undefined under null_handling='error'; "
            f"{int(all_undefined.sum())} of {len(df)} rows had no resolvable tier"
        )

    if body.null_handling == RiskNullHandling.NULL:
        # Rows where every tier was NA *and* the row wasn't otherwise
        # assigned land on null instead of the fallback label.
        emit_null = all_undefined & ~assigned
        out = out.where(~emit_null, other=None)
    # FALLBACK is the default behavior above — nothing to patch.

    return df.assign(**{target: out})
