"""Generate a draft IDC from a raw dataset.

The traditional flow is YAML-first: the user writes a spec, the pipeline
validates it, ambiguities surface at SR. But a clinical data manager who
just received a fresh extract can't reasonably hand-write a Pydantic-shaped
YAML. The agentic flow should reach backwards into spec authoring:

  Dataset → profile → propose derivations → review (HITL) → spec

This module produces the "propose derivations" half. The proposals are then
shown in the UI as a checklist; the user accepts/rejects each before any
pipeline work begins. **No proposal becomes pipeline input without explicit
human acceptance** — that boundary is the whole point of HITL at this layer.

Two signals stacked, same architectural pattern as spec_triage:

  1. **Deterministic profile** (always on, cheap).
       Column dtypes, cardinality, null fraction, value range, sample
       values, date-string detectability.

  2. **Pattern matching** (always on, deterministic).
       Recognises common clinical idioms from the profile:
         age column                → AGE_GROUP (bin)
         low-cardinality string    → *_FLAG (flag)
         pair of date columns      → *_DURATION (duration)
         age + response            → ANALYSIS_POP_FLAG (compound)
         age + numeric measurement → RISK_GROUP (risk_score)
       Patterns are conservative — better to miss a derivation than
       hallucinate one. The user can always add more by hand.

  3. **LLM augmentation** (optional; CLINITRACE_LLM=live).
       Asks the LLM for (a) derivations the patterns missed and (b)
       reviewer-friendly rationales. Each LLM proposal is structurally
       validated against the rule_kind registry before it joins the list
       — anything that fails to validate is dropped.

Why deterministic patterns even when an LLM is available:
  - Reproducibility: the same dataset produces the same baseline
    suggestions across runs. Regulatory submissions need that.
  - Latency: the user sees suggestions in <100ms instead of waiting on a
    model call.
  - Cost: most idioms don't need an LLM to recognise.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

log = logging.getLogger("clinitrace.spec_generator")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


# Heuristics for "this column looks like a date." We test parseability rather
# than relying on dtype because CSVs commonly arrive as object-dtype strings.
_DATE_NAME_PATTERNS = re.compile(
    r"date|_dt$|_at$|timestamp|dob|birth", re.IGNORECASE
)

# Column names that suggest a categorical flag rule (broad — sex / cohort /
# response all qualify).
_FLAG_NAME_PATTERNS = re.compile(
    r"response|outcome|status|category|cohort|arm|group|sex|gender",
    re.IGNORECASE,
)

# Narrower set used by ANALYSIS_POP_FLAG: only OUTCOME columns count for
# the "has a recorded response" inclusion criterion. Demographic columns
# like sex are NOT in this list — being in the analysis population should
# not depend on a patient's demographics.
_OUTCOME_NAME_PATTERNS = re.compile(
    r"response|outcome|efficacy|endpoint|disposition",
    re.IGNORECASE,
)

# Columns matching these names get an age-binning suggestion.
_AGE_NAME_PATTERNS = re.compile(r"^age$|^age_|_age$", re.IGNORECASE)

# Columns matching these names get a "measurement" treatment for risk scoring.
_MEASUREMENT_NAME_PATTERNS = re.compile(
    r"lab|score|level|measurement|value|bmi|weight|height|pressure",
    re.IGNORECASE,
)


def _is_date_column(series: pd.Series, name: str) -> bool:
    """A column is 'date-like' if (a) its name hints at dates AND (b) at least
    80% of non-null values parse as a date.

    Two-signal check: a column called 'patient_notes' that happens to
    contain a parseable date in one row should NOT be flagged as a date
    column. Conversely, an actual date column with one or two bad rows
    should still be flagged (hence the 80% threshold, not 100%).
    """
    if not _DATE_NAME_PATTERNS.search(name):
        return False
    nonnull = series.dropna()
    if nonnull.empty:
        return False
    try:
        parsed = pd.to_datetime(nonnull, errors="coerce")
    except Exception:  # noqa: BLE001
        return False
    return float(parsed.notna().mean()) >= 0.8


def _classify_column(series: pd.Series, name: str) -> str:
    """Coarse category: 'date' | 'numeric' | 'low_cardinality' | 'high_cardinality' | 'unknown'."""
    if _is_date_column(series, name):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    nonnull = series.dropna()
    if nonnull.empty:
        return "unknown"
    nunique = nonnull.nunique()
    # 'low cardinality' is the clinical-data sweet spot for flag rules:
    # things like sex (2-3 values) or response (responder / non_responder
    # / unknown). Anything above 20 distinct values is treated as free
    # text — too many to enumerate in a map.
    if nunique <= 20:
        return "low_cardinality"
    return "high_cardinality"


def profile_dataset(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Return a per-column profile usable by both propose_derivations and
    the UI preview.

    Output schema (per column):
      kind             : 'date' | 'numeric' | 'low_cardinality' |
                         'high_cardinality' | 'unknown'
      dtype            : str (e.g. 'int64', 'object')
      null_fraction    : float in [0, 1]
      n_unique         : int (None if not computed)
      sample_values    : list[Any] (up to 5)
      min, max         : present for numeric
      values           : present for low_cardinality (sorted unique)
    """
    out: dict[str, dict[str, Any]] = {}
    for name in df.columns:
        series = df[name]
        kind = _classify_column(series, name)
        profile: dict[str, Any] = {
            "kind": kind,
            "dtype": str(series.dtype),
            "null_fraction": float(series.isna().mean()),
            "n_unique": int(series.dropna().nunique()) if not series.dropna().empty else 0,
            "sample_values": [
                str(v) for v in series.dropna().head(5).tolist()
            ],
        }
        if kind == "numeric":
            nonnull = series.dropna()
            if not nonnull.empty:
                profile["min"] = float(nonnull.min())
                profile["max"] = float(nonnull.max())
        if kind == "low_cardinality":
            profile["values"] = sorted(
                series.dropna().astype(str).unique().tolist()
            )
        out[name] = profile
    return out


