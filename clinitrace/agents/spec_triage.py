"""Spec triage: suggest the closest registered rule_kind for an unknown one.

When a spec author writes `rule_kind: bucketize` but the registry only knows
`bin`, plain "did you mean" by character distance is a weak signal — typos
and semantic mismatches need different treatments.

This module stacks three signals and merges them into a single ranked
suggestion list:

  1. **Text similarity** (deterministic, always on).
       Uses difflib.SequenceMatcher ratio. Catches the typo case:
       'binn' → bin (95%), 'flagg' → flag (89%).

  2. **Shape inference** (deterministic, always on).
       Looks at the spec entry's `inputs` count and `rule_body` keys to
       guess which rule_kind the AUTHOR DESCRIBED, regardless of what
       they NAMED it. Catches the semantic mismatch case:
       'bucketize' with body {edges: [...], labels: [...]} → bin (95%).

  3. **LLM semantic match** (optional; CLINITRACE_LLM=live).
       Sends the rationale + inputs + body keys to the LLM with the
       full registered-rule_kind catalogue, asks which one matches the
       author's INTENT. Catches the vague case:
       rule_kind: 'TBD', rationale: 'compute age buckets' → bin.

Why this lives in agents/ and not spec/:
  Triage is an interpretive step — same architectural slot as SR
  (interpreting a rationale) and CG (interpreting a body). The spec
  package owns the strict schema (Pydantic models). Whenever the schema
  fails, the agentic layer gets a chance to enrich the error before it
  reaches the user.

Why it does NOT auto-patch the spec:
  An auto-patched rule_kind is a silent change to the source-of-truth
  YAML. We surface a ranked suggestion in the error message; the user
  has to consciously edit the YAML to accept it. The boundary between
  "advisor" and "authority" stays where the design says it should: in
  the human's hands.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

log = logging.getLogger("clinitrace.spec_triage")


# Reviewer-friendly one-line description of each rule_kind. These are
# duplicated from the rule_kinds package docstrings (kept short here) so the
# error message can show "bin (95% match) — buckets a numeric column…"
# without forcing the user to chase imports.
#
# When a new rule_kind ships, add it here so triage can describe it.
_KIND_DESCRIPTIONS: dict[str, str] = {
    "bin": (
        "Buckets a numeric column into named categories using edge cut "
        "points (e.g. AGE_GROUP from age → minor/adult/senior)."
    ),
    "flag": (
        "Maps each input value through an explicit lookup table to a "
        "fixed output (e.g. RESPONSE_FLAG from response → Y/N)."
    ),
    "duration": (
        "Computes a numeric delta (days/weeks/months/years) between two "
        "date columns (e.g. TREATMENT_DURATION = visit − treatment_start)."
    ),
    "compound": (
        "Combines per-column predicates with AND/OR into a binary flag "
        "(e.g. ANALYSIS_POP_FLAG = age≥18 AND response IS NOT NULL)."
    ),
    "risk_score": (
        "Walks an ordered ladder of tiers (first match wins) to assign "
        "a categorical label (e.g. RISK_GROUP = high/medium/low)."
    ),
}


# Confidence threshold above which a deterministic suggestion is "strong"
# (so we don't escalate to the LLM, and the error message says "did you
# mean" rather than "closest matches, low confidence").
_STRONG_CONFIDENCE = 0.60


# Each tuple: (rule_kind, confidence in [0, 1], one-line reason).
Suggestion = tuple[str, float, str]


# ---------------------------------------------------------------------------
# Signal 1: text similarity
# ---------------------------------------------------------------------------


def _text_score(query: str, candidate: str) -> float:
    """Symmetric character-level similarity in [0, 1].

    SequenceMatcher.ratio() is the same metric Python's `difflib.get_close_matches`
    uses; we expose the raw score so we can combine it with shape signals.
    """
    return SequenceMatcher(None, query.lower(), candidate.lower()).ratio()


# ---------------------------------------------------------------------------
# Signal 2: shape inference
# ---------------------------------------------------------------------------


def _shape_score(rule_kind: str, entry: dict[str, Any]) -> tuple[float, str]:
    """Heuristic: does the entry's *structure* look like this rule_kind?

    Returns (confidence, reason). Confidence 0 means "no shape evidence";
    higher values mean stronger structural match. Each branch is a tight
    pattern check — we'd rather return 0 than guess wrong.

    Why heuristics and not a full type system: we only need to disambiguate
    between five rule_kinds, each with a distinct body schema. Three
    indicator keys per kind is enough to identify them when the user has
    actually filled in the body. When the body is empty or vague, the
    deterministic layer correctly returns 0 and the LLM layer takes over.
    """
    inputs = entry.get("inputs") or []
    body = entry.get("rule_body") or {}
    body_keys = set(body.keys()) if isinstance(body, dict) else set()
    n_inputs = len(inputs)

    if rule_kind == "bin":
        if {"edges", "labels"} <= body_keys:
            return (0.95, "body has edges + labels (bin signature)")
        if "edges" in body_keys or "labels" in body_keys:
            return (0.50, "body has edges or labels")

    elif rule_kind == "flag":
        if "map" in body_keys:
            return (0.95, "body has a map (flag signature)")
        if "unmapped_handling" in body_keys or "unmapped_value" in body_keys:
            return (0.60, "body has unmapped_* (flag signature)")

    elif rule_kind == "duration":
        if {"start_column", "end_column"} <= body_keys:
            return (0.95, "body has start_column + end_column (duration signature)")
        if "unit" in body_keys and n_inputs >= 2:
            return (0.80, "body has unit and 2+ inputs (duration signature)")
        if n_inputs == 2 and not body_keys:
            return (0.40, "two inputs and no body — could be duration")

    elif rule_kind == "compound":
        if {"conditions", "combinator"} <= body_keys:
            return (0.95, "body has conditions + combinator (compound signature)")
        if "conditions" in body_keys:
            return (0.75, "body has a conditions list")
        if "true_value" in body_keys or "false_value" in body_keys:
            return (0.55, "body has true/false_value (compound signature)")

    elif rule_kind == "risk_score":
        if "tiers" in body_keys:
            return (0.95, "body has tiers (risk_score signature)")
        if "fallback_label" in body_keys:
            return (0.70, "body has fallback_label (risk_score signature)")

    return (0.0, "")


# ---------------------------------------------------------------------------
# Signal 3: optional LLM semantic match
# ---------------------------------------------------------------------------


def _llm_score(unknown: str, entry: dict[str, Any]) -> Suggestion | None:
    """Ask the LLM to pick the most-likely rule_kind from rationale + body.

    Returns a single Suggestion or None. Fail-open: any exception (LLM down,
    timeout, malformed response, ImportError) is logged and yields None so
    spec validation keeps the deterministic suggestions and never blocks on
    LLM availability.

    Only fires when CLINITRACE_LLM=live. Stub mode uses keyword matching
    against the rationale as a cheap-but-real escalation signal.
    """
    try:
        # Lazy import — avoid pulling the LLM stack at module load time so
        # triage works even in environments that have the LLM client uninstalled.
        from clinitrace.llm import dispatcher  # noqa: PLC0415
        return dispatcher.triage_rule_kind(unknown, entry)
    except Exception as exc:  # noqa: BLE001
        log.debug("LLM triage skipped: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Aggregation + formatting
# ---------------------------------------------------------------------------


def suggest_rule_kinds(
    unknown: str, entry: dict[str, Any] | None = None
) -> list[Suggestion]:
    """Return a ranked list of suggestions for an unknown rule_kind.

    Each suggestion is (rule_kind, confidence, reason). Sorted by
    confidence descending. Empty list means nothing in the registry has
    any signal at all — at that point the user is referring to a kind
    that genuinely doesn't exist and needs to add it (or fix the typo).

    Combination rule: max(text, shape). We don't average — when one
    signal is strong (typo OR shape match), it should dominate. When both
    are weak we want to know that.
    """
    from clinitrace.rule_kinds import known_rule_kinds  # noqa: PLC0415

    entry = entry or {}
    results: list[Suggestion] = []
    for kind in known_rule_kinds():
        text = _text_score(unknown, kind)
        shape, shape_reason = _shape_score(kind, entry)
        combined = max(text, shape)
        if combined <= 0:
            continue
        parts: list[str] = []
        if text >= 0.6:
            parts.append(f"name {text:.0%} similar")
        if shape > 0:
            parts.append(shape_reason)
        results.append((kind, combined, "; ".join(parts) or f"name {text:.0%} similar"))

    results.sort(key=lambda r: r[1], reverse=True)

    # If the deterministic top suggestion is weak, try the LLM as an
    # escalation. The LLM's suggestion gets boosted (it has access to the
    # rationale, which the deterministic signals do not) and merged so we
    # don't return duplicates.
    if not results or results[0][1] < _STRONG_CONFIDENCE:
        llm = _llm_score(unknown, entry)
        if llm is not None:
            kind, conf, reason = llm
            results = [(k, c, r) for (k, c, r) in results if k != kind]
            results.insert(0, (kind, conf, reason))
            results.sort(key=lambda r: r[1], reverse=True)

    return results


def format_suggestions(unknown: str, suggestions: list[Suggestion]) -> str:
    """Render the ranked list as a multi-line error message.

    Designed for the Pydantic ValidationError surface — every line
    indented under the field name, with the description showing what
    each suggested rule_kind would actually do.
    """
    from clinitrace.rule_kinds import known_rule_kinds  # noqa: PLC0415

    if not suggestions:
        return (
            f"unknown rule_kind {unknown!r}; no close match in the registry. "
            f"Registered kinds: {known_rule_kinds()}. "
            f"If {unknown!r} is a new rule_kind, add it under "
            f"clinitrace/rule_kinds/ and register it in __init__.py."
        )

    top = suggestions[:3]
    header = (
        f"unknown rule_kind {unknown!r}. "
        + ("Did you mean:" if top[0][1] >= _STRONG_CONFIDENCE else "Closest matches (low confidence):")
    )
    lines = [header]
    for kind, conf, reason in top:
        desc = _KIND_DESCRIPTIONS.get(kind, "")
        lines.append(f"  • {kind} ({conf:.0%}, {reason}) — {desc}")
    lines.append(
        f"Full registry: {known_rule_kinds()}. "
        f"Set CLINITRACE_LLM=live for LLM-assisted suggestions when "
        f"text and shape signals are weak."
    )
    return "\n".join(lines)


def triage_unknown_rule_kind(unknown: str, entry: dict[str, Any] | None = None) -> str:
    """One-call entry point used by Pydantic validators.

    Combines all three signals and returns a ready-to-use error string.
    """
    return format_suggestions(unknown, suggest_rule_kinds(unknown, entry))
