"""Deterministic stub responses for SR and CG. _002 Appendix A.

Stubs are intentionally simple: they implement the structural slice of each
agent's behaviour, enough for the demo + CI runs to exercise the full pipeline
without an LLM. The stub-vs-live decision is logged in the audit trail.

SR stub: flags entries that carry a non-empty `ambiguity_notes` field. A real
LLM would catch more cases (e.g. structural ambiguity in the rule_body), but
the demo spec uses `ambiguity_notes` as the explicit ambiguity marker so the
stub is sufficient.

CG stub: attempts to validate the raw rule_body against the registered body
class. If it validates -> typed body instance, confidence=1. If validation
fails -> no_match (with the validation error as the reason).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError


def sr_ambiguity_stub(spec_entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return a structural ambiguity finding, or None.

    Heuristic: a non-empty `ambiguity_notes` field is the explicit ambiguity
    marker. The stub picks rule_kind-aware resolution options so the demo's
    chosen_option ("flag_unknown_as_U") is always one of the offered options.
    A real LLM would catch more cases (rationale-vs-body structural conflict,
    missing edge handling) -- the stub covers the demo + the next-most-likely
    flag/bin cases.
    """
    notes = spec_entry.get("ambiguity_notes")
    if not notes:
        return None

    rule_kind = spec_entry.get("rule_kind", "")
    notes_lower = str(notes).lower()

    if rule_kind == "flag" and ("unknown" in notes_lower or "unmapped" in notes_lower):
        return {
            "ambiguity_class": "unmapped_value_undefined",
            "message": notes,
            "suggested_resolutions": [
                "treat_unmapped_as_null",
                "flag_unknown_as_U",
                "raise_on_unmapped",
            ],
        }
    if rule_kind == "bin" and ("null" in notes_lower or "missing" in notes_lower):
        return {
            "ambiguity_class": "null_handling_undefined",
            "message": notes,
            "suggested_resolutions": [
                "treat_null_as_null",
                "treat_null_as_label",
                "raise_on_null",
            ],
        }
    return {
        "ambiguity_class": "rationale_undefined",
        "message": notes,
        "suggested_resolutions": ["accept_default", "modify_body", "reject"],
    }


def triage_rule_kind_stub(unknown: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Stub for the spec-triage LLM call. Keyword-match the rationale to a
    rule_kind so stub mode is genuinely useful, not a no-op.

    Returns {kind, confidence, reason} or None if no keyword fires.

    Why a keyword stub here: in stub mode we want the architectural slot
    exercised (so a CI run shows "LLM-style escalation happened"), but
    without paying for a model call. Live mode replaces these heuristics
    with the actual model's read of the rationale.
    """
    rationale = " ".join(
        str(entry.get(k, "")) for k in ("rationale", "ambiguity_notes", "name")
    ).lower()
    if not rationale.strip():
        return None

    # Order matters: more specific patterns first so 'bucket of days' lands
    # on duration (not bin).
    patterns: list[tuple[str, list[str], str]] = [
        ("duration", ["days between", "weeks between", "duration", "delta", "elapsed", "days from"],
         "rationale mentions a time delta between dates"),
        ("risk_score", ["tier", "ladder", "risk group", "risk_group", "stratify by", "first match"],
         "rationale describes an ordered tier ladder"),
        ("compound", ["inclusion criter", "all of", "any of", "and/or", "population", "analysis pop"],
         "rationale describes a boolean combination of conditions"),
        ("bin", ["bucket", "stratif", "categor", "age group", "binning", "cut point"],
         "rationale describes numeric bucketing"),
        ("flag", ["map ", "mapping", "recode", "label", "respond"],
         "rationale describes a value mapping"),
    ]
    for kind, needles, reason in patterns:
        if any(needle in rationale for needle in needles):
            return {
                "kind": kind,
                "confidence": 0.75,
                "reason": f"LLM (stub): {reason}",
            }
    return None


def spec_augmentation_stub(
    profile_summary: dict[str, Any],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stub for the LLM-augmentation step of spec generation.

    Returns a list of additional proposal dicts the deterministic patterns
    might have missed. In stub mode, this returns an empty list — being
    honest beats hallucinating a proposal that didn't come from data.

    Live mode (see dispatcher._live_spec_augmentation) calls the model with
    the column profile + already-proposed derivations and asks for any
    obvious additions.
    """
    # Intentionally empty in stub mode: the deterministic proposer already
    # covers the well-known clinical idioms. Adding fake "stub LLM"
    # proposals would muddy what the indicator is honestly showing.
    return []


def cg_normalize_stub(
    spec_entry: dict[str, Any], body_cls: type[BaseModel]
) -> dict[str, Any]:
    """Try to build a typed body from the spec entry's rule_body.

    Returns either:
      {"outcome": "match", "rule_kind": ..., "body": <validated_dict>, "confidence": 1.0}
      {"outcome": "no_match", "reason": "<pydantic validation error>"}
    """
    rule_body = spec_entry.get("rule_body") or {}
    rule_kind = spec_entry["rule_kind"]
    try:
        instance = body_cls.model_validate(rule_body)
    except ValidationError as exc:
        return {
            "outcome": "no_match",
            "reason": f"body did not validate against {body_cls.__name__}: {exc.errors()!r}",
        }
    return {
        "outcome": "match",
        "rule_kind": rule_kind,
        "body": instance.model_dump(mode="json"),
        "confidence": 1.0,
    }
