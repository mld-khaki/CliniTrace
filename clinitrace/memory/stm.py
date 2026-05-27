"""Short-term memory: in-run workflow state.

Holds the parsed spec, the DAG, per-node status, V findings, R retry history,
and HITL tickets in flight. Persisted to disk as a run directory so a crashed
run can be replayed for audit (not resumed without re-verification).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeStatus(str, Enum):
    """DAG-node lifecycle states."""

    PENDING = "pending"
    AMBIGUOUS = "ambiguous"          # waiting on HITL ambiguity resolution
    AWAITING_APPROVAL = "awaiting_approval"  # waiting on HITL derivation approval
    AWAITING_TRIAGE = "awaiting_triage"      # waiting on HITL triage
    RUNNING = "running"
    VERIFIED = "verified"
    UNRESOLVED = "unresolved"        # final fail (HITL declined, or skipped due to upstream)
    SKIPPED = "skipped"              # an upstream input is unresolved


class RetryRecord(BaseModel):
    """One R iteration. Used by the adaptive early-stop check."""

    model_config = ConfigDict(extra="forbid")

    iteration: int
    body_hash: str
    findings_signature: str  # stable hash of the sorted findings set
    note: str = ""


class NodeState(BaseModel):
    """Per-derivation runtime state, persisted to STM snapshots."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: NodeStatus = NodeStatus.PENDING
    rule_kind: str | None = None
    body_signature: str | None = None
    body: dict[str, Any] | None = None
    ltm_pattern_ref: str | None = None
    ltm_hit: bool = False
    retries: list[RetryRecord] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    hitl_event_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class STM(BaseModel):
    """Run-level workflow state.

    Lives for the duration of one Orchestrator run. Persisted to
    <run_dir>/stm.json after each significant transition so a crashed run can
    be inspected.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    spec_version: str = "1"
    nodes: dict[str, NodeState] = Field(default_factory=dict)
    execution_order: list[str] = Field(default_factory=list)
    llm_mode: str = "stub"

    def ensure_node(self, name: str) -> NodeState:
        if name not in self.nodes:
            self.nodes[name] = NodeState(name=name)
        return self.nodes[name]

    def snapshot(self, run_dir: Path) -> None:
        """Write the current STM to <run_dir>/stm.json."""
        path = run_dir / "stm.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
