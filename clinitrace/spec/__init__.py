"""Spec layer: the YAML-shaped contract between humans and CliniTrace.

The spec is what a clinical analyst writes. It declares each derived variable
by name, its inputs, its rule_kind, a rule_body that may be incomplete or
ambiguous, and a free-text rationale. SR reads it; CG normalizes it; HITL
fills gaps.

Public surface:
  Spec, SpecEntry, load_spec
"""

from clinitrace.spec.loader import load_spec
from clinitrace.spec.model import Spec, SpecEntry

__all__ = ["Spec", "SpecEntry", "load_spec"]
