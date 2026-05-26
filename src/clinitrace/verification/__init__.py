"""Verification (V) -- _002 sections 3.3 and 6.

V is fully deterministic; no LLM participates in the fail/pass gate. It runs
three layers per derivation, fail-closed at each:

  - L1 deterministic: schema, type, range, nullability, controlled vocabulary,
    idempotence on re-run.
  - L2 spec-coverage: every value in the input domain has a defined output. No
    implicit defaults. (Deferred to the next slice; covered partially by L_p.)
  - L_p property suite: per-rule_kind invariants (3-5 per kind), exercised
    against deterministic synthetic batches.

The public entry point is `verify_rule_instance`. Agents must call this; they
do not run individual layers themselves.
"""

from clinitrace.verification.findings import Finding, Verdict
from clinitrace.verification.runner import verify_rule_instance

__all__ = ["Finding", "Verdict", "verify_rule_instance"]
