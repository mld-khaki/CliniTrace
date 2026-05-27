"""Memory: STM (short-term, per-run) and LTM (long-term, across-run).

_002 section 7. Public surface:

  STM: an in-memory workflow state object, persisted to a JSON snapshot in
       the run directory after every node transition.
  LTM: a SQLite-backed store with three tables: rule_patterns,
       ambiguity_resolutions, feedback_events.

The two are deliberately distinct types: STM holds dataframes-by-reference
plus per-node status; LTM is the durable across-run knowledge base.
"""

from clinitrace.memory.ltm import LTM
from clinitrace.memory.stm import STM, NodeState, NodeStatus

__all__ = ["LTM", "STM", "NodeState", "NodeStatus"]
