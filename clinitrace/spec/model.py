"""Pydantic models for the input specification (_002 section 2.2).

A spec is a list of SpecEntry. The rule_body is intentionally `dict[str, Any]`
at this layer: the human writes a possibly-ambiguous dict, SR flags
ambiguity, CG normalizes the dict into a typed body instance (BinBody,
FlagBody, ...). Strict typing at the spec layer would prevent SR/CG from
ever being interesting.

Schema invariants enforced here:
  - rule_kind is one of the registered names.
  - inputs is non-empty.
  - name is a non-empty identifier (loose: any non-blank string).
  - duplicate names across entries are rejected at Spec level.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinitrace.rule_kinds import known_rule_kinds


class SpecEntry(BaseModel):
    """One declared derived variable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., min_length=1)
    inputs: list[str] = Field(..., min_length=1)
    rule_kind: str
    rule_body: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    ambiguity_notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def triage_rule_kind(cls, data: Any) -> Any:
        """Intercept unknown rule_kinds BEFORE per-field validation runs.

        Running here (mode='before') instead of in a field_validator on
        rule_kind lets the triage agent see the full entry — inputs,
        rule_body, rationale — and use shape + (optionally) LLM signals to
        suggest the most likely match. A field_validator on rule_kind only
        has access to fields declared earlier (name, inputs), which would
        cut off the most useful triage signals.

        When the rule_kind IS registered, this is a no-op and the normal
        Pydantic flow proceeds. When it isn't, we raise with the agent's
        ranked suggestion list as the error message.
        """
        if not isinstance(data, dict):
            return data
        rk = data.get("rule_kind")
        if isinstance(rk, str) and rk not in known_rule_kinds():
            # Lazy import — keeps the spec module's import graph small and
            # avoids any chance of a circular import via agents → llm → spec.
            from clinitrace.agents.spec_triage import triage_unknown_rule_kind
            raise ValueError(triage_unknown_rule_kind(rk, data))
        return data

    @field_validator("rule_kind")
    @classmethod
    def rule_kind_registered(cls, v: str) -> str:
        # Backstop for callers that construct SpecEntry directly (bypassing
        # the YAML loader and therefore the model_validator above). Falls
        # back to the simple error so direct-construction paths still see
        # a clear message even if spec_triage is unavailable.
        if v not in known_rule_kinds():
            raise ValueError(
                f"unknown rule_kind {v!r}; "
                f"registered: {known_rule_kinds()}"
            )
        return v

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must be non-blank")
        return v

    def ambiguity_signature(self) -> str:
        """Canonical hash of (name, rationale, ambiguity_notes).

        Used as the LTM key for ambiguity_resolutions. A new run with the same
        name + rationale + ambiguity_notes hits the prior resolution.
        """
        canonical = json.dumps(
            {
                "name": self.name,
                "rationale": self.rationale,
                "ambiguity_notes": self.ambiguity_notes or "",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class Spec(BaseModel):
    """The full specification: a list of derivations plus minimal metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "1"
    derivations: list[SpecEntry] = Field(..., min_length=1)

    @model_validator(mode="after")
    def names_unique(self) -> Spec:
        names = [d.name for d in self.derivations]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate derivation names: {dupes!r}")
        return self

    def by_name(self, name: str) -> SpecEntry:
        for entry in self.derivations:
            if entry.name == name:
                return entry
        raise KeyError(f"no derivation named {name!r}")
