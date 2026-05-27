# CliniTrace

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)


> An agentic clinical-data transformation pipeline with HITL, DAG-based
> derivation, and traceable lineage.

CliniTrace takes a structured mock clinical dataset and a transformation
specification; produces an analysis-ready dataset, a verification report,
and a per-row audit trail. Six small agents do the work; a single
Orchestrator schedules them; a Streamlit GUI lets a reviewer answer the
questions the pipeline raises.

Reviewer-facing documentation (Glossary, Tutorial) is rendered in-app
under the Documentation menu when the GUI is running.

## Quick Start

Two entry points for different workflows:

### Interactive Web UI (Recommended for HITL Review)

```bash
python -m clinitrace ui
```

Opens a Streamlit interface at `http://localhost:8501` for reviewing rules,
resolving ambiguities, and inspecting audit trails.

### Batch CLI (For Automation & Testing)

```bash
python -m clinitrace run \
  --spec examples/demo_spec.yaml \
  --data examples/demo_data.csv \
  --out ./runs
```

See [RUN.md](RUN.md) for full options and examples.

## What this prototype includes

Hero-flow MVP per the slice plan:

- Six agents wired: SR (LLM-backed), CG (LLM-backed), V (deterministic
  L1 + L2 + L_p), R (deterministic patcher with adaptive early-stop),
  A (lineage + audit trail), O (DAG planner + sole loop authority).
- Five rule_kinds registered: `bin`, `flag`, `duration`, `compound`, `risk_score`.
  `bin` and `flag` carry full L1 + L2 + L_p coverage with property suites;
  the other three have L1 schemas and apply functions (L2 + L_p coverage
  deferred to future work).
- One HITL kind exercised end-to-end: ambiguity tickets. Tickets and
  resolutions are JSON files inside each run's directory; a `--replay` flag
  lets CI and headless demos auto-resolve from a pre-recorded file.
- LTM in SQLite with three tables (rule_patterns, ambiguity_resolutions,
  feedback_events). SR auto-resolves on LTM hit; CG skips the LLM entirely
  when the canonical body signature already lives in LTM.
- Pre-DAG dataset validation: every source column referenced by the spec is
  checked at run start; missing columns are a dataset-level fail with exit
  code 3 and a `dataset_check_failed` audit event.
- Two-run scenario demonstrable: a warm-LTM second run hits ambiguity and
  rule patterns in LTM, opens zero HITL tickets, and (in live mode) skips
  every CG LLM call.
- Local Ollama integration. The default is offline stubs so the demo runs
  from a clean clone without network. Set `CLINITRACE_LLM=live` to call a
  local Ollama server.
- Streamlit GUI with sidebar workflow navigation: Import new DB, IDC Rulebook
  (Pending + Library), Task History, Settings, Documentation, and a Glossary
  popover.

The derivation-approval and triage HITL paths are scaffolded but not
exercised in the demo; ambiguity-resolution is the primary HITL path
demonstrated end-to-end. L2 + L_p coverage for the three newer rule_kinds
(duration, compound, risk_score) lands in future work.

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management.

```
git clone https://github.com/mld-khaki/CliniTrace.git
cd CliniTrace
uv python install 3.11
uv sync
uv run --extra dev pytest
```

The core CLI and Streamlit UI dependencies are installed by `uv sync`.
Developer-only tools such as pytest, hypothesis, and ruff live in the
`dev` extra:

```
uv sync --extra dev
```

If `uv` is not available or fails on your filesystem, pip works fine:

```
python -m pip install -e ".[dev]"
python -m pytest
```

## Demo: run the pipeline end-to-end

```
python -m clinitrace run --spec examples/demo_spec.yaml --data examples/demo_data.csv --out demo_out --ltm demo_ltm.db --replay examples/demo_resolutions.json
```

This:

1. Loads the spec and dataset.
2. Runs SR over both derivations. AGE_GROUP is clean; RESPONSE_FLAG is
   flagged ambiguous (its rationale mentions `unknown` but the body has no
   handling for it).
