"""Per-rule_kind property suites for L_p.

Each module exposes a `run(target, body, apply_fn) -> list[Finding]` function
that exercises the contracts from property_test_contracts.md against
deterministic synthetic inputs. Deterministic-by-design so V outputs are
reproducible (same rule instance + same V version -> same findings).

The dispatcher selects the right suite by rule_kind name.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from clinitrace.verification.findings import Finding
from clinitrace.verification.properties import bin as bin_props
from clinitrace.verification.properties import flag as flag_props

PropertySuite = Callable[[str, BaseModel, Callable], list[Finding]]

SUITES: dict[str, PropertySuite] = {
    "bin": bin_props.run,
    "flag": flag_props.run,
}


def run_suite(
    rule_kind: str,
    target: str,
    body: BaseModel,
    apply_fn: Callable,
) -> list[Finding]:
    """Run the property suite for a rule_kind. Empty list if no suite exists."""
    if rule_kind not in SUITES:
        return []
    return SUITES[rule_kind](target, body, apply_fn)
