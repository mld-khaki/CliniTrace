"""Dispatch SR + CG calls to stub or live (Ollama) backend.

Returns rich-shaped dataclasses so agents do not have to handle two response
shapes. Falls back from live to stub semantics only on transport errors and
logs the fallback for the audit trail; never silently masks an LLM disagreement.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict

from clinitrace.llm import client as ollama
from clinitrace.llm.stubs import (
    cg_normalize_stub,
    spec_augmentation_stub,
    sr_ambiguity_stub,
    triage_rule_kind_stub,
)

log = logging.getLogger("clinitrace.llm")


def current_mode() -> str:
    """Return 'live' or 'stub'."""
    mode = os.environ.get("CLINITRACE_LLM", "stub").lower()
    return "live" if mode == "live" else "stub"


class SrAmbiguityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambiguity_class: str
    message: str
    suggested_resolutions: list[str]
    source_mode: str
    source_model: str | None = None


class CgResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str  # 'match' | 'no_match'
    rule_kind: str | None = None
    body: dict[str, Any] | None = None
    confidence: float | None = None
    reason: str | None = None
    source_mode: str
    source_model: str | None = None


# ---------------------------------------------------------------------------
# SR
# ---------------------------------------------------------------------------

_SR_SYSTEM = """You are the Specification Review agent for CliniTrace, a clinical-data
transformation pipeline. Your job is to inspect ONE spec entry and decide
whether the rule is ambiguous, missing logic, or inconsistent with its
rationale.

Audience for the "message" field: a clinical data manager who has never
read the CliniTrace design document. Write the message as a plain-English
sentence that names the variable and the problem in study-team language.
Do NOT use programming terms ("rule_body", "schema", "null"), do NOT use
snake_case identifiers, and do NOT quote field names from the JSON spec.
Use "blank values" instead of "null", "the rule" instead of "rule_body",
"the value mapping" instead of "the map field".

The "suggested_resolutions" entries are internal option keys -- keep them
snake_case so the system can route them. Each key MUST be one of the
documented options for that ambiguity_class, since the user interface
renders each key as a full sentence from a fixed lookup table.

Respond with strict JSON. If the entry is ambiguous, respond:
  {"ambiguous": true, "ambiguity_class": "<short>", "message": "<one sentence>",
   "suggested_resolutions": ["<opt1>", "<opt2>", ...]}
If the entry is unambiguous, respond:
  {"ambiguous": false}
No prose outside JSON."""


def _live_sr(spec_entry: dict[str, Any]) -> dict[str, Any] | None:
    user = (
        "Spec entry:\n"
        f"{spec_entry!r}\n"
        "Inspect for ambiguity per the system instructions."
    )
    target = spec_entry.get("name", "<unknown>")
    log.info("SR -> Ollama [%s] target=%s", ollama.model_name(), target)
    started = time.monotonic()
    try:
        response = ollama.chat_json(_SR_SYSTEM, user)
    except ollama.OllamaError as exc:
        elapsed = time.monotonic() - started
        log.warning(
            "SR Ollama call FAILED in %.1fs -> falling back to stub (target=%s, reason=%s)",
            elapsed,
            target,
            exc,
        )
        finding = sr_ambiguity_stub(spec_entry)
        if finding is None:
            return None
        finding["_fallback_reason"] = str(exc)
        return finding
    elapsed = time.monotonic() - started
    log.info(
        "SR <- Ollama in %.1fs target=%s ambiguous=%s",
        elapsed,
        target,
        bool(response.get("ambiguous")),
    )
    if not response.get("ambiguous"):
        return None
    return {
        "ambiguity_class": response.get("ambiguity_class", "unspecified"),
        "message": response.get("message", "ambiguity detected"),
        "suggested_resolutions": response.get("suggested_resolutions", []),
    }


def call_sr_ambiguity(spec_entry: dict[str, Any]) -> SrAmbiguityFinding | None:
    """Run SR on one spec entry. Returns a finding or None."""
    mode = current_mode()
    if mode == "live":
        finding = _live_sr(spec_entry)
        model = ollama.model_name()
    else:
        finding = sr_ambiguity_stub(spec_entry)
        model = None
    if finding is None:
        return None
    source_mode = mode
    if mode == "live" and finding.get("_fallback_reason"):
        source_mode = "stub_fallback"
        finding.pop("_fallback_reason", None)
    return SrAmbiguityFinding(
        ambiguity_class=finding["ambiguity_class"],
        message=finding["message"],
        suggested_resolutions=finding.get("suggested_resolutions", []),
        source_mode=source_mode,
        source_model=model,
    )


# ---------------------------------------------------------------------------
# CG
# ---------------------------------------------------------------------------

_CG_SYSTEM = """You are the Code Generation agent for CliniTrace. Your job is to
normalize ONE spec entry into a typed rule instance.