3. Opens an ambiguity ticket in `demo_out/<run_id>/hitl/inbox/`. The
   `--replay` flag short-circuits the wait by reading the pre-recorded
   resolution from `examples/demo_resolutions.json`.
4. Merges the resolution's `body_patch` into the entry (adds
   `unmapped_handling: value, unmapped_value: "U"`).
5. Builds the DAG, executes each derivation in topo order via CG -> V.
6. Writes `analysis_ready.parquet`, `verification_report.json`,
   `audit_trail.jsonl`, `run_summary.md`, and `stm.json` under
   `demo_out/<run_id>/`.

Run it a second time without `--replay`. The warm LTM auto-resolves SR's
ambiguity and CG's rule lookup; zero HITL tickets open.

For a reviewer-framed walkthrough of what to do once you have a run on
disk, open the GUI (below) and read Documentation > Tutorial.

## GUI (Streamlit)

```
python -m clinitrace ui
```

For direct Streamlit launch, use `streamlit run streamlit_app.py` from the
repository root.

The sidebar is split into workflow and reference groups:

- **Import new DB** -- upload a dataset, preview columns, choose or generate
  an IDC, run the pipeline, and inspect the immediate result.
- **IDC Rulebook** -- combines **Pending** clarification tickets with the
  **Library** of validated rule patterns and reviewer decisions. Pending
  tickets live under `<run_dir>/hitl/inbox/`; resolutions are written to the
  matching outbox where the Orchestrator picks them up.
- **Task History** -- pick a past run; view the `run_summary.md`,
  `verification_report.json` (as a table), the `audit_trail.jsonl`
  (filterable by event_type), the `analysis_ready.parquet` dataset, and
  per-row lineage records.
- **Settings** -- edit paths, display timezone, and LLM backend settings.
- **Documentation** -- horizontal sub-menu with Glossary (term
  definitions) and Tutorial (concepts plus a step-by-step walkthrough of
  the demo, in reviewer language).
- **Glossary** -- sidebar popover for quick definitions without leaving the
  current page.

The sidebar holds the same Runs folder and Memory file inputs (defaults:
`demo_out` and `demo_ltm.db`, both resolved relative to where you launched
streamlit), so you do not have to leave the current page to point at a
different study.

## Screenshots

Screenshots of the Streamlit GUI (sidebar navigation, IDC Rulebook Pending tab,
Documentation tutorial page) will be added to `docs/screenshots/`. Capture
instructions live in `docs/screenshots/CAPTURE_NOTES.md`.

## Live Ollama mode

```
ollama serve            # if not already running
ollama pull qwen3.5:4b  # any instruction-tuned model works

CLINITRACE_LLM=live \
    CLINITRACE_OLLAMA_MODEL=qwen3.5:4b \
    python -m clinitrace run --spec examples/demo_spec.yaml \
        --data examples/demo_data.csv --out demo_out --replay examples/demo_resolutions.json
```

Env vars:

- `CLINITRACE_LLM`: `stub` (default) or `live`.
- `CLINITRACE_OLLAMA_URL`: default `http://localhost:11434`.
- `CLINITRACE_OLLAMA_MODEL`: default `gpt-oss:20b`.
- `CLINITRACE_OLLAMA_TIMEOUT`: seconds per call, default 120.

The stub-vs-live decision is logged in `audit_trail.jsonl` per agent call
(`source_mode` and `source_model` fields), so a reviewer reading the trail
always knows where each derivation came from.

## Layout

