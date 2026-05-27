"""Long-term memory: SQLite store for across-run knowledge.

Schema per _002 section 7.2:

  rule_patterns
    rule_kind          TEXT, indexed
    body_signature     TEXT, indexed
    body               TEXT (JSON)
    first_seen_run_id  TEXT
    first_seen_at      TEXT (ISO8601)
    approval_event_id  TEXT
    status             TEXT  ('validated' | 'deprecated')
    PRIMARY KEY (rule_kind, body_signature)

  ambiguity_resolutions
    signature             TEXT PRIMARY KEY
    resolution            TEXT (JSON)
    resolved_run_id       TEXT
    resolved_at           TEXT
    resolution_event_id   TEXT

  feedback_events
    event_id              TEXT PRIMARY KEY
    ticket_kind           TEXT  ('ambiguity' | 'approval' | 'triage')
    target                TEXT
    options_offered       TEXT (JSON)
    resolution            TEXT (JSON)
    resolved_by           TEXT
    resolved_at           TEXT
    free_text_rationale   TEXT

Write policy (A is the only writer): an entry lands in rule_patterns or
ambiguity_resolutions only AFTER V passes and HITL has approved (where
required). Triage resolutions do NOT auto-promote.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_patterns (
    rule_kind         TEXT NOT NULL,
    body_signature    TEXT NOT NULL,
    body              TEXT NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    approval_event_id TEXT,
    status            TEXT NOT NULL DEFAULT 'validated',
    PRIMARY KEY (rule_kind, body_signature)
);

CREATE INDEX IF NOT EXISTS idx_rule_patterns_kind
    ON rule_patterns(rule_kind);

CREATE TABLE IF NOT EXISTS ambiguity_resolutions (
    signature            TEXT PRIMARY KEY,
    resolution           TEXT NOT NULL,
    resolved_run_id      TEXT NOT NULL,
    resolved_at          TEXT NOT NULL,
    resolution_event_id  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_events (
    event_id            TEXT PRIMARY KEY,
    ticket_kind         TEXT NOT NULL,
    target              TEXT,
    options_offered     TEXT,
    resolution          TEXT,
    resolved_by         TEXT,
    resolved_at         TEXT NOT NULL,
    free_text_rationale TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LTM:
    """SQLite-backed long-term memory."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LTM:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # rule_patterns
    # ------------------------------------------------------------------

    def find_rule_pattern(
        self, rule_kind: str, body_signature: str
    ) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT rule_kind, body_signature, body, first_seen_run_id, "
            "first_seen_at, approval_event_id, status "
            "FROM rule_patterns WHERE rule_kind = ? AND body_signature = ?",
            (rule_kind, body_signature),
        )
        row = cur.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["body"] = json.loads(result["body"])
        return result

    def write_rule_pattern(
        self,
        *,
        rule_kind: str,
        body_signature: str,
        body: dict[str, Any],
        run_id: str,
        approval_event_id: str | None,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO rule_patterns "
            "(rule_kind, body_signature, body, first_seen_run_id, first_seen_at, "
            " approval_event_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'validated')",
            (
                rule_kind,
                body_signature,
                json.dumps(body, sort_keys=True),
                run_id,
                _now(),
                approval_event_id,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # ambiguity_resolutions
    # ------------------------------------------------------------------

    def find_ambiguity_resolution(self, signature: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT signature, resolution, resolved_run_id, resolved_at, resolution_event_id "
            "FROM ambiguity_resolutions WHERE signature = ?",
            (signature,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["resolution"] = json.loads(result["resolution"])
        return result

    def write_ambiguity_resolution(
        self,
        *,
        signature: str,
        resolution: dict[str, Any],
        run_id: str,
        event_id: str,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO ambiguity_resolutions "
            "(signature, resolution, resolved_run_id, resolved_at, resolution_event_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (signature, json.dumps(resolution, sort_keys=True), run_id, _now(), event_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # feedback_events
    # ------------------------------------------------------------------

    def write_feedback_event(
        self,
        *,
        event_id: str,
        ticket_kind: str,
        target: str | None,
        options_offered: dict[str, Any] | None,
        resolution: dict[str, Any] | None,
        resolved_by: str | None,
        free_text_rationale: str | None,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO feedback_events "
            "(event_id, ticket_kind, target, options_offered, resolution, "
            " resolved_by, resolved_at, free_text_rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                ticket_kind,
                target,
                json.dumps(options_offered, sort_keys=True) if options_offered else None,
                json.dumps(resolution, sort_keys=True) if resolution else None,
                resolved_by,
                _now(),
                free_text_rationale,
            ),
        )
        self._conn.commit()

    def count_rule_patterns(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM rule_patterns")
        return int(cur.fetchone()["c"])

    def count_ambiguity_resolutions(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM ambiguity_resolutions")
        return int(cur.fetchone()["c"])