# ---------------------------------------------------------------------------
# Propose
# ---------------------------------------------------------------------------


# Each proposal is the structural shape of a SpecEntry plus a 'confidence'
# and 'reason' so the UI can render the agent's reasoning to the reviewer.
Proposal = dict[str, Any]


def _propose_age_group(col: str, profile: dict[str, Any]) -> Proposal | None:
    """If a column looks like an age column, propose AGE_GROUP bin."""
    if profile["kind"] != "numeric":
        return None
    if not _AGE_NAME_PATTERNS.search(col):
        return None
    mn = profile.get("min", 0.0)
    mx = profile.get("max", 100.0)
    # Choose edges that bracket the observed range. The classic three-tier
    # clinical stratification is pediatric (<18) / adult (18-65) / senior
    # (65+). If the data is all pediatric (max < 18) or all senior (min >=
    # 65), drop the unused tier.
    edges: list[float] = []
    labels: list[str] = []
    if mn < 18:
        labels.append("minor")
        edges.append(18.0)
    labels.append("adult")
    if mx >= 65:
        edges.append(65.0)
        labels.append("senior")
    if len(labels) < 2:
        return None
    return {
        "name": "AGE_GROUP",
        "inputs": [col],
        "rule_kind": "bin",
        "rule_body": {"edges": edges, "labels": labels},
        "rationale": (
            f"Stratify patients by {col} into clinically meaningful "
            f"age bands (data ranges {mn:.0f}–{mx:.0f})."
        ),
        "_confidence": 0.90,
        "_reason": f"`{col}` is numeric and its name matches an age pattern",
    }


