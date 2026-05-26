"""Visible LLM-call lifecycle indicator for the Streamlit UI.

When a user clicks a button that triggers an LLM call, they should see:

  1. **Sending** — the request is being prepared.
  2. **Waiting** — the model is producing tokens (Streamlit's `st.status`
     renders a spinner while the with-block is open).
  3. **Received** — completion latency and (in live mode) the model name
     that responded.

In stub mode, the indicator is explicit about NOT calling an LLM
("Stub mode — deterministic logic, no LLM contact"). Hiding the
difference would make the demo dishonest about what's happening when —
the whole point of these visual indicators is to make the agentic /
deterministic boundary visible to a Sanofi reviewer.

Architectural note:
  Streamlit cannot tick a timer DURING a blocking LLM call — Python is
  busy. The "waiting" feel comes for free from `st.status`'s running
  state, which renders a spinner until the with-block exits. The exit
  message then prints the actual elapsed time. No async / streaming
  needed for the UX to read as live.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st

from clinitrace.llm import current_mode
from clinitrace.llm import client as ollama


@contextmanager
def llm_call(
    label: str,
    *,
    purpose: str | None = None,
    expanded: bool = True,
    deterministic: bool = False,
) -> Iterator["LLMCallController"]:
    """Show an LLM-call lifecycle box around a blocking call.

    Args:
        label: short title shown in the status box (e.g. "Auto-suggest
            derivations", "Triage unknown rule_kind").
        purpose: optional one-line explanation rendered inside the box,
            visible while the call is running.
        expanded: whether the box starts expanded (live mode usually
            wants True so the user sees the model name; stub mode False).
        deterministic: True when the wrapped work definitely does not
            contact the LLM (e.g. profiling a dataset). Forces the ⚙️
            "deterministic" styling regardless of CLINITRACE_LLM. Honesty
            knob — a step that doesn't call out should not look like it does.

    Yields a controller object the caller can use to write extra status
    lines mid-call (visible only AFTER the with-block exits, due to
    Streamlit's render model).
    """
    mode = "stub" if deterministic else current_mode()
    if mode == "stub":
        with st.status(
            f"⚙️ Deterministic — {label}",
            state="running",
            expanded=False,
        ) as status:
            status.write(
                "Stub mode is active: the LLM is **not** being contacted. "
                "Enable the LLM in Settings to see the live agentic loop."
            )
            ctrl = LLMCallController(status, mode="stub", started=time.monotonic())
            try:
                yield ctrl
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.monotonic() - ctrl.started) * 1000
                status.update(
                    label=f"⚠️ Deterministic step failed after {elapsed_ms:.0f}ms — {exc}",
                    state="error",
                )
                raise
            elapsed_ms = (time.monotonic() - ctrl.started) * 1000
            status.update(
                label=f"⚙️ Deterministic — {label} ({elapsed_ms:.0f}ms, no LLM)",
                state="complete",
                expanded=False,
            )
        return

    # Live mode: show the model name so the user can verify configuration
    # matches what they set in Settings.
    try:
        model_name = ollama.model_name()
    except Exception:  # noqa: BLE001
        model_name = "(unknown model)"
    with st.status(
        f"🤖 LLM → {label}",
        state="running",
        expanded=expanded,
    ) as status:
        status.write(f"**Model**: `{model_name}`")
        status.write(f"📤 Sending request… (timer starts now)")
        if purpose:
            status.write(f"_{purpose}_")
        ctrl = LLMCallController(status, mode="live", started=time.monotonic())
        try:
            yield ctrl
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - ctrl.started
            status.update(
                label=f"⚠️ LLM error after {elapsed:.1f}s — {exc}",
                state="error",
            )
            raise
        elapsed = time.monotonic() - ctrl.started
        # Flag slow responses so the user can tell when the model is
        # struggling vs. when the call was crisp.
        speed_tag = "fast" if elapsed < 2 else ("normal" if elapsed < 10 else "slow")
        status.update(
            label=f"🤖 LLM ← {label} ({elapsed:.1f}s, {speed_tag})",
            state="complete",
            expanded=False,
        )


class LLMCallController:
    """Handle the caller uses to add detail lines mid-call.

    Lines added via `note()` appear in the status box once it re-renders
    (which is when the with-block exits — Streamlit can't paint during a
    blocking Python call). So in practice these lines are best for
    post-mortem detail: "matched rule_kind 'bin' with confidence 0.87",
    "augmented 2 new derivations", etc.
    """

    def __init__(self, status: "st.delta_generator.StatusContainer", *, mode: str, started: float):
        self._status = status
        self.mode = mode
        self.started = started

    def note(self, text: str) -> None:
        """Append a line inside the status box."""
        self._status.write(text)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started
