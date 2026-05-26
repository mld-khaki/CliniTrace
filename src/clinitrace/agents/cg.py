"""Code Generation (CG) -- _002 section 3.2.

In: one annotated SpecEntry (after SR + any HITL ambiguity resolutions), plus
   LTM for (rule_kind, body_signature) lookup.
Out: a typed rule instance OR a `no_match` outcome. NEVER raw code.

CG never executes a derivation, never calls V, and never emits Python. Its
sole job is to convert a possibly-loose spec entry into a body the registered
apply function can run.

LTM lookup ordering (_002 section 7.3):

  1. Try to canonicalize the spec body directly via body_cls.model_validate.
     If it validates, compute the canonical body_signature from the validated
     body and look it up in LTM by (rule_kind, body_signature). HIT -> skip
     the LLM call entirely; the cached body is the result. This is the
     fast path that makes warm-LTM runs essentially free in live mode.
  2. If direct validation failed (body has gaps after HITL) OR LTM missed:
     dispatch to the LLM (stub in offline mode, Ollama in live mode).
  3. Re-validate the LLM body, compute its canonical signature, and check
     LTM one more time in case the LLM normalized into a known-good body.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from clinitrace.llm import CgResult, call_cg_normalize
from clinitrace.memory.ltm import LTM
from clinitrace.rule_kinds import get as get_rule_kind
from clinitrace.spec.model import SpecEntry


@dataclass(frozen=True)
class CgOutput:
    """CG's per-entry result.

    outcome: 'match' | 'no_match'.
    rule_kind: the rule_kind name (always set when outcome=='match').
    body: typed body instance (a Pydantic BaseModel) -- always set when match.
    body_signature: canonical hash of body, for LTM key.
    ltm_hit: True if the (rule_kind, body_signature) was already in LTM.
    ltm_pattern_ref: LTM row reference (body_signature) when ltm_hit is True.
    confidence: from the LLM (1.0 if stub).
    reason: filled when outcome=='no_match'.
    source_mode / source_model: where the body came from (audit trail).
        'ltm'           -> body came from LTM, LLM skipped.
        'stub' / 'live' -> body came from the dispatcher.
        'stub_fallback' -> live LLM failed, dispatcher fell back to stub.
    """

    outcome: str
    rule_kind: str | None
    body: BaseModel | None
    body_signature: str | None
    ltm_hit: bool
    ltm_pattern_ref: str | None
    confidence: float | None
    reason: str | None
    source_mode: str
    source_model: str | None


def _canonical_signature(instance: BaseModel) -> str:
    """Hash of the validated body's canonical JSON dump.

    Stable across runs and across stub/live modes as long as Pydantic returns
    the same `model_dump(mode="json")` for equivalent inputs. This is the
    only signature shape written to LTM.
    """
    canonical = json.dumps(
        instance.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def normalize(entry: SpecEntry, ltm: LTM | None) -> CgOutput:
    """Normalize one spec entry. See module docstring for the ordering."""
    body_cls = get_rule_kind(entry.rule_kind).body_cls

    direct_instance: BaseModel | None
    direct_sig: str | None
    try:
        direct_instance = body_cls.model_validate(entry.rule_body)
        direct_sig = _canonical_signature(direct_instance)
    except Exception:
        direct_instance = None
        direct_sig = None

    if ltm is not None and direct_sig is not None:
        hit = ltm.find_rule_pattern(entry.rule_kind, direct_sig)
        if hit is not None:
            assert direct_instance is not None
            return CgOutput(
                outcome="match",
                rule_kind=entry.rule_kind,
                body=direct_instance,
                body_signature=direct_sig,
                ltm_hit=True,
                ltm_pattern_ref=direct_sig,
                confidence=1.0,
                reason=None,
                source_mode="ltm",
                source_model=None,
            )

    # No LTM hit (or no canonical sig). Dispatch to the LLM.
    result: CgResult = call_cg_normalize(entry.model_dump(), body_cls)
    if result.outcome != "match" or result.body is None:
        return CgOutput(
            outcome="no_match",
            rule_kind=None,
            body=None,
            body_signature=None,
            ltm_hit=False,
            ltm_pattern_ref=None,
            confidence=None,
            reason=result.reason or "CG returned no_match",
            source_mode=result.source_mode,
            source_model=result.source_model,
        )

    try:
        instance = body_cls.model_validate(result.body)
    except Exception as exc:
        return CgOutput(
            outcome="no_match",
            rule_kind=None,
            body=None,
            body_signature=None,
            ltm_hit=False,
            ltm_pattern_ref=None,
            confidence=None,
            reason=f"CG body did not re-validate: {exc!r}",
            source_mode=result.source_mode,
            source_model=result.source_model,
        )

    body_sig = _canonical_signature(instance)
    ltm_hit = False
    ltm_ref: str | None = None
    if ltm is not None:
        hit = ltm.find_rule_pattern(entry.rule_kind, body_sig)
        if hit is not None:
            ltm_hit = True
            ltm_ref = body_sig

    return CgOutput(
        outcome="match",
        rule_kind=entry.rule_kind,
        body=instance,
        body_signature=body_sig,
        ltm_hit=ltm_hit,
        ltm_pattern_ref=ltm_ref,
        confidence=result.confidence,
        reason=None,
        source_mode=result.source_mode,
        source_model=result.source_model,
    )


def merge_resolution_into_entry(
    entry: SpecEntry, body_patch: dict[str, Any]
) -> SpecEntry:
    """Return a new SpecEntry with rule_body merged with body_patch.

    Used by the Orchestrator after a HITL ambiguity resolution: the resolution
    carries a body_patch that fills in the missing fields, and CG re-runs on
    the merged entry.
    """
    if not body_patch:
        return entry
    merged = {**entry.rule_body, **body_patch}
    return entry.model_copy(update={"rule_body": merged})
