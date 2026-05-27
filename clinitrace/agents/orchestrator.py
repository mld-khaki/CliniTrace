"""Orchestrator / DAG runner (O) -- _002 sections 3.6 and 4.

The Orchestrator is the sole loop authority. Agents emit structured results;
agents do not call each other. The Orchestrator:

  1. Runs the pre-DAG SR step over every spec entry.
  2. Opens HITL ambiguity tickets for non-auto-resolved findings; collects
     body_patches and merges them into spec entries.
  3. Builds the variable graph + topological sort; rejects cycles.
  4. For each derivation in topo order, runs the per-derivation pipeline:
     CG -> (HITL approval if no LTM match)? -> execute -> V -> (R + V)*  -> HITL triage?
  5. Hands final state to Audit for lineage + summary + LTM promotion.

MVP scope: only the ambiguity HITL kind is exercised. Derivation-approval and
triage paths mark the node UNRESOLVED with a structured finding; the
architecture supports them and the next slice wires the file inbox/outbox
through them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("clinitrace.orch")

from clinitrace.agents import audit as audit_mod
from clinitrace.agents import cg as cg_agent
from clinitrace.agents import refinement as r_agent
from clinitrace.agents import sr as sr_agent
from clinitrace.hitl import Inbox, Ticket, TicketKind
from clinitrace.memory import LTM, STM, NodeStatus
from clinitrace.memory.stm import RetryRecord
from clinitrace.rule_kinds import get as get_rule_kind
from clinitrace.spec.model import Spec, SpecEntry
from clinitrace.presentation import (
    GLOSSARY,
    humanize_ambiguity_class,
    humanize_event,
    humanize_layer,
    humanize_option,
    humanize_property,
    humanize_rule_kind,
    humanize_ticket_kind,
)
from clinitrace.verification import verify_rule_instance
from clinitrace.verification.findings import Severity


_MAX_RETRIES = 3


class DatasetValidationError(RuntimeError):
    """Raised when the input dataset fails the pre-DAG source-schema check.

    Per _002 section 4.1 + failure mode #6: source columns referenced by any
    spec entry must be present at run start. A missing column is a dataset-
    level fail; no derivations run.
    """


def _validate_dataset(spec: Spec, dataset: pd.DataFrame) -> None:
    """Static check on source columns. Inputs that are themselves derivations
    are allowed (they will be produced); raw source inputs must exist in the
    dataset at run start.
    """
    derived_names = {d.name for d in spec.derivations}
    columns = set(dataset.columns)
    missing: dict[str, list[str]] = {}
    for entry in spec.derivations:
        for col in entry.inputs:
            if col in derived_names:
                continue
            if col not in columns:
                missing.setdefault(entry.name, []).append(col)
    if not missing:
        return
    msgs = ", ".join(
        f"{name}=missing[{','.join(cols)!s}]" for name, cols in sorted(missing.items())
    )
    raise DatasetValidationError(
        f"dataset is missing source columns required by the spec: {msgs}; "
        f"available columns: {sorted(columns)!r}"
    )


@dataclass
class RunResult:
    """What an Orchestrator run returns to the CLI."""

    run_id: str
    run_dir: Path
    output_dataset_path: Path
    verification_report_path: Path
    run_summary_path: Path
    stm: STM
    counts: dict[str, int]
    ltm_writes: dict[str, int] = field(default_factory=dict)


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:6]}"


def _topological_sort(spec: Spec, source_columns: set[str]) -> list[str]:
    """Return derivation names in topological order. Raises ValueError on
    cycles or on inputs that reference neither source columns nor a declared
    derivation."""
    derived_names = {d.name for d in spec.derivations}
    indegree: dict[str, int] = {d.name: 0 for d in spec.derivations}
    forward: dict[str, list[str]] = {d.name: [] for d in spec.derivations}

    for entry in spec.derivations:
        for dep in entry.inputs:
            if dep in source_columns:
                continue
            if dep in derived_names:
                forward[dep].append(entry.name)
                indegree[entry.name] += 1
            else:
                raise ValueError(
                    f"derivation {entry.name!r} references unknown input {dep!r} "
                    f"(not a source column and not a declared derivation)"
                )

    ready = [name for name, deg in indegree.items() if deg == 0]
    order: list[str] = []
    while ready:
        ready.sort()  # stable order across runs
        name = ready.pop(0)
        order.append(name)
        for downstream in forward[name]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)

    if len(order) != len(derived_names):
        unresolved = sorted(set(derived_names) - set(order))
        raise ValueError(f"spec contains a cycle involving: {unresolved!r}")
    return order


def run(
    *,
    spec: Spec,
    dataset: pd.DataFrame,
    out_dir: Path,
    ltm: LTM | None,
    llm_mode: str,
    replay_path: Path | None = None,
    inbox_poll_interval: float = 0.5,
    inbox_poll_timeout: float = 60.0,
) -> RunResult:
    """Top-level orchestrator entry point.

    The Inbox is constructed under run_dir so each run's HITL tickets and
    resolutions are co-located with its audit_trail / lineage records. This
    prevents tickets from being overwritten by a subsequent run sharing the
    same out_dir (a real bug in earlier slices).
    """
    run_id = _new_run_id()
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stm = STM(run_id=run_id, llm_mode=llm_mode)
    audit = audit_mod.Audit(run_dir=run_dir, run_id=run_id, ltm=ltm)
    audit.log("run_start", spec_version=spec.version, llm_mode=llm_mode)
    log.info("run_start run_id=%s run_dir=%s llm_mode=%s", run_id, run_dir, llm_mode)

    inbox = Inbox(
        run_dir=run_dir,
        replay_path=replay_path,
        poll_interval_seconds=inbox_poll_interval,
        poll_timeout_seconds=inbox_poll_timeout,
    )

    # ------------------------------------------------------------------
    # Stage 0: pre-DAG dataset validation (_002 section 4.1)
    # ------------------------------------------------------------------

    log.info("stage 0: validating dataset against spec source columns")
    try:
        _validate_dataset(spec, dataset)
    except DatasetValidationError as exc:
        audit.log("dataset_check_failed", error=str(exc))
        log.error("dataset validation failed: %s", exc)
        raise

    counts = {
        "sr_findings": 0,
        "sr_auto_resolved": 0,
        "hitl_tickets_opened": 0,
        "cg_ltm_hits": 0,
        "derivations_verified": 0,
        "derivations_unresolved": 0,
        "refinement_iterations": 0,
    }
    ltm_writes = {"rule_patterns": 0, "ambiguity_resolutions": 0}

    # ------------------------------------------------------------------
    # Stage 1: SR + ambiguity resolution
    # ------------------------------------------------------------------

    log.info("stage 1: running SR over %d entries + resolving ambiguity", len(spec.derivations))
    resolved_spec, sr_log = _resolve_ambiguity(
        spec=spec,
        stm=stm,
        audit=audit,
        ltm=ltm,
        inbox=inbox,
        counts=counts,
        ltm_writes=ltm_writes,
    )
    audit.log("sr_complete", findings=sr_log)
    stm.snapshot(run_dir)

    # ------------------------------------------------------------------
    # Stage 2: DAG planning
    # ------------------------------------------------------------------

    source_cols = set(dataset.columns)
    try:
        execution_order = _topological_sort(resolved_spec, source_cols)
    except ValueError as exc:
        audit.log("dag_plan_failed", error=str(exc))
        raise

    stm.execution_order = execution_order
    audit.log("dag_planned", execution_order=execution_order)
    log.info("stage 2: DAG planned, execution order=%s", execution_order)
    stm.snapshot(run_dir)

    # ------------------------------------------------------------------
    # Stage 3: per-derivation pipeline
    # ------------------------------------------------------------------

    df = dataset.copy()
    derivation_records: dict[str, dict[str, Any]] = {}
    verification_report: dict[str, Any] = {"derivations": {}}

    log.info("stage 3: executing %d derivation(s) in topo order", len(execution_order))
    for name in execution_order:
        entry = resolved_spec.by_name(name)
        node = stm.ensure_node(name)
        if _has_unresolved_input(entry, stm, source_cols):
            node.status = NodeStatus.SKIPPED
            counts["derivations_unresolved"] += 1
            verification_report["derivations"][name] = {
                "status": "skipped",
                "reason": "upstream input did not verify",
            }
            audit.log("derivation_skipped", target=name)
            log.info("  %s: SKIPPED (upstream unresolved)", name)
            stm.snapshot(run_dir)
            continue
        log.info("  %s: starting (rule_kind=%s, inputs=%s)", name, entry.rule_kind, entry.inputs)
        report_entry, record = _execute_derivation(
            entry=entry,
            df=df,
            stm=stm,
            audit=audit,
            ltm=ltm,
            counts=counts,
            ltm_writes=ltm_writes,
            run_id=run_id,
        )
        verification_report["derivations"][name] = report_entry
        if record is None:
            node.status = NodeStatus.UNRESOLVED
            counts["derivations_unresolved"] += 1
            log.info("  %s: UNRESOLVED (%s)", name, report_entry.get("reason", "no reason"))
            stm.snapshot(run_dir)
            continue
        df = record["df"]
        derivation_records[name] = record["lineage"]
        node.status = NodeStatus.VERIFIED
        counts["derivations_verified"] += 1
        log.info(
            "  %s: VERIFIED (agent_chain=%s, ltm_hit=%s, body_signature=%s)",
            name,
            " -> ".join(report_entry.get("agent_chain", [])),
            report_entry.get("ltm_hit"),
            report_entry.get("body_signature"),
        )
        stm.snapshot(run_dir)

    # ------------------------------------------------------------------
    # Stage 4: Audit artifacts
    # ------------------------------------------------------------------

    if derivation_records:
        df = df.assign(
            lineage_id=audit.build_lineage_column(
                df, derivation_records=derivation_records
            )
        )

    dataset_path = audit.write_dataset(df)
    report_path = audit.write_verification_report(verification_report)
    summary_path = audit.write_run_summary(
        _render_summary(
            spec=resolved_spec,
            stm=stm,
            counts=counts,
            verification_report=verification_report,
            llm_mode=llm_mode,
            dataset_path=dataset_path,
            sr_log=sr_log,
        )
    )

    audit.log(
        "run_complete",
        derivations_verified=counts["derivations_verified"],
        derivations_unresolved=counts["derivations_unresolved"],
        ltm_writes=ltm_writes,
    )
    log.info(
        "stage 4: complete -- verified=%d unresolved=%d ltm_writes=%s",
        counts["derivations_verified"],
        counts["derivations_unresolved"],
        ltm_writes,
    )

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        output_dataset_path=dataset_path,
        verification_report_path=report_path,
        run_summary_path=summary_path,
        stm=stm,
        counts=counts,
        ltm_writes=ltm_writes,
    )


# ---------------------------------------------------------------------------
# Stage 1 helpers
# ---------------------------------------------------------------------------


def _resolve_ambiguity(
    *,
    spec: Spec,
    stm: STM,
    audit: audit_mod.Audit,
    ltm: LTM | None,
    inbox: Inbox,
    counts: dict[str, int],
    ltm_writes: dict[str, int],
) -> tuple[Spec, list[dict[str, Any]]]:
    """SR pass + HITL ambiguity tickets. Returns a new Spec with body_patches
    applied and a list of per-entry SR log records."""
    findings = sr_agent.review(spec, ltm)
    counts["sr_findings"] = len(findings)

    log_records: list[dict[str, Any]] = []
    name_to_patch: dict[str, dict[str, Any]] = {}

    for finding in findings:
        record: dict[str, Any] = {
            "target": finding.entry_name,
            "ambiguity_class": finding.ambiguity_class,
            "ambiguity_signature": finding.ambiguity_signature,
            "auto_resolved": finding.auto_resolved,
            "source_mode": finding.source_mode,
            "source_model": finding.source_model,
        }

        if finding.auto_resolved and finding.ltm_resolution is not None:
            counts["sr_auto_resolved"] += 1
            patch = finding.ltm_resolution.get("body_patch", {})
            name_to_patch[finding.entry_name] = patch
            record["chosen_option"] = finding.ltm_resolution.get(
                "chosen_option", "ltm_replay"
            )
            record["body_patch"] = patch
            audit.log("hitl_auto_resolved", **record)
            log.info(
                "  SR auto-resolved %s from LTM (signature=%s)",
                finding.entry_name,
                finding.ambiguity_signature,
            )
            log_records.append(record)
            continue

        # Open a HITL ambiguity ticket.
        ticket = Ticket(
            ticket_kind=TicketKind.AMBIGUITY,
            target=finding.entry_name,
            prompt_shown_to_human=finding.message,
            options_offered=finding.suggested_resolutions,
            context={
                "ambiguity_class": finding.ambiguity_class,
                "ambiguity_signature": finding.ambiguity_signature,
                "source_mode": finding.source_mode,
                "source_model": finding.source_model,
            },
        )
        counts["hitl_tickets_opened"] += 1
        audit.log(
            "hitl_open",
            event_id=ticket.event_id,
            ticket_kind=ticket.ticket_kind.value,
            target=ticket.target,
            options_offered=ticket.options_offered,
        )
        log.info(
            "  HITL ticket opened (kind=%s target=%s event_id=%s) -- WAITING ON HUMAN",
            ticket.ticket_kind.value,
            ticket.target,
            ticket.event_id,
        )
        resolution = inbox.submit_and_wait(ticket)
        log.info(
            "  HITL resolved (event_id=%s chosen=%s by=%s)",
            resolution.event_id,
            resolution.chosen_option,
            resolution.resolved_by,
        )
        audit.log(
            "hitl_resolved",
            event_id=resolution.event_id,
            ticket_kind=resolution.ticket_kind.value,
            target=resolution.target,
            chosen_option=resolution.chosen_option,
            resolved_by=resolution.resolved_by,
        )

        audit.record_feedback_event(
            event_id=resolution.event_id,
            ticket_kind=resolution.ticket_kind.value,
            target=resolution.target,
            options_offered=ticket.options_offered,
            resolution={
                "chosen_option": resolution.chosen_option,
                "body_patch": resolution.body_patch,
            },
            resolved_by=resolution.resolved_by,
            free_text_rationale=resolution.free_text_rationale,
        )

        # Promote to LTM ambiguity_resolutions (ambiguity tickets DO auto-promote).
        audit.promote_ambiguity_resolution(
            signature=finding.ambiguity_signature,
            resolution={
                "chosen_option": resolution.chosen_option,
                "body_patch": resolution.body_patch,
                "free_text_rationale": resolution.free_text_rationale,
            },
            event_id=resolution.event_id,
        )
        ltm_writes["ambiguity_resolutions"] += 1

        name_to_patch[finding.entry_name] = resolution.body_patch
        record["chosen_option"] = resolution.chosen_option
        record["body_patch"] = resolution.body_patch
        record["hitl_event_id"] = resolution.event_id
        log_records.append(record)

        node = stm.ensure_node(finding.entry_name)
        node.hitl_event_ids.append(resolution.event_id)

    # Apply patches to produce a new Spec.
    if not name_to_patch:
        return spec, log_records

    new_entries: list[SpecEntry] = []
    for entry in spec.derivations:
        patch = name_to_patch.get(entry.name, {})
        new_entries.append(cg_agent.merge_resolution_into_entry(entry, patch))
    new_spec = spec.model_copy(update={"derivations": new_entries})
    return new_spec, log_records


# ---------------------------------------------------------------------------
# Stage 3 helpers
# ---------------------------------------------------------------------------


def _execute_derivation(
    *,
    entry: SpecEntry,
    df: pd.DataFrame,
    stm: STM,
    audit: audit_mod.Audit,
    ltm: LTM | None,
    counts: dict[str, int],
    ltm_writes: dict[str, int],
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run the per-derivation pipeline for one entry.

    Returns (verification_report_dict, record_or_None).
    A None record means the derivation is unresolved.
    """
    name = entry.name
    node = stm.ensure_node(name)
    node.status = NodeStatus.RUNNING
    node.rule_kind = entry.rule_kind

    # --- CG ---------------------------------------------------------------
    log.info("    CG normalizing %s ...", name)
    cg_out = cg_agent.normalize(entry, ltm)
    log.info(
        "    CG result: outcome=%s ltm_hit=%s source_mode=%s",
        cg_out.outcome,
        cg_out.ltm_hit,
        cg_out.source_mode,
    )
    audit.log(
        "cg_complete",
        target=name,
        outcome=cg_out.outcome,
        rule_kind=cg_out.rule_kind,
        body_signature=cg_out.body_signature,
        ltm_hit=cg_out.ltm_hit,
        source_mode=cg_out.source_mode,
        source_model=cg_out.source_model,
        confidence=cg_out.confidence,
        reason=cg_out.reason,
    )

    if cg_out.outcome != "match" or cg_out.body is None:
        # MVP: derivation-approval / no_match path is NOT a HITL ticket in
        # this slice. Mark unresolved with a structured finding.
        report = {
            "status": "unresolved",
            "reason": cg_out.reason or "CG returned no_match",
            "cg_outcome": cg_out.outcome,
            "agent_chain": ["CG"],
        }
        node.error = report["reason"]
        return report, None

    counts["cg_ltm_hits"] += int(cg_out.ltm_hit)
    node.body = cg_out.body.model_dump(mode="json")
    node.body_signature = cg_out.body_signature
    node.ltm_hit = cg_out.ltm_hit
    node.ltm_pattern_ref = cg_out.ltm_pattern_ref

    # `source` names the primary input column. For single-source kinds
    # (bin/flag) it IS the input column. For multi-source kinds
    # (duration/compound/risk_score) the body carries explicit column refs
    # (e.g. start_column, condition.column) and `source` is informational
    # only — the apply function ignores it. We still keep entry.inputs[0] so
    # logs and the L_p suites have a stable "headline" column name.
    source = entry.inputs[0]
    # Slice the sample so multi-source rules see every column they reference.
    # bin/flag still get their one column; the extra columns are harmless.
    sample_cols = [c for c in entry.inputs if c in df.columns]
    if not sample_cols:
        sample_cols = [source]
    agent_chain: list[str] = ["CG"]
    current_body = cg_out.body
    last_body_hash = r_agent.body_hash(current_body)
    last_findings_sig: str | None = None

    # --- V (and R loop) ----------------------------------------------------
    for iteration in range(_MAX_RETRIES + 1):
        log.info("    V running L1+L2+L_p on %s (iteration=%d)", name, iteration)
        verdict = verify_rule_instance(
            target=name,
            rule_kind=entry.rule_kind,
            body=current_body,
            source=source,
            sample=df[sample_cols].copy(),
        )
        agent_chain.append("V")
        log.info(
            "    V verdict: passed=%s n_findings=%d", verdict.passed, len(verdict.findings)
        )
        audit.log(
            "v_complete",
            target=name,
            iteration=iteration,
            passed=verdict.passed,
            n_findings=len(verdict.findings),
            findings=[f.model_dump(mode="json") for f in verdict.findings],
        )

        node.findings = [f.model_dump(mode="json") for f in verdict.findings]
        node_findings_sig = r_agent.findings_signature(verdict.findings)

        if verdict.passed:
            # Execute apply against the full df, write the target column.
            entry_record = get_rule_kind(entry.rule_kind)
            df_updated = entry_record.apply(df, name, source, current_body)
            audit.log("apply_complete", target=name, rule_kind=entry.rule_kind)

            # Promote to LTM rule_patterns (validated rule). Skip the write
            # when this run already loaded the pattern from LTM, so the audit
            # trail reflects only genuinely-new patterns.
            if not cg_out.ltm_hit and cg_out.body_signature:
                audit.promote_rule_pattern(
                    rule_kind=entry.rule_kind,
                    body_signature=cg_out.body_signature,
                    body=current_body.model_dump(mode="json"),
                    approval_event_id=None,
                )
                ltm_writes["rule_patterns"] += 1

            report = {
                "status": "verified",
                "rule_kind": entry.rule_kind,
                "body_signature": cg_out.body_signature,
                "iterations": iteration,
                "agent_chain": agent_chain,
                "findings": [],
                "ltm_hit": cg_out.ltm_hit,
                "source_mode": cg_out.source_mode,
                "source_model": cg_out.source_model,
            }
            record = {
                "df": df_updated,
                "lineage": {
                    "rule_kind": entry.rule_kind,
                    "body_signature": cg_out.body_signature,
                    "agent_chain": agent_chain,
                    "hitl_event_ids": list(node.hitl_event_ids),
                    "ltm_pattern_ref": cg_out.ltm_pattern_ref,
                },
            }
            return report, record

        # Verdict failed: decide R vs. early-stop vs. budget.
        if iteration == _MAX_RETRIES:
            audit.log(
                "r_budget_exhausted",
                target=name,
                iterations=iteration,
                reason="reached retry ceiling",
            )
            break

        if last_findings_sig is not None and (
            r_agent.body_hash(current_body) == last_body_hash
            and node_findings_sig == last_findings_sig
        ):
            audit.log(
                "r_early_stop",
                target=name,
                iteration=iteration,
                reason="body+findings unchanged across two iterations",
            )
            break
        last_findings_sig = node_findings_sig
        last_body_hash = r_agent.body_hash(current_body)

        r_out = r_agent.refine(
            rule_kind=entry.rule_kind,
            body=current_body,
            findings=verdict.findings,
        )
        agent_chain.append("R")
        counts["refinement_iterations"] += 1
        audit.log(
            "r_complete",
            target=name,
            iteration=iteration,
            escalate=r_out.escalate,
            reason=r_out.reason,
            note=r_out.note,
        )
        node.retries.append(
            RetryRecord(
                iteration=iteration,
                body_hash=r_agent.body_hash(current_body),
                findings_signature=node_findings_sig,
                note=r_out.note,
            )
        )
        if r_out.escalate or r_out.revised_body is None:
            break

        body_cls = get_rule_kind(entry.rule_kind).body_cls
        current_body = body_cls.model_validate(r_out.revised_body)
        node.body = current_body.model_dump(mode="json")

    # If we get here, V never passed. MVP: mark unresolved (triage HITL is a
    # follow-up slice). The verification report still carries the last verdict.
    final_findings = [f.model_dump(mode="json") for f in verdict.findings]
    report = {
        "status": "unresolved",
        "reason": "V did not pass within retry budget; triage HITL not wired in MVP",
        "rule_kind": entry.rule_kind,
        "body_signature": cg_out.body_signature,
        "iterations": iteration,
        "agent_chain": agent_chain,
        "findings": final_findings,
    }
    node.error = report["reason"]
    return report, None