def _propose_flag(col: str, profile: dict[str, Any]) -> Proposal | None:
    """If a low-cardinality string column looks like a categorical outcome,
    propose a flag rule that maps each value to itself (the reviewer will
    edit the targets)."""
    if profile["kind"] != "low_cardinality":
        return None
    if not _FLAG_NAME_PATTERNS.search(col):
        return None
    values = profile.get("values", [])
    if not values or len(values) > 6:
        # Too many distinct values to map cleanly; ask reviewer to handle.
        return None
    # Default mapping: preserve known values, but pick something readable
    # for common binary outcomes.
    mapping: dict[str, str] = {}
    for v in values:
        v_lower = str(v).lower()
        if v_lower in ("responder", "yes", "true", "y", "positive"):
            mapping[v] = "Y"
        elif v_lower in ("non_responder", "non-responder", "no", "false", "n", "negative"):
            mapping[v] = "N"
        elif v_lower in ("unknown", "missing", "na", "n/a"):
            mapping[v] = "U"
        else:
            mapping[v] = str(v).upper()[:3]
    return {
        "name": f"{col.upper()}_FLAG",
        "inputs": [col],
        "rule_kind": "flag",
        "rule_body": {
            "map": mapping,
            "unmapped_handling": "value",
            "unmapped_value": "U",
        },
        "rationale": (
            f"Map `{col}` (values {values}) to a binary/ternary flag for "
            f"downstream tables. Unmapped inputs surface as 'U' for review."
        ),
        "_confidence": 0.85,
        "_reason": (
            f"`{col}` is low-cardinality and its name matches a "
            f"categorical-outcome pattern"
        ),
    }


def _propose_duration(
    df: pd.DataFrame, profile: dict[str, dict[str, Any]]
) -> Proposal | None:  # noqa: ARG001 — df present for uniform signature

    """Find a pair of date columns whose names suggest 'start' and 'visit'
    or similar, and propose a TREATMENT_DURATION-style duration."""
    date_cols = [c for c, p in profile.items() if p["kind"] == "date"]
    if len(date_cols) < 2:
        return None
    # Heuristic: pair a "start"-ish column with the most likely "end"-ish.
    start = next(
        (c for c in date_cols if re.search(r"start|begin|baseline", c, re.IGNORECASE)),
        None,
    )
    end = next(
        (c for c in date_cols if re.search(r"visit|end|stop|followup|f_?up", c, re.IGNORECASE)),
        None,
    )
    if start is None or end is None or start == end:
        # Fall back: first two date columns, in declaration order.
        start, end = date_cols[0], date_cols[1]
    return {
        "name": "TREATMENT_DURATION",
        "inputs": [start, end],
        "rule_kind": "duration",
        "rule_body": {
            "start_column": start,
            "end_column": end,
            "unit": "days",
            "null_handling": "null",
        },
        "rationale": (
            f"Days from {start} to {end}. Surfaces exposure window for "
            f"per-visit analysis."
        ),
        "_confidence": 0.80,
        "_reason": f"Two date columns detected: {start} and {end}",
    }


def _propose_analysis_pop(
    df: pd.DataFrame, profile: dict[str, dict[str, Any]]
) -> Proposal | None:
    """If an age column and a response-like column both exist, propose
    ANALYSIS_POP_FLAG (the classic SAP inclusion criterion)."""
    age_col = next(
        (c for c, p in profile.items()
         if p["kind"] == "numeric" and _AGE_NAME_PATTERNS.search(c)),
        None,
    )
    # Use the narrower OUTCOME pattern here — sex/cohort shouldn't gate
    # analysis-population membership.
    resp_col = next(
        (c for c, p in profile.items()
         if p["kind"] == "low_cardinality" and _OUTCOME_NAME_PATTERNS.search(c)),
        None,
    )
    if age_col is None or resp_col is None:
        return None
    return {
        "name": "ANALYSIS_POP_FLAG",
        "inputs": [age_col, resp_col],
        "rule_kind": "compound",
        "rule_body": {
            "conditions": [
                {"column": age_col, "op": ">=", "value": 18},
                {"column": resp_col, "op": "not_null"},
            ],
            "combinator": "and",
            "true_value": "Y",
            "false_value": "N",
            "null_handling": "false",
        },
        "rationale": (
            f"Patient is in the analysis population if they are 18+ AND "
            f"have a recorded {resp_col}. Default inclusion criterion "
            f"per most SAPs — reviewer should confirm exposure / other "
            f"criteria are not also required."
        ),
        "_confidence": 0.70,
        "_reason": (
            f"`{age_col}` (age-like) and `{resp_col}` (response-like) "
            f"both present"
        ),
    }