You will be given the entry and the JSON schema of the body class. Respond
with strict JSON. If you can confidently fit the entry into the schema:
  {"outcome": "match", "rule_kind": "<kind>", "body": <dict matching schema>,
   "confidence": <0..1>}
If you cannot:
  {"outcome": "no_match", "reason": "<one sentence>"}
You must NEVER emit raw Python. Bodies that fail the schema downstream are
fatal."""


def _live_cg(spec_entry: dict[str, Any], body_cls: type[BaseModel]) -> dict[str, Any]:
    schema = body_cls.model_json_schema()
    user = (
        f"Body class: {body_cls.__name__}\n"
        f"Schema: {schema!r}\n"
        f"Spec entry: {spec_entry!r}\n"
        "Normalize into the schema."
    )
    target = spec_entry.get("name", "<unknown>")
    log.info(
        "CG -> Ollama [%s] target=%s rule_kind=%s",
        ollama.model_name(),
        target,
        spec_entry.get("rule_kind"),
    )
    started = time.monotonic()
    try:
        response = ollama.chat_json(_CG_SYSTEM, user)
    except ollama.OllamaError as exc:
        elapsed = time.monotonic() - started
        log.warning(
            "CG Ollama call FAILED in %.1fs -> falling back to stub (target=%s, reason=%s)",
            elapsed,
            target,
            exc,
        )
        return cg_normalize_stub(spec_entry, body_cls)
    elapsed = time.monotonic() - started
    log.info(
        "CG <- Ollama in %.1fs target=%s outcome=%s",
        elapsed,
        target,
        response.get("outcome"),
    )
    return response


# ---------------------------------------------------------------------------
# Spec triage (semantic rule_kind guess for an unknown name)
# ---------------------------------------------------------------------------


_TRIAGE_SYSTEM = """You are the Spec Triage assistant for CliniTrace. The user
wrote a rule_kind name that is not in the registered set. Your job is to
read the spec entry's rationale, inputs, and rule_body shape, and decide
which of the REGISTERED rule_kinds best matches the user's intent.

Registered rule_kinds (only these are valid):
  bin        — buckets a numeric column into named categories (edges + labels).
  flag       — maps each input value through a lookup table to a fixed output.
  duration   — computes a numeric delta between two date columns.
  compound   — combines per-column predicates with AND/OR into a binary flag.
  risk_score — walks an ordered ladder of tiers; first match wins.

Respond with strict JSON, no prose outside JSON:
  {"kind": "<one of: bin|flag|duration|compound|risk_score>",
   "confidence": <float in [0, 1]>,
   "reason": "<one short sentence explaining the match>"}

If NO registered kind fits the intent, respond:
  {"kind": null, "confidence": 0.0, "reason": "<one sentence>"}"""


def _live_triage(unknown: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    user = (
        f"Unknown rule_kind: {unknown!r}\n"
        f"Spec entry:\n{entry!r}\n"
        "Which registered rule_kind best matches the author's intent?"
    )
    log.info("Triage -> Ollama [%s] unknown=%r", ollama.model_name(), unknown)
    started = time.monotonic()
    try:
        response = ollama.chat_json(_TRIAGE_SYSTEM, user)
    except ollama.OllamaError as exc:
        log.warning(
            "Triage Ollama call FAILED in %.1fs -> falling back to stub (reason=%s)",
            time.monotonic() - started, exc,
        )
        return triage_rule_kind_stub(unknown, entry)
    elapsed = time.monotonic() - started
    log.info(
        "Triage <- Ollama in %.1fs kind=%s", elapsed, response.get("kind"),
    )
    return response


def triage_rule_kind(unknown: str, entry: dict[str, Any]) -> tuple[str, float, str] | None:
    """Return (rule_kind, confidence, reason) or None.

    Tries the live LLM first if CLINITRACE_LLM=live. On any failure (or in
    stub mode), uses the keyword-matching stub. Result is normalised into
    a (kind, confidence, reason) tuple — the format spec_triage expects.

    Fail-open: any uncaught exception returns None so the caller (validator)
    still has the deterministic suggestions to fall back to.
    """
    try:
        from clinitrace.rule_kinds import known_rule_kinds  # noqa: PLC0415

        mode = current_mode()
        if mode == "live":
            raw = _live_triage(unknown, entry)
        else:
            raw = triage_rule_kind_stub(unknown, entry)

        if not raw:
            return None
        kind = raw.get("kind")
        if not kind or kind not in known_rule_kinds():
            return None
        # Cap LLM confidence at 0.85 — it never gets to claim more certainty
        # than a deterministic shape signature (which can hit 0.95). This
        # keeps shape-driven matches authoritative when they fire.
        conf = float(raw.get("confidence") or 0.0)
        conf = min(conf, 0.85)
        reason = str(raw.get("reason") or "LLM semantic match")
        # Tag the reason so the user can tell where this suggestion came from.
        if mode == "live" and "LLM" not in reason:
            reason = f"LLM (live): {reason}"
        elif mode == "stub" and "stub" not in reason.lower():
            reason = f"LLM (stub): {reason}"
        return (kind, conf, reason)
    except Exception as exc:  # noqa: BLE001
        log.debug("triage_rule_kind aborted: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Spec augmentation (propose extra derivations the deterministic patterns missed)
# ---------------------------------------------------------------------------


_AUGMENT_SYSTEM = """You are the Spec Generator assistant for CliniTrace. The
user uploaded a clinical dataset; deterministic pattern matching already
proposed some derivations from it. Your job: look at the column profile and
the existing proposals, then suggest any clinically useful derivations the
deterministic patterns missed.

