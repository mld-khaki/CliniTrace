# CliniTrace Presentation Talk Track

Target length: 15-20 minutes.

## Slide 1 - Problem

Clinical derivation workflows need automation, but they also need correctness,
auditability, and human oversight. The goal is not to build a one-off script; it
is to show a controlled agentic workflow that can transform mock clinical data
into analysis-ready outputs.

## Slide 2 - What CliniTrace Does

Inputs are a clinical CSV/Parquet dataset and an IDC YAML transformation spec.
Outputs are the derived dataset, verification report, audit trail, short-term
state, and run summary.

Demo variables include `AGE_GROUP`, `RESPONSE_FLAG`,
`TREATMENT_DURATION`, `ANALYSIS_POP_FLAG`, and `RISK_GROUP`.

## Slide 3 - Agentic Architecture

The workflow uses six agents: SR, CG, V, R, A, and O. The important design
choice is that the Orchestrator owns control flow. Agents emit structured
results; they do not secretly call one another.

## Slide 4 - Dependency Handling

The Orchestrator builds a DAG from each derivation's declared inputs. Raw source
columns are validated before execution. Derived variables run in topological
order. Cycles, missing columns, and unresolved upstream nodes are explicit run
states rather than hidden errors.

## Slide 5 - Rule Kinds

The registry covers five common derivation patterns: binning, categorical flags,
durations, compound predicates, and ordered risk scores. Each rule kind has a
typed body and a deterministic apply function.

## Slide 6 - Verification

Verification is layered. L1 validates schema and rule body shape. L2 checks
coverage where available. L_p property suites test behavior for mature rule
kinds. Failures can trigger deterministic refinement, bounded by retry budget
and early-stop logic.

## Slide 7 - Human-in-the-Loop

The demo HITL path is ambiguity resolution. When the rule rationale says one
thing and the rule body omits it, SR opens a reviewer ticket. The reviewer
decision can patch the rule body before execution continues.

## Slide 8 - Traceability

Every run produces `audit_trail.jsonl`, `stm.json`, `verification_report.json`,
`analysis_ready.parquet`, and `run_summary.md`. These artifacts connect outputs
back to source columns, rule logic, agents, HITL decisions, and final state.

## Slide 9 - Memory

Short-term memory is per-run state. Long-term memory is SQLite-backed reusable
knowledge: validated rule patterns, ambiguity resolutions, and feedback events.
On later runs, matching ambiguity and rule signatures can auto-resolve with an
audit event.

## Slide 10 - Demo

Run:

```bash
uv run python -m clinitrace run --spec examples/demo_spec.yaml --data examples/demo_data.csv --out demo_out --ltm demo_ltm.db --replay examples/demo_resolutions.json
```

Then show the run summary, verification report, audit trail, and UI run review.
If time allows, rerun with warm memory and point out that HITL tickets drop to
zero for known ambiguities.

## Slide 11 - Trade-offs

LLMs are useful for interpretation and normalization, but deterministic code
owns execution, verification, lineage, retry policy, and memory writes. This
keeps the prototype credible for regulated workflows.

## Slide 12 - Production Path

A production version would add service separation, private cloud deployment,
dataset/spec versioning, governed LLM gateway, encrypted audit storage, CI/CD,
rollback, monitoring, and study-level tenancy.

## Close

The key point: CliniTrace demonstrates a practical agentic pattern for clinical
derivation where automation is bounded by dependency awareness, deterministic
verification, human review, and reconstructable audit records.