def _propose_risk_group(
    df: pd.DataFrame, profile: dict[str, dict[str, Any]]
) -> Proposal | None:
    """If an age + measurement column pair exists, propose RISK_GROUP."""
    age_col = next(
        (c for c, p in profile.items()
         if p["kind"] == "numeric" and _AGE_NAME_PATTERNS.search(c)),
        None,
    )
    measure_col = next(
        (c for c, p in profile.items()
         if p["kind"] == "numeric"
         and not _AGE_NAME_PATTERNS.search(c)
         and _MEASUREMENT_NAME_PATTERNS.search(c)),
        None,
    )
    if age_col is None or measure_col is None:
        return None
    # Use observed range to pick clinically-reasonable cutoffs. We aim for
    # ~25/50/25 split as a placeholder; reviewer can edit.
    mx_age = profile[age_col].get("max", 90.0)
    mx_meas = profile[measure_col].get("max", 100.0)
    age_cut = 65.0 if mx_age >= 65 else round(mx_age * 0.8, 0)
    meas_cut_high = round(mx_meas * 0.75, 0)
    meas_cut_med = round(mx_meas * 0.5, 0)
    return {
        "name": "RISK_GROUP",
        "inputs": [age_col, measure_col],
        "rule_kind": "risk_score",
        "rule_body": {
            "tiers": [
                {
                    "label": "high",
                    "combinator": "and",
                    "conditions": [
                        {"column": age_col, "op": ">=", "value": age_cut},
                        {"column": measure_col, "op": ">=", "value": meas_cut_high},
                    ],
                },
                {
                    "label": "medium",
                    "combinator": "or",
                    "conditions": [
                        {"column": measure_col, "op": ">=", "value": meas_cut_med},
                        {"column": age_col, "op": ">=", "value": age_cut},
                    ],
                },
            ],
            "fallback_label": "low",
            "null_handling": "fallback",
        },
        "rationale": (
            f"First-match risk ladder. 'high' = elderly with elevated "
            f"{measure_col}; 'medium' = elderly OR elevated; 'low' = "
            f"everyone else. Cutoffs are placeholders — clinical lead "
            f"should set the real thresholds."
        ),
        "_confidence": 0.55,
        "_reason": (
            f"`{age_col}` (age) and `{measure_col}` (measurement) both "
            f"present; cutoffs are placeholders"
        ),
    }


