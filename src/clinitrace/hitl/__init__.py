"""Human-in-the-loop: file-based ticket store + (future) Streamlit viewer.

_002 sections 5.2, 5.3, 5.4. MVP ships ambiguity-kind tickets only;
derivation-approval and triage tickets are defined in the schema and stubbed
in the orchestrator path for the next slice.

Replay path (used by CI + headless demo): a pre-recorded resolutions JSON file
is loaded at run start and consulted by the inbox poller; tickets whose
target+kind appear in the file are resolved immediately. Streamlit-based
interactive resolution is the next slice.
"""

from clinitrace.hitl.inbox import Inbox
from clinitrace.hitl.tickets import (
    Resolution,
    Ticket,
    TicketKind,
    new_event_id,
)

__all__ = ["Inbox", "Resolution", "Ticket", "TicketKind", "new_event_id"]
