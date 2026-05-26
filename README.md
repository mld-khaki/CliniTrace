# CliniTrace

> An agentic clinical-data transformation pipeline with HITL, DAG-based
> derivation, and traceable lineage.

CliniTrace takes a structured mock clinical dataset and a transformation
specification; produces an analysis-ready dataset, a verification report,
and a per-row audit trail. Six small agents do the work; a single
Orchestrator schedules them; a Streamlit GUI lets a reviewer answer the
questions the pipeline raises.

This repo holds the source code. The canonical architecture spec, decision
log, and design documents live one directory up:

- `../clinitrace_architecture_proposal_003.md` -- canonical spec (current)
- `../MIGRATION_NOTE.md` -- current state, locked decisions, mode per workstream
- `../discussions.md` -- decision rationale (Rounds 1-3)
- `../property_test_contracts.md` -- per-rule_kind L_p contracts
- `../TUTORIAL.md` -- reviewer-facing tour (also rendered in-app under
  Documentation > Tutorial)
- `../GLOSSARY.md` -- term definitions (also in-app under
  Documentation > Glossary)

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
- Streamlit GUI with a top-level menu: Review questions, Run review,
  Across-run memory, Documentation (Glossary + Tutorial), Settings.

The derivation-approval and triage HITL paths are scaffolded but not
exercised in the demo; ambiguity-resolution is the primary HITL path
demonstrated end-to-end. L2 + L_p coverage for the three newer rule_kinds
(duration, compound, risk_score) lands in future work.

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management.

```
cd repo
uv python install 3.11
uv sync
uv run pytest
```

The GUI ships as an optional extra. Install it with:

```
uv sync --extra gui
```

This pulls in `streamlit>=1.36` and `streamlit-option-menu>=0.3.6` (the
top-level menu component).

If `uv` is not available or fails on your filesystem, pip works fine:

```
cd repo
python -m pip install -e ".[gui]" pytest hypothesis pyyaml pyarrow
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
3. Opens an ambiguity ticket in `demo_out/_hitl_staging/hitl/inbox/`. The
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
disk, open the GUI (below) and read Documentation > Tutorial, or read
`../TUTORIAL.md` directly.

## GUI (Streamlit)

```
streamlit run src/clinitrace/ui/streamlit_app.py
```

The top of the page carries a horizontal menu with five entries:

- **Review questions** -- lists open reviewer tickets under
  `<run_dir>/hitl/inbox/`, renders the selected one (prompt, context,
  options, free-text rationale, optional JSON body_patch), and writes the
  resolution into the outbox where the Orchestrator picks it up. This is
  the locked surface from proposal section 5.3.
- **Run review** -- pick a past run; view the `run_summary.md`,
  `verification_report.json` (as a table), the `audit_trail.jsonl`
  (filterable by event_type), the `analysis_ready.parquet` dataset, and
  per-row lineage records.
- **Across-run memory** -- point at the SQLite file; browse
  `rule_patterns`, `ambiguity_resolutions`, and `feedback_events`. Click a
  rule_pattern row to see its full body JSON.
- **Documentation** -- horizontal sub-menu with Glossary (term
  definitions) and Tutorial (concepts plus a step-by-step walkthrough of
  the demo, in reviewer language).
- **Settings** -- mirror of the sidebar's path inputs. Edit either; the
  other updates automatically.

The sidebar holds the same Runs folder and Memory file inputs (defaults:
`demo_out` and `demo_ltm.db`, both resolved relative to where you launched
streamlit), so you do not have to leave the current page to point at a
different study.

## Screenshots

Capture instructions for these are in `docs/screenshots/CAPTURE_NOTES.md`.
Drop the PNGs in `docs/screenshots/` with the names below and the links
below will resolve.

![Top-level menu](docs/screenshots/menu.png)

*Top-level menu with five pages. The active page is highlighted.*

![Review questions page](docs/screenshots/review_questions.png)

*The Review questions page with one open ambiguity ticket. The prompt,
options, and free-text reasoning box are the locked HITL surface from
proposal section 5.3.*

![Documentation > Tutorial page](docs/screenshots/documentation_tutorial.png)

*Documentation page with the Tutorial sub-menu selected, showing the
concepts overview followed by the demo walkthrough.*

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
repo/
  pyproject.toml
  examples/
    demo_spec.yaml
    demo_data.csv
    demo_resolutions.json
  src/clinitrace/
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

## What lives where

- Architecture spec, decision log, property contracts: parent directory.
- Locked decisions: proposal `_003` (canonical), `discussions.md` Rounds 1-3.
- Per-rule_kind property contracts that V exercises:
  `property_test_contracts.md`.
- Reviewer documentation: `../TUTORIAL.md`, `../GLOSSARY.md` (both also
  rendered in-app under Documentation).
- This README: how to install and run.

## Sanity check

```
python -m pytest                    # 78 tests, ~1.5s
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

## License

TBD. The take-home submission is shared with Sanofi for evaluation
purposes; a permissive license (MIT or Apache-2.0) is the recommended
choice if this repo is ever published more broadly.
