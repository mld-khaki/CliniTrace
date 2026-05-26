"""Orchestrator-level tests for the R loop and adaptive early-stop.

R is structurally dead in the demo because L1 catches every body shape L_p
would reject. To exercise the loop, these tests monkey-patch the verification
runner so the orchestrator sees a controllable verdict stream while keeping
all other agents and the DAG real.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from clinitrace.agents import orchestrator as orch
from clinitrace.memory import LTM
from clinitrace.spec.model import Spec, SpecEntry
from clinitrace.verification.findings import Finding, Layer, Severity, Verdict


def _failing_verdict(target: str, property_id: str = "P-bin-2") -> Verdict:
    return Verdict.from_findings(
        target,
        [
            Finding(
                layer=Layer.L_P,
                derivation=target,
                property_id=property_id,
                severity=Severity.ERROR,
                message="synthetic-fail",
            )
        ],
    )


def _passing_verdict(target: str) -> Verdict:
    return Verdict(derivation=target, passed=True, findings=[])


def _flag_spec_for_unmapped() -> Spec:
    return Spec(
        derivations=[
            SpecEntry(
                name="RFLAG",
                inputs=["response"],
                rule_kind="flag",
                rule_body={"map": {"responder": "Y", "non_responder": "N"}},
                rationale="x",
            )
        ]
    )


def _dataset() -> pd.DataFrame:
    return pd.DataFrame({"response": ["responder", "non_responder", "responder"]})


def test_r_loop_fires_and_recovers(tmp_path: Path, monkeypatch) -> None:
    """V fails first, R applies the P-flag-3 patch (unmapped_handling='null'),
    V then passes on iteration 1. Verifies the agent_chain reflects R."""
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    verdict_calls = {"count": 0}

    def fake_verify(*, target, rule_kind, body, source, sample):  # type: ignore[no-untyped-def]
        verdict_calls["count"] += 1
        # First call: synthetic failure on P-flag-3. R will patch
        # unmapped_handling -> 'null', which is already the body's default; the
        # patched body re-validates and is passed back to V for iter 1.
        if verdict_calls["count"] == 1:
            return _failing_verdict(target, "P-flag-3")
        return _passing_verdict(target)

    monkeypatch.setattr(orch, "verify_rule_instance", fake_verify)

    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        result = orch.run(
            spec=_flag_spec_for_unmapped(),
            dataset=_dataset(),
            out_dir=out,
            ltm=ltm,
            llm_mode="stub",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm.close()

    assert result.counts["derivations_verified"] == 1
    assert result.counts["refinement_iterations"] == 1
    # Chain: CG -> V (fail) -> R -> V (pass).
    import json

    report = json.loads(
        result.verification_report_path.read_text(encoding="utf-8")
    )
    chain = report["derivations"]["RFLAG"]["agent_chain"]
    assert chain == ["CG", "V", "R", "V"]


def test_adaptive_early_stop_when_body_and_findings_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    """V keeps emitting the same finding; R's patch is a no-op for that body
    shape, so body+findings repeat across iterations. The adaptive early-stop
    must fire before the retry ceiling and the derivation lands UNRESOLVED.
    """
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    verdict_count = {"n": 0}

    def fake_verify(*, target, rule_kind, body, source, sample):  # type: ignore[no-untyped-def]
        verdict_count["n"] += 1
        # Always the same failing finding -> R's patch will be a no-op on
        # subsequent iterations (already applied), so body_hash stops changing.
        return _failing_verdict(target, "P-flag-3")

    monkeypatch.setattr(orch, "verify_rule_instance", fake_verify)

    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        result = orch.run(
            spec=_flag_spec_for_unmapped(),
            dataset=_dataset(),
            out_dir=out,
            ltm=ltm,
            llm_mode="stub",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm.close()

    assert result.counts["derivations_unresolved"] == 1
    # Should have stopped well before the retry ceiling (early-stop fires on
    # iteration 2; ceiling would be 4 V calls).
    assert verdict_count["n"] <= 3, verdict_count

    # Audit trail carries the r_early_stop event.
    trail = (result.run_dir / "audit_trail.jsonl").read_text(encoding="utf-8")
    assert "r_early_stop" in trail


def test_retry_budget_exhaustion(tmp_path: Path, monkeypatch) -> None:
    """Each iteration V emits a different finding (so early-stop never fires),
    R can't patch any of them -> escalates on iteration 0. The node should be
    marked UNRESOLVED with reason mentioning the retry budget / triage gap.
    """
    monkeypatch.setenv("CLINITRACE_LLM", "stub")

    def fake_verify(*, target, rule_kind, body, source, sample):  # type: ignore[no-untyped-def]
        # P-flag-1 has NO _PATCH_RULES entry -> R will escalate the first
        # time it's called, so the loop breaks at iteration 0 with the node
        # UNRESOLVED.
        return _failing_verdict(target, "P-flag-1")

    monkeypatch.setattr(orch, "verify_rule_instance", fake_verify)

    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        result = orch.run(
            spec=_flag_spec_for_unmapped(),
            dataset=_dataset(),
            out_dir=out,
            ltm=ltm,
            llm_mode="stub",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm.close()

    assert result.counts["derivations_unresolved"] == 1
    import json

    report = json.loads(
        result.verification_report_path.read_text(encoding="utf-8")
    )
    rflag_report = report["derivations"]["RFLAG"]
    assert rflag_report["status"] == "unresolved"
    assert "triage" in rflag_report["reason"].lower() or "retry" in rflag_report["reason"].lower()
