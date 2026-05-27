"""Tests for orchestrator branches that the demo doesn't exercise:
cycle detection, dataset schema mismatch, and downstream-skip on upstream
failure.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from clinitrace.agents import orchestrator as orch
from clinitrace.memory import LTM
from clinitrace.spec.model import Spec, SpecEntry


def _trivial_dataset() -> pd.DataFrame:
    return pd.DataFrame({"age": [10, 30, 70], "response": ["responder", "non_responder", "responder"]})


def _bin_entry(name: str, source: str) -> SpecEntry:
    return SpecEntry(
        name=name,
        inputs=[source],
        rule_kind="bin",
        rule_body={"edges": [18, 65], "labels": ["minor", "adult", "senior"]},
        rationale="standard age binning",
    )


# ---------------------------------------------------------------------------
# Dataset schema mismatch (failure mode #6)
# ---------------------------------------------------------------------------


def test_dataset_missing_source_column_fails_pre_dag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    spec = Spec(
        derivations=[
            SpecEntry(
                name="LAB_FLAG",
                inputs=["lab_value"],
                rule_kind="flag",
                rule_body={"map": {"high": "H", "low": "L"}},
                rationale="binarize lab value",
            )
        ]
    )
    # Dataset is missing lab_value.
    dataset = pd.DataFrame({"age": [10, 30]})
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        with pytest.raises(orch.DatasetValidationError) as exc:
            orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=out,
                ltm=ltm,
                llm_mode="stub",
                inbox_poll_interval=0.01,
                inbox_poll_timeout=0.5,
            )
        assert "lab_value" in str(exc.value)
    finally:
        ltm.close()


def test_dataset_missing_body_referenced_column_fails_pre_dag(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    spec = Spec(
        derivations=[
            SpecEntry(
                name="TREATMENT_DURATION",
                inputs=["treatment_start_date"],
                rule_kind="duration",
                rule_body={
                    "start_column": "treatment_start_date",
                    "end_column": "visit_date",
                    "unit": "days",
                },
                rationale="days from treatment start to visit",
            )
        ]
    )
    dataset = pd.DataFrame({"treatment_start_date": ["2026-01-01"]})
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        with pytest.raises(orch.DatasetValidationError) as exc:
            orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=out,
                ltm=ltm,
                llm_mode="stub",
                inbox_poll_interval=0.01,
                inbox_poll_timeout=0.5,
            )
        assert "visit_date" in str(exc.value)
    finally:
        ltm.close()


def test_dataset_check_logs_to_audit_trail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    spec = Spec(
        derivations=[_bin_entry("AGE_GROUP", "weight")],  # source col not in dataset
    )
    dataset = _trivial_dataset()
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        with pytest.raises(orch.DatasetValidationError):
            orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=out,
                ltm=ltm,
                llm_mode="stub",
                inbox_poll_interval=0.01,
                inbox_poll_timeout=0.5,
            )
    finally:
        ltm.close()
    # The run_dir exists and audit_trail.jsonl carries the dataset_check_failed event.
    run_dirs = list(out.glob("run-*"))
    assert len(run_dirs) == 1
    trail = (run_dirs[0] / "audit_trail.jsonl").read_text(encoding="utf-8")
    assert "dataset_check_failed" in trail


# ---------------------------------------------------------------------------
# Cycle detection (failure mode #5)
# ---------------------------------------------------------------------------


def test_spec_cycle_is_rejected_at_planning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    # A depends on B; B depends on A -> cycle.
    spec = Spec(
        derivations=[
            SpecEntry(
                name="A",
                inputs=["B"],
                rule_kind="bin",
                rule_body={"edges": [0], "labels": ["lo", "hi"]},
                rationale="x",
            ),
            SpecEntry(
                name="B",
                inputs=["A"],
                rule_kind="bin",
                rule_body={"edges": [0], "labels": ["lo", "hi"]},
                rationale="x",
            ),
        ]
    )
    dataset = _trivial_dataset()
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        with pytest.raises(ValueError) as exc:
            orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=out,
                ltm=ltm,
                llm_mode="stub",
                inbox_poll_interval=0.01,
                inbox_poll_timeout=0.5,
            )
        assert "cycle" in str(exc.value).lower()
    finally:
        ltm.close()
    # dag_plan_failed event was logged.
    trail = (next(out.glob("run-*")) / "audit_trail.jsonl").read_text(encoding="utf-8")
    assert "dag_plan_failed" in trail


def test_spec_reference_to_unknown_column_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    # NOT_A_COLUMN is neither a source column nor a declared derivation.
    spec = Spec(
        derivations=[
            SpecEntry(
                name="X",
                inputs=["NOT_A_COLUMN"],
                rule_kind="bin",
                rule_body={"edges": [0], "labels": ["lo", "hi"]},
                rationale="x",
            )
        ]
    )
    dataset = _trivial_dataset()
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        # Dataset pre-check fires first (NOT_A_COLUMN is not in the dataset and
        # is not a declared derivation -> looks like a missing source).
        with pytest.raises(orch.DatasetValidationError):
            orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=out,
                ltm=ltm,
                llm_mode="stub",
                inbox_poll_interval=0.01,
                inbox_poll_timeout=0.5,
            )
    finally:
        ltm.close()


# ---------------------------------------------------------------------------
# Downstream skip on upstream unresolved
# ---------------------------------------------------------------------------


def test_downstream_skipped_when_upstream_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    """If an upstream derivation fails CG (no_match), every derivation that
    transitively depends on it should be SKIPPED with the right report shape.

    Construction: UPSTREAM is a `flag` rule_kind with a rule_body that has no
    `map` field. Pydantic L1 rejects it -> CG returns no_match -> UPSTREAM is
    UNRESOLVED. DOWNSTREAM has UPSTREAM in its inputs -> skipped.
    """
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    spec = Spec(
        derivations=[
            SpecEntry(
                name="UPSTREAM",
                inputs=["response"],
                rule_kind="flag",
                rule_body={},  # missing required `map` -> body validation fails
                rationale="x",
            ),
            SpecEntry(
                name="DOWNSTREAM",
                inputs=["UPSTREAM"],
                rule_kind="bin",
                rule_body={"edges": [0], "labels": ["lo", "hi"]},
                rationale="x",
            ),
        ]
    )
    dataset = _trivial_dataset()
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        result = orch.run(
            spec=spec,
            dataset=dataset,
            out_dir=out,
            ltm=ltm,
            llm_mode="stub",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm.close()

    assert result.counts["derivations_verified"] == 0
    assert result.counts["derivations_unresolved"] == 2

    report_path = result.verification_report_path
    import json

    report = json.loads(report_path.read_text(encoding="utf-8"))
    derivations = report["derivations"]
    assert derivations["UPSTREAM"]["status"] == "unresolved"
    assert derivations["DOWNSTREAM"]["status"] == "skipped"
    assert "upstream" in derivations["DOWNSTREAM"]["reason"].lower()


def test_body_referenced_derived_column_drives_dag_order(
    tmp_path: Path, monkeypatch
) -> None:
    """Multi-source bodies participate in dependency planning even when the
    human-facing inputs list omits the derived dependency."""
    monkeypatch.setenv("CLINITRACE_LLM", "stub")
    spec = Spec(
        derivations=[
            SpecEntry(
                name="AA_DOWNSTREAM",
                inputs=["age"],
                rule_kind="compound",
                rule_body={
                    "conditions": [
                        {"column": "ZZ_UPSTREAM", "op": "==", "value": "Y"}
                    ],
                    "true_value": "Y",
                    "false_value": "N",
                    "null_handling": "false",
                },
                rationale="depends on the upstream response flag",
            ),
            SpecEntry(
                name="ZZ_UPSTREAM",
                inputs=["response"],
                rule_kind="flag",
                rule_body={
                    "map": {"responder": "Y", "non_responder": "N"},
                    "unmapped_handling": "null",
                },
                rationale="response flag",
            ),
        ]
    )
    dataset = _trivial_dataset()
    out = tmp_path / "out"
    out.mkdir()
    ltm = LTM(tmp_path / "ltm.db")
    try:
        result = orch.run(
            spec=spec,
            dataset=dataset,
            out_dir=out,
            ltm=ltm,
            llm_mode="stub",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm.close()

    assert result.stm.execution_order == ["ZZ_UPSTREAM", "AA_DOWNSTREAM"]
    assert result.counts["derivations_verified"] == 2


def test_ambiguity_signature_changes_when_rule_body_changes() -> None:
    base = SpecEntry(
        name="RESPONSE_FLAG",
        inputs=["response"],
        rule_kind="flag",
        rule_body={"map": {"responder": "Y", "non_responder": "N"}},
        rationale="map response to a binary flag",
        ambiguity_notes="unknown response value is not specified",
    )
    changed = base.model_copy(
        update={"rule_body": {"map": {"responder": "1", "non_responder": "0"}}}
    )

    assert base.ambiguity_signature() != changed.ambiguity_signature()