def propose_derivations(
    df: pd.DataFrame, profile: dict[str, dict[str, Any]] | None = None
) -> list[Proposal]:
    """Return a list of structurally-valid SpecEntry-shaped proposals.

    Each proposal carries internal `_confidence` and `_reason` fields
    (stripped before the proposal becomes a SpecEntry). The list is sorted
    by confidence descending so the highest-signal proposals render first.

    Conservative by design: only proposals matching well-understood
    clinical idioms make the list. The reviewer can always hand-write
    additional derivations.
    """
    profile = profile or profile_dataset(df)
    proposals: list[Proposal] = []

    # Per-column proposals.
    for col, col_profile in profile.items():
        for proposer in (_propose_age_group, _propose_flag):
            p = proposer(col, col_profile)
            if p is not None:
                proposals.append(p)

    # Cross-column proposals (TREATMENT_DURATION, ANALYSIS_POP_FLAG, RISK_GROUP).
    # All cross-column proposers share the (df, profile) signature so the
    # dispatch loop stays uniform.
    for proposer in (_propose_duration, _propose_analysis_pop, _propose_risk_group):
        p = proposer(df, profile)
        if p is not None:
            proposals.append(p)

    # Dedupe by (name, rule_kind) — repeat age columns shouldn't produce two
    # AGE_GROUP proposals.
    seen: set[tuple[str, str]] = set()
    deduped: list[Proposal] = []
    for p in proposals:
        key = (p["name"], p["rule_kind"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    deduped.sort(key=lambda p: -p.get("_confidence", 0.0))
    return deduped


def _profile_summary_for_llm(
    profile: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compact form of the profile, safe to put in an LLM prompt.

    Drops sample values (PHI risk) and high-cardinality value lists (token
    cost). Keeps only the signals the model needs to decide what
    derivations might apply: column name, detected kind, dtype, nulls,
    range / distinct-value count.
    """
    out: dict[str, Any] = {}
    for col, p in profile.items():
        slim = {
            "kind": p["kind"],
            "dtype": p["dtype"],
            "null_fraction": round(p["null_fraction"], 2),
            "n_unique": p["n_unique"],
        }
        if "min" in p:
            slim["range"] = [p["min"], p["max"]]
        if "values" in p and len(p["values"]) <= 6:
            # Only include the value set when it's tiny enough to be
            # safe to ship — protects against PHI in high-cardinality
            # free-text columns.
            slim["values"] = p["values"]
        out[col] = slim
    return out


def augment_proposals_with_llm(
    df: pd.DataFrame,  # noqa: ARG001 — kept for parity; profile carries the signal
    profile: dict[str, dict[str, Any]],
    existing: list[Proposal],
) -> list[Proposal]:
    """Ask the LLM for additional derivations the deterministic patterns
    missed, then structurally validate each before returning.

    Fail-closed validation, fail-open dispatch:
      - If CLINITRACE_LLM=stub, returns [] (the stub is explicit about
        not contacting an LLM).
      - If the model errors / times out, returns [] (the deterministic
        baseline is always available).
      - If the model returns a proposal that fails Pydantic validation
        against the rule_kind registry, that proposal is DROPPED. We do
        not show the user a structurally-broken proposal.
    """
    # Lazy import — keeps the spec_generator import graph light and avoids
    # pulling Pydantic / dispatcher at module load.
    from clinitrace.llm import dispatcher  # noqa: PLC0415
    from clinitrace.spec.model import SpecEntry  # noqa: PLC0415

    summary = _profile_summary_for_llm(profile)
    existing_dicts = [proposal_to_spec_entry(p) for p in existing]
    try:
        raw_proposals = dispatcher.call_spec_augmentation(summary, existing_dicts)
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM augmentation aborted: %s", exc)
        return []

    if not raw_proposals:
        return []

    augmented: list[Proposal] = []
    existing_names = {p["name"] for p in existing}
    for raw in raw_proposals:
        if not isinstance(raw, dict):
            continue
        # Avoid clobbering an existing-by-name proposal.
        if raw.get("name") in existing_names:
            continue
        try:
            # SpecEntry's own validators catch unknown rule_kinds + body
            # shape mismatches — same gate the pipeline uses.
            entry = SpecEntry.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log.info(
                "Dropping LLM-augmented proposal %r — failed validation: %s",
                raw.get("name", "<unnamed>"), exc,
            )
            continue
        augmented.append({
            "name": entry.name,
            "inputs": list(entry.inputs),
            "rule_kind": entry.rule_kind,
            "rule_body": dict(entry.rule_body),
            "rationale": entry.rationale,
            "_confidence": 0.70,  # capped — LLM never beats a deterministic shape match
            "_reason": "LLM-augmented (read column profile + existing proposals)",
        })
    return augmented


def proposal_to_spec_entry(proposal: Proposal) -> dict[str, Any]:
    """Strip internal `_*` fields so a SpecEntry can be constructed."""
    return {k: v for k, v in proposal.items() if not k.startswith("_")}


def proposals_to_spec_dict(
    proposals: list[Proposal], version: str = "1"
) -> dict[str, Any]:
    """Build a full Spec-shaped dict from a list of accepted proposals."""
    return {
        "version": version,
        "derivations": [proposal_to_spec_entry(p) for p in proposals],
    }
