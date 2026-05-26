"""Audit / Summarization (A) -- _002 section 3.5 and 8.

A is the sole writer of:
  - audit_trail.jsonl  (append-only event log)
  - lineage records    (per-row, embedded in analysis_ready.parquet)
  - run_summary.md     (human-readable narrative)
  - LTM rule_patterns + ambiguity_resolutions entries (after V passes and HITL
    approves; triage resolutions are NOT auto-promoted)

A does not decide anything: it just records what the Orchestrator tells it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from clinitrace.memory.ltm import LTM


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Audit:
    """Append-only writer for audit trail and final artifacts.

    Construct with the run directory; the audit_trail.jsonl file is opened on
    first event and flushed after each event so a crashed run leaves the
    trail-up-to-the-crash intact.
    """

    def __init__(self, run_dir: Path, run_id: str, ltm: LTM | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trail_path = self.run_dir / "audit_trail.jsonl"
        self.run_id = run_id
        self.ltm = ltm

    # ------------------------------------------------------------------
    # Event stream
    # ------------------------------------------------------------------

    def log(self, event_type: str, **fields: Any) -> None:
        """Append one event to audit_trail.jsonl."""
        record = {
            "ts": _utcnow(),
            "run_id": self.run_id,
            "event_type": event_type,
            **fields,
        }
        with self.trail_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True))
            f.write("\n")

    # ------------------------------------------------------------------
    # Per-row lineage
    # ------------------------------------------------------------------

    def build_lineage_column(
        self,
        df: pd.DataFrame,
        *,
        derivation_records: dict[str, dict[str, Any]],
    ) -> pd.Series:
        """Construct a per-row lineage JSON column.

        derivation_records maps derived-column name -> a JSON-shaped record
        with keys (rule_kind, body_signature, agent_chain, hitl_event_ids,
        ltm_pattern_ref). The lineage value for a given row is a dict
        {col -> per-row record}.
        """
        lineage_payloads = []
        for idx in df.index:
            row_lineage: dict[str, dict[str, Any]] = {}
            for col, rec in derivation_records.items():
                row_lineage[col] = {
                    "value": df.at[idx, col] if col in df.columns else None,
                    "rule_kind": rec["rule_kind"],
                    "body_signature": rec["body_signature"],
                    "agent_chain": rec["agent_chain"],
                    "hitl_event_ids": rec.get("hitl_event_ids", []),
                    "ltm_pattern_ref": rec.get("ltm_pattern_ref"),
                    "source_row_ids": [int(idx)],
                }
            lineage_payloads.append(json.dumps(row_lineage, default=str))
        return pd.Series(lineage_payloads, index=df.index, name="lineage_id")

    # ------------------------------------------------------------------
    # Final artifacts
    # ------------------------------------------------------------------

    def write_dataset(self, df: pd.DataFrame) -> Path:
        """Write analysis_ready.parquet (or .csv if pyarrow isn't available)."""
        parquet_path = self.run_dir / "analysis_ready.parquet"
        try:
            df.to_parquet(parquet_path)
            return parquet_path
        except (ImportError, ValueError):
            csv_path = self.run_dir / "analysis_ready.csv"
            df.to_csv(csv_path, index=False)
            self.log(
                "dataset_format_fallback",
                reason="pyarrow_unavailable_or_failed",
                wrote=str(csv_path.name),
            )
            return csv_path

    def write_verification_report(self, report: dict[str, Any]) -> Path:
        path = self.run_dir / "verification_report.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def write_run_summary(self, body: str) -> Path:
        path = self.run_dir / "run_summary.md"
        path.write_text(body, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # LTM promotion
    # ------------------------------------------------------------------

    def promote_rule_pattern(
        self,
        *,
        rule_kind: str,
        body_signature: str,
        body: dict[str, Any],
        approval_event_id: str | None,
    ) -> None:
        """Write a validated rule pattern to LTM. Idempotent: a second call
        with the same (rule_kind, body_signature) is a no-op."""
        if self.ltm is None:
            return
        self.ltm.write_rule_pattern(
            rule_kind=rule_kind,
            body_signature=body_signature,
            body=body,
            run_id=self.run_id,
            approval_event_id=approval_event_id,
        )
        self.log(
            "ltm_write",
            table="rule_patterns",
            rule_kind=rule_kind,
            body_signature=body_signature,
        )

    def promote_ambiguity_resolution(
        self,
        *,
        signature: str,
        resolution: dict[str, Any],
        event_id: str,
    ) -> None:
        if self.ltm is None:
            return
        self.ltm.write_ambiguity_resolution(
            signature=signature,
            resolution=resolution,
            run_id=self.run_id,
            event_id=event_id,
        )
        self.log(
            "ltm_write",
            table="ambiguity_resolutions",
            signature=signature,
        )

    def record_feedback_event(
        self,
        *,
        event_id: str,
        ticket_kind: str,
        target: str | None,
        options_offered: list[str] | None,
        resolution: dict[str, Any] | None,
        resolved_by: str | None,
        free_text_rationale: str | None,
    ) -> None:
        if self.ltm is None:
            return
        self.ltm.write_feedback_event(
            event_id=event_id,
            ticket_kind=ticket_kind,
            target=target,
            options_offered={"options": options_offered} if options_offered else None,
            resolution=resolution,
            resolved_by=resolved_by,
            free_text_rationale=free_text_rationale,
        )