def _has_unresolved_input(
    entry: SpecEntry, stm: STM, source_cols: set[str]
) -> bool:
    """Return True if any input column is a derivation that did not VERIFY.

    Per _002 section 4.4: a derivation whose upstream input is unresolved is
    skipped, not silently defaulted.
    """
    for dep in entry.inputs:
        if dep in source_cols:
            continue
        upstream = stm.nodes.get(dep)
        if upstream is None or upstream.status != NodeStatus.VERIFIED:
            return True
    return False


_AI_MODE_LABELS = {
    "stub": "offline stubs (no API key required)",
    "live": "live LLM (Ollama)",
}


def _outcome_paragraph(counts: dict[str, int], total_derivations: int) -> str:
    """Plain-English summary paragraph at the top of run_summary.md."""
    verified = counts.get("derivations_verified", 0)
    unresolved = counts.get("derivations_unresolved", 0)
    skipped = counts.get("derivations_skipped", 0)
    tickets_opened = counts.get("hitl_tickets_opened", 0)
    auto_resolved = counts.get("sr_auto_resolved", 0)

    if total_derivations == 0:
        return (
            "The run could not produce any variables. See the run details "
            "below for what went wrong."
        )

    if verified == total_derivations and tickets_opened == 0:
        if auto_resolved:
            return (
                f"Every derived variable was produced and verified. "
                f"No questions came back to you for review -- "
                f"{auto_resolved} prior decision(s) in memory auto-resolved "
                f"potential ambiguities."
            )
        return (
            "Every derived variable was produced and verified. No reviewer "
            "questions were raised."
        )

    if verified == total_derivations and tickets_opened > 0:
        return (
            f"All {total_derivations} derived variable(s) were produced and "
            f"verified. We raised {tickets_opened} review question(s) along "
            f"the way; resolutions are recorded below."
        )

    parts = [f"{verified} of {total_derivations} variable(s) were verified."]
    if unresolved:
        parts.append(f"{unresolved} could not be resolved.")
    if skipped:
        parts.append(f"{skipped} were skipped because a dependency was not available.")
    if tickets_opened:
        parts.append(f"We raised {tickets_opened} review question(s) along the way.")
    return " ".join(parts)


