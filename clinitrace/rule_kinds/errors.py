"""Shared exception types raised by rule_kind apply_* functions.

These exceptions form part of the contract Verification (V) inspects when
deciding the verdict for a derivation. Catching the wrong type would mask a
real failure; each name signals a specific failure mode.
"""

from __future__ import annotations


class NullInputError(ValueError):
    """Raised when a rule receives a null input and null_handling == 'error'.

    This is the explicit-fail outcome from the null_handling enum (see, e.g.,
    BinNullHandling.ERROR in clinitrace.rule_kinds.bin). It is a subclass of
    ValueError so that callers using the broader contract still catch it, but
    Verification's L1 layer distinguishes it from other ValueError causes.
    """
