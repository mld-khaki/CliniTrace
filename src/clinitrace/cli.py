"""Command-line entry point for CliniTrace.

Usage:
    python -m clinitrace run --spec PATH --data PATH --out PATH [opts]
    python -m clinitrace --version

The `run` subcommand is the only one. The default uses stub LLM mode and a
fresh LTM. Pass --replay PATH to enable headless HITL resolution from a
pre-recorded JSON file (CI / demo path).
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

from clinitrace import __version__
from clinitrace.agents import orchestrator as orch
from clinitrace.llm import current_mode
from clinitrace.memory import LTM
from clinitrace.spec import load_spec


def _configure_logging(verbose: bool) -> None:
    """Configure stdlib logging for the CLI.

    --verbose lifts the clinitrace logger to INFO and routes lines to stderr
    with a short timestamp + module-tail format that's readable next to the
    final printed counts on stdout.
    """
    level = logging.INFO if verbose else logging.WARNING
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("clinitrace")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinitrace",
        description="CliniTrace: Agentic clinical-data transformation with HITL and traceability.",
    )
    parser.add_argument("--version", action="version", version=f"clinitrace {__version__}")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Stream per-stage progress to stderr: which entry SR/CG is "
            "processing, when an LLM call starts/finishes (with latency), "
            "and per-derivation status. Useful for live Ollama runs where "
            "the CLI is otherwise silent for tens of seconds at a time."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the pipeline end-to-end (batch mode).")
    run.add_argument("--spec", required=True, type=Path, help="Path to spec YAML.")
    run.add_argument(
        "--data",
        required=True,
        type=Path,
        help="Path to the input dataset (CSV or Parquet).",
    )
    run.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory where run artifacts will be written.",
    )
    run.add_argument(
        "--ltm",
        type=Path,
        default=Path("ltm.db"),
        help="Path to the SQLite LTM database (default: ltm.db).",
    )
    run.add_argument(
        "--replay",
        type=Path,
        default=None,
        help=(
            "Optional JSON file mapping ticket (kind,target) to a pre-recorded "
            "resolution. Enables headless HITL replay for CI."
        ),
    )
    run.add_argument(
        "--no-ltm",
        action="store_true",
        help="Skip LTM entirely (no auto-resolution, no LTM writes).",
    )
    run.add_argument(
        "--poll-timeout",
        type=float,
        default=60.0,
        help=(
            "Seconds the Orchestrator waits for each HITL resolution to land "
            "in the outbox. Bump this when resolving interactively in the "
            "Streamlit UI (default: 60)."
        ),
    )
    run.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help=(
            "Seconds between outbox polls (default: 0.5)."
        ),
    )

    ui = sub.add_parser("ui", help="Launch the interactive web-based UI (Streamlit).")
    ui.add_argument(
        "--host",
        default="localhost",
        help="Server host (default: localhost).",
    )
    ui.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Server port (default: 8501).",
    )

    return parser


def _load_dataset(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        sep = "," if suffix == ".csv" else "\t"
        return pd.read_csv(path, sep=sep)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise SystemExit(f"unsupported dataset format: {path.suffix!r}")


def _launch_ui(args: argparse.Namespace, log: logging.Logger) -> int:
    """Launch the Streamlit web UI."""
    ui_path = Path(__file__).parent / "ui" / "streamlit_app.py"
    if not ui_path.exists():
        raise SystemExit(f"UI script not found: {ui_path}")

    log.info("launching Streamlit UI at http://%s:%d", args.host, args.port)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ui_path),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
    ]
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        raise SystemExit(
            "streamlit not found. Install with: pip install streamlit streamlit-option-menu"
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    log = logging.getLogger("clinitrace.cli")

    if args.command == "ui":
        return _launch_ui(args, log)
    if args.command != "run":
        raise SystemExit(f"unknown command: {args.command!r}")

    log.info("loading spec from %s", args.spec)
    spec = load_spec(args.spec)
    log.info(
        "spec loaded: %d derivation(s) -> %s",
        len(spec.derivations),
        [d.name for d in spec.derivations],
    )
    log.info("loading dataset from %s", args.data)
    dataset = _load_dataset(args.data)
    log.info("dataset loaded: %d row(s), columns=%s", len(dataset), list(dataset.columns))
    args.out.mkdir(parents=True, exist_ok=True)
    log.info("llm mode: %s", current_mode())

    ltm: LTM | None = None if args.no_ltm else LTM(args.ltm)

    try:
        try:
            result = orch.run(
                spec=spec,
                dataset=dataset,
                out_dir=args.out,
                ltm=ltm,
                llm_mode=current_mode(),
                replay_path=args.replay,
                inbox_poll_interval=args.poll_interval,
                inbox_poll_timeout=args.poll_timeout,
            )
        except orch.DatasetValidationError as exc:
            print(f"dataset validation failed: {exc}", file=sys.stderr)
            return 3
    finally:
        if ltm is not None:
            ltm.close()

    print(f"run_id: {result.run_id}")
    print(f"output: {result.output_dataset_path}")
    print(f"report: {result.verification_report_path}")
    print(f"summary: {result.run_summary_path}")
    print(f"counts: {result.counts}")
    print(f"ltm writes: {result.ltm_writes}")
    if result.counts["derivations_unresolved"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