def _render_summary(
    *,
    spec: Spec,
    stm: STM,
    counts: dict[str, int],
    verification_report: dict[str, Any],
    llm_mode: str,
    dataset_path: Path,
    sr_log: list[dict[str, Any]] | None = None,
) -> str:
    """Render the reviewer-facing run_summary.md.

    Audience: clinical data manager / study analyst. Voice: plain English,
    no internal identifiers (rule_kind, body_signature, L1/L_p) leak in;
    everything goes through clinitrace.presentation helpers.
    """
    total = len(stm.execution_order)
    ai_mode_label = _AI_MODE_LABELS.get(llm_mode, llm_mode)

    lines: list[str] = []
    lines.append("# Run summary")
    lines.append("")
    lines.append(
        "This run applied the rules in your transformation spec to the "
        "patient dataset, with oversight at three checkpoints. Below: a "
        "plain-language summary of what happened, per-variable detail, the "
        "review questions raised, and a glossary."
    )
    lines.append("")

    # ----- What happened
    lines.append("## What happened")
    lines.append("")
    lines.append(_outcome_paragraph(counts, total))
    lines.append("")

    # ----- Run details
    lines.append("## Run details")
    lines.append("")
    lines.append(f"- Run identifier: `{stm.run_id}`")
    lines.append(f"- Started: {stm.started_at}")
    lines.append(f"- Spec version: {spec.version}")
    lines.append(f"- Output dataset: `{dataset_path.name}`")
    lines.append(f"- AI mode: {ai_mode_label}")
    lines.append("")

    # ----- Variables produced
    lines.append("## Variables produced")
    lines.append("")
    if total == 0:
        lines.append("No variables were produced in this run.")
        lines.append("")
    else:
        # Map spec name -> SpecEntry for fast rationale lookup. Resolved spec
        # is passed in so we always see the post-HITL body.
        spec_by_name = {d.name: d for d in spec.derivations}

        for name in stm.execution_order:
            report = verification_report["derivations"].get(
                name, {"status": "missing"}
            )
            status = report.get("status", "unknown")
            status_label = {
                "verified":   "Verified",
                "unresolved": "Unresolved",
                "skipped":    "Skipped",
                "missing":    "Not produced",
            }.get(status, status.capitalize())

            lines.append(f"### {name}")
            lines.append("")

            # Lead with the rationale from the spec -- this is what tells the
            # reviewer in one or two sentences what the variable is *for*. The
            # technical "Rule type" and "Status" lines come after, so the
            # reviewer's eye lands on meaning before mechanics.
            entry = spec_by_name.get(name)
            if entry and entry.rationale:
                # Collapse to one line so the rendered markdown stays scannable.
                rationale_line = " ".join(entry.rationale.split())
                lines.append(f"_What this variable is:_ {rationale_line}")
                lines.append("")

            line = f"- **Status:** {status_label}"
            if status == "unresolved":
                reason = report.get("reason")
                if reason:
                    line += f" -- {reason}"
            lines.append(line)

            rule_kind = report.get("rule_kind")
            if rule_kind:
                lines.append(f"- **Rule type:** {humanize_rule_kind(rule_kind)}")

            if report.get("ltm_hit"):
                lines.append(
                    "- **Memory hit:** Recognised from a prior run; the "
                    "validated version was reused (no reviewer ticket needed)."
                )

            # Blocking findings only -- advisories live in verification_report.json.
            blocking = [
                f for f in (report.get("findings") or [])
                if f.get("severity") == Severity.ERROR.value
            ]
            if blocking:
                lines.append("- **Issues raised:**")
                for finding in blocking:
                    layer = humanize_layer(finding.get("layer", ""))
                    prop = finding.get("property_id")
                    prop_label = (
                        f" ({humanize_property(prop)})" if prop else ""
                    )
                    msg = finding.get("message", "")
                    lines.append(f"    - {layer}{prop_label}: {msg}")
            lines.append("")

    # ----- Review questions
    lines.append("## Review questions")
    lines.append("")
    tickets_opened = counts.get("hitl_tickets_opened", 0)
    auto_resolved = counts.get("sr_auto_resolved", 0)
    if tickets_opened == 0 and auto_resolved == 0:
        lines.append(
            "No review questions were raised in this run, and no prior "
            "decisions in memory were applied."
        )
    elif tickets_opened == 0 and auto_resolved > 0:
        lines.append(
            f"No new review questions were raised. {auto_resolved} potential "
            f"ambiguit{'y' if auto_resolved == 1 else 'ies'} matched prior "
            f"decisions in memory and resolved automatically."
        )
    else:
        plural = "questions" if tickets_opened != 1 else "question"
        lines.append(
            f"{tickets_opened} reviewer {plural} raised; all were resolved "
            f"before the run completed."
        )
        if auto_resolved:
            lines.append("")
            lines.append(
                f"Additionally, {auto_resolved} potential ambiguit"
                f"{'y' if auto_resolved == 1 else 'ies'} matched prior "
                f"decisions in memory and resolved automatically (no human "
                f"input needed)."
            )
    lines.append("")

    # Itemized list of each question + decision. Pulled from sr_log so we can
    # show the variable, the question category, and the chosen option in
    # plain-language form.
    if sr_log:
        lines.append("### Each question and decision")
        lines.append("")
        for rec in sr_log:
            target = rec.get("target", "(unspecified variable)")
            klass = humanize_ambiguity_class(rec.get("ambiguity_class", ""))
            chosen_raw = rec.get("chosen_option")
            if chosen_raw is None:
                chosen_label = "(no decision recorded)"
            elif chosen_raw == "ltm_replay":
                chosen_label = "Auto-resolved from memory"
            else:
                chosen_label = humanize_option(chosen_raw)
            auto = rec.get("auto_resolved")
            origin = (
                "Auto-resolved from memory"
                if auto
                else "Resolved by the reviewer"
            )
            lines.append(
                f"- **{target}** -- {klass}. "
                f"_Decision:_ {chosen_label}. "
                f"_How:_ {origin}."
            )
        lines.append("")
        lines.append(
            "See `audit_trail.jsonl` for the full sequence including event "
            "IDs, timestamps, and who resolved each question."
        )
        lines.append("")

    # ----- Glossary
    lines.append("## Glossary")
    lines.append("")
    lines.append(GLOSSARY.rstrip())
    lines.append("")

    return "\n".join(lines)
