"""End-to-end integration test: run the demo through the full pipeline in
stub LLM mode and assert on the produced artifacts.

This is the load-bearing test that the prototype is wired correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from clinitrace.agents import orchestrator as orch
from clinitrace.memory import LTM
from clinitrace.spec import load_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"


def test_demo_runs_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")

    spec = load_spec(EXAMPLES / "demo_spec.yaml")
    dataset = pd.read_csv(EXAMPLES / "demo_data.csv")

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
            replay_path=EXAMPLES / "demo_resolutions.json",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=2.0,
        )
    finally:
        ltm.close()

    # All five derivations should verify cleanly.
    assert result.counts["derivations_verified"] == 5, result.counts
    assert result.counts["derivations_unresolved"] == 0
    # SR flagged the RESPONSE_FLAG ambiguity; one HITL ticket opened and
    # auto-resolved from the replay file.
    assert result.counts["sr_findings"] == 1
    assert result.counts["hitl_tickets_opened"] == 1
    # LTM grew by one ambiguity_resolutions row and five rule_patterns rows
    # (one per derivation: AGE_GROUP, RESPONSE_FLAG, TREATMENT_DURATION, ANALYSIS_POP_FLAG, RISK_GROUP).
    assert result.ltm_writes["ambiguity_resolutions"] == 1
    assert result.ltm_writes["rule_patterns"] == 5

    # The audit trail is a JSONL file with at least the run_start, run_complete
    # events plus per-stage entries.
    trail_path = result.run_dir / "audit_trail.jsonl"
    assert trail_path.exists()
    events = [json.loads(line) for line in trail_path.read_text(encoding="utf-8").splitlines()]
    event_types = {e["event_type"] for e in events}
    assert {"run_start", "sr_complete", "dag_planned", "run_complete"}.issubset(event_types)
    # A HITL ticket was opened AND resolved.
    assert any(e["event_type"] == "hitl_open" for e in events)
    assert any(e["event_type"] == "hitl_resolved" for e in events)

    # HITL inbox/outbox files live INSIDE the run_dir, not at a shared staging path.
    assert (result.run_dir / "hitl" / "inbox").exists()
    assert (result.run_dir / "hitl" / "outbox").exists()
    inbox_files = list((result.run_dir / "hitl" / "inbox").glob("*.ticket.json"))
    outbox_files = list((result.run_dir / "hitl" / "outbox").glob("*.resolution.json"))
    assert len(inbox_files) == 1
    assert len(outbox_files) == 1

    # Output dataset has the derived columns and a lineage_id column.
    out_path = result.output_dataset_path
    out_df = pd.read_parquet(out_path) if out_path.suffix == ".parquet" else pd.read_csv(out_path)
    assert {"AGE_GROUP", "RESPONSE_FLAG", "TREATMENT_DURATION", "ANALYSIS_POP_FLAG", "RISK_GROUP", "lineage_id"}.issubset(out_df.columns)
    # 'unknown' rows should have been flagged 'U' per the replay resolution.
    mask = dataset["response"] == "unknown"
    assert (out_df.loc[mask, "RESPONSE_FLAG"] == "U").all()
    # 'minor' / 'adult' / 'senior' partition is non-trivial.
    assert set(out_df["AGE_GROUP"].unique()) == {"minor", "adult", "senior"}


def test_second_run_hits_ltm(tmp_path: Path, monkeypatch) -> None:
    """A second run on the same spec should auto-resolve ambiguity from LTM
    (zero new HITL tickets) and skip the rule_patterns LTM write."""
    monkeypatch.setenv("CLINITRACE_LLM", "stub")

    spec = load_spec(EXAMPLES / "demo_spec.yaml")
    dataset = pd.read_csv(EXAMPLES / "demo_data.csv")

    out = tmp_path / "out"
    out.mkdir()
    db = tmp_path / "ltm.db"

    # First run: cold LTM.
    ltm1 = LTM(db)
    try:
        orch.run(
            spec=spec,
            dataset=dataset,
            out_dir=out,
            ltm=ltm1,
            llm_mode="stub",
            replay_path=EXAMPLES / "demo_resolutions.json",
            inbox_poll_interval=0.01,
            inbox_poll_timeout=2.0,
        )
    finally:
        ltm1.close()

    # Second run: warm LTM. Note the replay file is intentionally NOT supplied;
    # if LTM auto-resolution fails, the inbox poll will time out.
    ltm2 = LTM(db)
    try:
        result = orch.run(
            spec=spec,
            dataset=dataset,
            out_dir=out,
            ltm=ltm2,
            llm_mode="stub",
            replay_path=None,
            inbox_poll_interval=0.01,
            inbox_poll_timeout=0.5,
        )
    finally:
        ltm2.close()

    assert result.counts["derivations_verified"] == 5
    assert result.counts["sr_findings"] == 1
    assert result.counts["sr_auto_resolved"] == 1
    assert result.counts["hitl_tickets_opened"] == 0
    # No new LTM writes (everything already there).
    assert result.ltm_writes["ambiguity_resolutions"] == 0
    assert result.ltm_writes["rule_patterns"] == 0
    # CG hit LTM for all five derivations on the second run.
    assert result.counts["cg_ltm_hits"] == 5


def test_no_ltm_reports_zero_ltm_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLINITRACE_LLM", "stub")

    spec = load_spec(EXAMPLES / "demo_spec.yaml")
    dataset = pd.read_csv(EXAMPLES / "demo_data.csv")

    out = tmp_path / "out"
    out.mkdir()

    result = orch.run(
        spec=spec,
        dataset=dataset,
        out_dir=out,
        ltm=None,
        llm_mode="stub",
        replay_path=EXAMPLES / "demo_resolutions.json",
        inbox_poll_interval=0.01,
        inbox_poll_timeout=2.0,
    )

    assert result.counts["derivations_verified"] == 5
    assert result.ltm_writes == {"rule_patterns": 0, "ambiguity_resolutions": 0}
    assert not (tmp_path / "ltm.db").exists()
