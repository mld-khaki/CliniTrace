# CliniTrace Design Document

## 1. Objective

CliniTrace is a prototype agentic workflow for clinical data derivation,
verification, and traceability. It accepts a structured clinical dataset and an
Importing Data Contract (IDC) YAML specification, then produces:

- an analysis-ready dataset with derived variables,
- verification results for each derivation,
- an audit trail that records lineage, agent actions, human decisions, and
  final run state.

The prototype is intentionally small enough to review in a take-home setting,
but its boundaries mirror regulated clinical data workflows: no silent default
logic, explicit dependencies, deterministic verification, and human review
where clinical intent is ambiguous.

## 2. Architecture

The system is organized as six agents coordinated by a deterministic
Orchestrator.

| Agent | Role | Implementation stance |
|---|---|---|
| Spec Reviewer (SR) | Reads each IDC derivation and flags ambiguous rationale/body mismatches. | LLM-backed in live mode; deterministic stub by default for reproducibility. |
| Code Generator (CG) | Normalizes the rule body into a validated internal representation. | Uses LTM cache first; may call an LLM in live mode. |
| Verifier (V) | Runs schema, coverage, and property checks. | Deterministic. |
| Refiner (R) | Applies safe patches for known failure modes and stops early when no progress is made. | Deterministic. |
| Auditor (A) | Writes run summaries, per-row lineage, event logs, and LTM promotion records. | Deterministic. |
| Orchestrator (O) | Owns control flow, DAG planning, retry budget, and HITL gates. | Deterministic. |

The Orchestrator is the only component allowed to schedule agents or loop. This
keeps control flow inspectable and prevents hidden agent-to-agent side effects.

## 3. Orchestration and Dependencies

Each derived variable declares its source inputs in the IDC. The Orchestrator
also asks the rule-kind registry for body-carried references such as
`start_column`, `end_column`, and condition columns. It classifies the combined
set as raw dataset columns or upstream derived variables, validates that raw
sources exist, and builds a directed acyclic graph (DAG) over derivations.

Execution proceeds in topological order. If the graph contains a cycle, the run
fails before derivation. If a raw source column is missing, the run exits with a
dataset validation failure. If an upstream derivation remains unresolved,
downstream derivations are skipped rather than computed on partial data.

This design directly addresses dependency-aware derivation:

- source variables are separated from derived variables,
- execution order is explicit and reproducible,
- cycles and missing columns fail early,
- downstream error propagation is visible in the audit trail.

## 4. Rule and Verification Model

The current rule registry includes five rule kinds:

- `bin`: numeric values into named buckets,
- `flag`: categorical mapping with explicit null/unmapped behavior,
- `duration`: date delta between two columns,
- `compound`: flat boolean predicates combined with AND/OR,
- `risk_score`: ordered tier ladder where the first matching tier wins.

Verification runs in layers:

- L1: schema/body validation through Pydantic models,
- L2: deterministic coverage checks where available,
- L_p: property-based checks for shipped rule kinds with mature coverage.

The strongest coverage is currently on `bin` and `flag`; `duration`,
`compound`, and `risk_score` have typed bodies and apply functions, with deeper
L2/property suites planned as future hardening.

## 5. Human-in-the-Loop Design

CliniTrace demonstrates HITL through ambiguity tickets. When SR finds a rule
whose rationale and body do not match, the Orchestrator writes a structured
ticket to the run's HITL inbox. A reviewer can resolve it in the Streamlit UI or
through a replay JSON file for headless demos and CI.

Each resolution captures:

- the prompt shown to the reviewer,
- options offered,
- the chosen option,
- optional rationale,
- optional rule-body patch,
- the event ID and timestamp.

The resolution is merged into the working spec before DAG execution continues.
The same decision is later promoted to long-term memory so future matching
ambiguities can auto-resolve with an explicit audit event.

## 6. Traceability and Auditability

Every run writes a self-contained output directory containing:

- `analysis_ready.parquet`: final dataset,
- `verification_report.json`: derivation-level verification results,
- `audit_trail.jsonl`: event stream for agent actions and human decisions,
- `stm.json`: short-term workflow state,
- `run_summary.md`: reviewer-readable summary.

Lineage records connect each derived output back to source columns, applied rule
logic, agent chain, HITL event IDs, and verification status. The audit trail also
records whether SR/CG used stub, live LLM, or LTM cache behavior, so a reviewer
can reconstruct how each result was produced.

## 7. Memory and Reusability

Short-term memory is the run-local state in `stm.json`: DAG nodes, statuses,
findings, retry records, open tickets, and output paths. It supports audit and
debugging for one workflow execution.

Long-term memory is a SQLite database with reusable validated knowledge:

- `rule_patterns`: canonical rule bodies and signatures,
- `ambiguity_resolutions`: prior human decisions keyed by ambiguity signature,
- `feedback_events`: reviewer interventions and metadata.

Retrieval happens before expensive or ambiguous work. SR can auto-resolve a
known ambiguity, and CG can skip live LLM normalization when a validated rule
pattern already exists. This improves consistency and reduces repeated human or
model effort while preserving explainability.

## 8. Trade-offs and Production Path

The prototype favors explicit control and reproducibility over maximum
automation. LLM calls are optional and isolated to interpretive steps; execution,
verification, dependency handling, lineage, and memory writes remain
deterministic. This is appropriate for regulated clinical workflows where an LLM
should propose or normalize logic, not silently approve it.

Key limitations:

- only ambiguity HITL is exercised end-to-end,
- three newer rule kinds need deeper property coverage,
- production auth, PHI handling, and multi-study tenancy are outside this demo,
- the workflow engine is hand-rolled rather than backed by Airflow/Prefect.

A production version would separate services for UI, orchestration, verified
rule execution, memory, and audit storage; run inside a private cloud network;
encrypt data at rest and in transit; route LLM calls through a governed gateway;
version specs, prompts, rule bodies, and datasets; and emit observability
metrics for failures, HITL volume, cache hit rate, and derivation latency.

## 9. How to Review

Run the deterministic batch demo:

```bash
uv sync
uv run python -m clinitrace run --spec examples/demo_spec.yaml --data examples/demo_data.csv --out demo_out --ltm demo_ltm.db --replay examples/demo_resolutions.json
```

Then inspect `demo_out/<run_id>/run_summary.md`,
`verification_report.json`, and `audit_trail.jsonl`, or launch the UI:

```bash
uv run python -m clinitrace ui
```