Registered rule_kinds (only these are valid):
  bin        — numeric → categorical buckets (edges + labels).
  flag       — categorical → fixed output via a lookup map.
  duration   — delta between two date columns (days/weeks/months/years).
  compound   — boolean AND/OR of per-column predicates → binary label.
  risk_score — ordered tier ladder, first match wins.

Be CONSERVATIVE. Propose at most 2 additional derivations. Only suggest a
derivation when the column profile clearly supports it AND it would be
clinically useful (don't propose AGE_GROUP if the existing list already
has one). If no useful additions, return an empty array.

Each proposal MUST be a complete, structurally-valid spec entry:
  {
    "name": "<UPPER_SNAKE>",
    "inputs": ["<column>", ...],
    "rule_kind": "<one of bin|flag|duration|compound|risk_score>",
    "rule_body": { ... full rule body keyed for the chosen rule_kind ... },
    "rationale": "<one sentence written for a clinical reviewer>"
  }

Respond with strict JSON: {"proposals": [<proposal>, <proposal>, ...]}.
No prose outside JSON. Empty list is fine."""


def _live_spec_augmentation(
    profile_summary: dict[str, Any], existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Live Ollama call. Returns the list of proposal dicts the model
    suggests, or [] on any failure (fail-open — the deterministic baseline
    is always available)."""
    user = (
        "Column profile:\n"
        f"{profile_summary!r}\n\n"
        "Already-proposed derivations:\n"
        f"{[{k: p[k] for k in ('name','rule_kind','inputs')} for p in existing]!r}\n\n"
        "Suggest any clinically useful derivations the deterministic "
        "patterns missed. Empty list is fine."
    )
    log.info("SpecAugment -> Ollama [%s]", ollama.model_name())
    started = time.monotonic()
    try:
        response = ollama.chat_json(_AUGMENT_SYSTEM, user)
    except ollama.OllamaError as exc:
        log.warning(
            "SpecAugment Ollama call FAILED in %.1fs -> returning [] (reason=%s)",
            time.monotonic() - started, exc,
        )
        return []
    elapsed = time.monotonic() - started
    proposals = response.get("proposals") or []
    log.info(
        "SpecAugment <- Ollama in %.1fs proposals=%d", elapsed, len(proposals),
    )
    return proposals if isinstance(proposals, list) else []


def call_spec_augmentation(
    profile_summary: dict[str, Any], existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Public entry — returns extra proposal dicts (NOT yet validated).

    Stub mode returns []. Live mode calls the model. Caller is expected to
    validate each result against SpecEntry before adding it to the user's
    review list — the LLM may hallucinate columns or rule_kinds, and the
    validation step is where that gets caught.
    """
    if current_mode() == "live":
        return _live_spec_augmentation(profile_summary, existing)
    return spec_augmentation_stub(profile_summary, existing)


def call_cg_normalize(
    spec_entry: dict[str, Any], body_cls: type[BaseModel]
) -> CgResult:
    """Normalize one spec entry into a typed rule instance."""
    mode = current_mode()
    if mode == "live":
        raw = _live_cg(spec_entry, body_cls)
        model = ollama.model_name()
    else:
        raw = cg_normalize_stub(spec_entry, body_cls)
        model = None

    outcome = raw.get("outcome")
    if outcome == "match":
        return CgResult(
            outcome="match",
            rule_kind=raw.get("rule_kind") or spec_entry["rule_kind"],
            body=raw.get("body") or {},
            confidence=float(raw.get("confidence", 1.0)),
            source_mode=mode,
            source_model=model,
        )
    return CgResult(
        outcome="no_match",
        reason=raw.get("reason") or "CG returned no_match",
        source_mode=mode,
        source_model=model,
    )
