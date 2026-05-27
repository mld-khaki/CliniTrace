"""YAML loader for Spec.

The YAML shape mirrors the Pydantic model 1:1. Example:

    version: "1"
    derivations:
      - name: AGE_GROUP
        inputs: [age]
        rule_kind: bin
        rule_body:
          edges: [18, 65]
          labels: [minor, adult, senior]
        rationale: "Standard adult-stratum binning."
      - name: RESPONSE_FLAG
        inputs: [response]
        rule_kind: flag
        rule_body:
          map: {responder: "Y", non_responder: "N"}
        rationale: "Map response to a binary flag."
        ambiguity_notes: "Behaviour for response == 'unknown' is not defined."
"""

from __future__ import annotations

from pathlib import Path

import yaml

from clinitrace.spec.model import Spec


def load_spec(path: str | Path) -> Spec:
    """Load and validate a spec YAML file. Raises pydantic.ValidationError on
    structural problems and yaml.YAMLError on parse errors."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"spec at {p} did not load as a mapping; got {type(raw).__name__}"
        )
    return Spec.model_validate(raw)
