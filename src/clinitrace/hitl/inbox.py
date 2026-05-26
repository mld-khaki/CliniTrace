"""File-based HITL inbox/outbox + replay support.

Per ticket layout:
    <run_dir>/hitl/inbox/<event_id>.ticket.json
    <run_dir>/hitl/outbox/<event_id>.resolution.json

The Orchestrator opens a ticket by writing to the inbox; the (future) Streamlit
viewer reads the inbox and writes to the outbox. For CI/demo runs the human is
replaced by a pre-recorded resolutions file (--replay flag in the CLI), which
the Inbox loads on construction.

The Inbox polls the outbox at a fixed cadence. The poll wait time is bounded
so a CI run never hangs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import ValidationError

from clinitrace.hitl.tickets import Resolution, Ticket, TicketKind


class HitlReplayError(RuntimeError):
    """Raised when a replay file is missing a resolution for an open ticket."""


class Inbox:
    """File-based ticket store with optional replay-based auto-resolution.

    If replay_path is given, the Inbox preloads its contents and uses them to
    auto-resolve tickets immediately upon opening. This is how CI and headless
    demo runs avoid hanging on human input.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        replay_path: Path | None = None,
        poll_interval_seconds: float = 0.5,
        poll_timeout_seconds: float = 60.0,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.inbox_dir = self.run_dir / "hitl" / "inbox"
        self.outbox_dir = self.run_dir / "hitl" / "outbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval_seconds
        self.poll_timeout = poll_timeout_seconds
        self._replay: dict[tuple[str, str], dict] = {}
        if replay_path is not None and Path(replay_path).exists():
            self._load_replay(Path(replay_path))

    def _load_replay(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data:
            key = (item["ticket_kind"], item["target"])
            self._replay[key] = item

    # ------------------------------------------------------------------
    # Inbox / outbox file IO
    # ------------------------------------------------------------------

    def open_ticket(self, ticket: Ticket) -> Path:
        path = self.inbox_dir / f"{ticket.event_id}.ticket.json"
        path.write_text(ticket.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _outbox_path(self, event_id: str) -> Path:
        return self.outbox_dir / f"{event_id}.resolution.json"

    def write_resolution(self, resolution: Resolution) -> Path:
        path = self._outbox_path(resolution.event_id)
        path.write_text(resolution.model_dump_json(indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # High-level: open + wait
    # ------------------------------------------------------------------

    def submit_and_wait(self, ticket: Ticket) -> Resolution:
        """Open a ticket, then resolve it. Uses replay when available,
        otherwise polls the outbox until the user writes a resolution file.
        """
        self.open_ticket(ticket)
        key = (ticket.ticket_kind.value, ticket.target)
        if key in self._replay:
            return self._build_replay_resolution(ticket, self._replay[key])
        return self._poll_outbox(ticket)

    def _build_replay_resolution(
        self, ticket: Ticket, replay_entry: dict
    ) -> Resolution:
        resolution = Resolution(
            event_id=ticket.event_id,
            ticket_kind=ticket.ticket_kind,
            target=ticket.target,
            chosen_option=replay_entry.get("chosen_option", ""),
            body_patch=replay_entry.get("body_patch", {}),
            free_text_rationale=replay_entry.get("free_text_rationale", ""),
            resolved_by=replay_entry.get("resolved_by", "auto-replay"),
        )
        self.write_resolution(resolution)
        return resolution

    def _poll_outbox(self, ticket: Ticket) -> Resolution:
        deadline = time.time() + self.poll_timeout
        path = self._outbox_path(ticket.event_id)
        while time.time() < deadline:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                try:
                    return Resolution.model_validate(raw)
                except ValidationError as exc:
                    raise HitlReplayError(
                        f"resolution file {path} did not parse: {exc.errors()!r}"
                    ) from exc
            time.sleep(self.poll_interval)
        raise HitlReplayError(
            f"timed out after {self.poll_timeout}s waiting for resolution at {path}; "
            f"ticket_kind={ticket.ticket_kind.value} target={ticket.target!r}"
        )

    @staticmethod
    def example_replay_entry(
        ticket_kind: TicketKind,
        target: str,
        chosen_option: str,
        body_patch: dict | None = None,
        free_text_rationale: str = "",
    ) -> dict:
        """Helper: shape one entry of the replay JSON list. Used by demos."""
        return {
            "ticket_kind": ticket_kind.value,
            "target": target,
            "chosen_option": chosen_option,
            "body_patch": body_patch or {},
            "free_text_rationale": free_text_rationale,
        }
