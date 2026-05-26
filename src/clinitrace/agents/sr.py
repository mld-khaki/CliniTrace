"""Specification Review (SR) -- _002 section 3.1.

In: a parsed Spec + access to LTM (for ambiguity-signature lookup).
Out: a list of ambiguity findings per entry, each cross-referenced against LTM.

SR does not rewrite the spec. SR produces findings; the human resolves them
through HITL (ambiguity-kind ticket).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clinitrace.llm import SrAmbiguityFinding, call_sr_ambiguity
from clinitrace.memory.ltm import LTM
from clinitrace.spec.model import Spec, SpecEntry


@dataclass(frozen=True)
class SrFinding:
    """Per-entry SR output.

    auto_resolved is True if LTM contained a prior resolution for this entry's
    ambiguity signature (per _002 section 7.3). In that case the LTM resolution
    is applied without a fresh HITL ticket.
    """

    entry_name: str
    ambiguity_signature: str
    ambiguity_class: str
    message: str
    suggested_resolutions: list[str]
    auto_resolved: bool
    ltm_resolution: dict[str, Any] | None
    source_mode: str
    source_model: str | None


def review(spec: Spec, ltm: LTM | None) -> list[SrFinding]:
    """Run SR over every spec entry.

    Order: SR queries LTM by ambiguity_signature *before* asking the LLM (per
    _002 section 7.3). A hit short-circuits the LLM call and is reported as
    auto_resolved=True; the orchestrator skips the HITL ticket and applies the
    stored body_patch directly.
    """
    findings: list[SrFinding] = []
    for entry in spec.derivations:
        finding = _review_one(entry, ltm)
        if finding is not None:
            findings.append(finding)
    return findings


def _review_one(entry: SpecEntry, ltm: LTM | None) -> SrFinding | None:
    sig = entry.ambiguity_signature()
    if ltm is not None:
        hit = ltm.find_ambiguity_resolution(sig)
        if hit is not None:
            return SrFinding(
                entry_name=entry.name,
                ambiguity_signature=sig,
                ambiguity_class="ltm_cached",
                message=f"prior resolution found in LTM (signature {sig})",
                suggested_resolutions=[],
                auto_resolved=True,
                ltm_resolution=hit["resolution"],
                source_mode="ltm",
                source_model=None,
            )

    # Short-circuit when the spec author left ambiguity_notes blank. This
    # mirrors what the stub already does (sr_ambiguity_stub uses the
    # presence of ambiguity_notes as its trigger). Without this gate, live
    # mode burns one Ollama call per entry to almost always come back with
    # "no ambiguity" — particularly painful for auto-generated specs where
    # the same agent wrote both rationale and body, so by construction no
    # gap exists.
    #
    # If a reviewer wants the live LLM to look for gaps even without an
    # explicit ambiguity_notes hint, they can write any non-empty value
    # (e.g. "review for completeness") in Step 3 — the gate above falls
    # through and the LLM call fires.
    if not entry.ambiguity_notes or not entry.ambiguity_notes.strip():
        return None

    llm_finding: SrAmbiguityFinding | None = call_sr_ambiguity(entry.model_dump())
    if llm_finding is None:
        return None

    return SrFinding(
        entry_name=entry.name,
        ambiguity_signature=sig,
        ambiguity_class=llm_finding.ambiguity_class,
        message=llm_finding.message,
        suggested_resolutions=llm_finding.suggested_resolutions,
        auto_resolved=False,
        ltm_resolution=None,
        source_mode=llm_finding.source_mode,
        source_model=llm_finding.source_model,
    )
