# CliniTrace Submission README

## Contents

- `CliniTrace/`: clean source snapshot for the prototype.
- `DESIGN_DOCUMENT.md`: 2-4 page design document.
- `PRESENTATION_TALK_TRACK.md`: 15-20 minute presentation outline.
- `RUN.md`: setup, CLI, UI, and demo instructions.
- `demo_artifacts/`: deterministic sample run outputs.

## Quick Run

From the `CliniTrace` project directory:

```bash
uv sync
uv run python -m clinitrace run --spec examples/demo_spec.yaml --data examples/demo_data.csv --out demo_out --ltm demo_ltm.db --replay examples/demo_resolutions.json
```

Launch the UI:

```bash
uv run python -m clinitrace ui
```

Run validation:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
```

## Validation Status

Current local checks:

- Ruff: all checks passed.
- Pytest: 144 passed on Python 3.11.

## Notes for Reviewers

The default demo uses deterministic stub LLM behavior so it runs from a clean
clone without network or model setup. Live LLM mode is supported locally via
Ollama or OpenAI-compatible configuration; see `RUN.md` and `README.md`.