```
CliniTrace/
  pyproject.toml
  examples/
    demo_spec.yaml
    demo_data.csv
    demo_resolutions.json
  clinitrace/
    cli.py
    __main__.py
    presentation.py   # reviewer-facing labels (GLOSSARY_HTML, TUTORIAL_HTML, ...)
    rule_kinds/       # bin, flag, errors, registry
    spec/             # YAML loader + Pydantic models
    verification/     # L1 + L2 (coverage) + L_p (property suites)
    memory/           # STM (in-run) + LTM (SQLite)
    llm/              # Ollama client + offline stubs + dispatcher
    hitl/             # ticket schema + file-based inbox (per run_dir)
    agents/           # sr, cg, refinement, audit, orchestrator
    ui/               # streamlit_app.py
  tests/
    rule_kinds/                       # body + apply tests for bin + flag
    verification/                     # L1 + L_p runner tests
    test_e2e.py                       # full pipeline + two-run LTM scenario
    test_refinement.py                # R unit tests
    test_orchestrator_branches.py     # cycle, dataset schema, skip-downstream
    test_orchestrator_retry_loop.py   # R loop, adaptive early-stop, budget
  docs/
    screenshots/                      # README screenshots (see CAPTURE_NOTES.md)
```

## Sanity check

```
python -m pytest                    # 148 tests
python -m clinitrace --version
python -m clinitrace run --help
```

Pass `-v` / `--verbose` to stream per-stage progress to stderr while a run
is in flight: which entry SR is reviewing, when an Ollama call starts and
how long it took, per-derivation status. Essential for live Ollama runs
where the CLI would otherwise sit silent for tens of seconds at a time.

Exit codes:

- 0 -- run succeeded, every derivation verified
- 2 -- run completed but one or more derivations are unresolved
- 3 -- pre-DAG dataset validation failed (missing source columns)

## Deploy to Streamlit Community Cloud

CliniTrace ships with a root-level `streamlit_app.py` entry point so it
deploys to [share.streamlit.io](https://share.streamlit.io) in three clicks.

### One-time setup

1. Fork or push this repo to your own GitHub account (public required for
   the free tier).
2. Go to [share.streamlit.io](https://share.streamlit.io), click **New app**.
3. Fill in the deploy form:
   - **Repository**: your GitHub URL.
   - **Branch**: `main`.
   - **Main file path**: `streamlit_app.py` (the root wrapper, not the package
     module under `clinitrace/ui/`).
4. Click **Advanced settings > Secrets**, paste the line below, and save:
   ```
   CLINITRACE_CLOUD_DEMO = "true"
   ```
   This trips the cloud-demo banner and locks the LLM toggle off (see
   "What the cloud demo can and can't do" below).
5. Click **Deploy**. First build pulls dependencies from
   `requirements.txt` and takes ~2 minutes. Subsequent deploys cache the
   environment.

### What the cloud demo can and can't do

| Feature | Cloud demo | Local |
|---|---|---|
| All five rule kinds (`bin`, `flag`, `duration`, `compound`, `risk_score`) | Yes | Yes |
| Auto-suggest IDC from dataset | Yes | Yes |
| HITL clarifications + IDC Rulebook | Yes | Yes |
| Pre-warmed LTM (immediate cache hits on first visit) | Yes, via shipped `demo_ltm.db` | Yes |
| Live LLM (SR + CG calling Ollama) | No, stub mode only | Yes, with local Ollama |
| Persistent state across cold starts | No, resets every restart | Yes |

The cloud demo intentionally runs in stub mode because Streamlit Cloud
cannot reach an LLM running on your machine. The deterministic agents
(V, R, A, O) work identically in both environments. For the full live
agentic loop, clone the repo and run locally:

```bash
git clone https://github.com/<you>/CliniTrace.git
cd CliniTrace
uv sync
ollama serve &   # or just have it running in the background
python -m clinitrace ui
```

### Cleaning up before your first push

The repo includes a few local-environment files that shouldn't ship to
the cloud demo. Run these once before pushing:

```bash
git rm --cached .clinitrace_settings.json
git rm --cached --ignore-unmatch ltm.db
git commit -m "chore: remove local-env files from tracking"
```

`demo_ltm.db` IS tracked (read-only seed for the cloud demo).
`.clinitrace_settings.json`, `ltm.db`, `demo_out/` are gitignored after
this change.

## License

Released under the [MIT License](LICENSE). See `LICENSE` for the full text.
