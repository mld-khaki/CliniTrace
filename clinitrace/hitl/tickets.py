"""HITL ticket and resolution schemas (_002 section 5.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TicketKind(str, Enum):
    AMBIGUITY = "ambiguity"
    APPROVAL = "approval"
    TRIAGE = "triage"


def new_event_id() -> str:
    """Return a fresh feedback-event id. Used both as ticket id and as
    foreign-key reference from LTM rows."""
    return f"evt-{uuid.uuid4().hex[:12]}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ticket(BaseModel):
    """One open ticket awaiting a human resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=new_event_id)
    ticket_kind: TicketKind
    target: str
    prompt_shown_to_human: str
    options_offered: list[str]
    context: dict[str, Any] = Field(default_factory=dict)
    opened_at: str = Field(default_factory=_utcnow)


class Resolution(BaseModel):
    """A human's structured answer to a ticket.

    For ambiguity: `chosen_option` is one of the offered options. If the
    option implies a body patch, `body_patch` holds the patch dict.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    ticket_kind: TicketKind
    target: str
    chosen_option: str
    body_patch: dict[str, Any] = Field(default_factory=dict)
    free_text_rationale: str = ""
    resolved_by: str = "auto-replay"
    resolved_at: str = Field(default_factory=_utcnow)
