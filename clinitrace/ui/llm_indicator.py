"""Visible LLM-call lifecycle indicator for the Streamlit UI.

When a user triggers an agentic step, they should see one of three
honestly-distinct status boxes:

  1. ⚙️ **Deterministic by design** — the step never calls the LLM,
     regardless of CLINITRACE_LLM. E.g. dataset profiling, pattern
     proposal, audit writes. Use `llm_call(..., deterministic=True)`.

  2. ⚙️ **Stub fallback** — the step COULD call the LLM, but the user
     has stub mode active (LLM disabled in Settings). Indicator says so
     explicitly and points at Settings.

  3. 🤖 **Live LLM** — the step is actually contacting Ollama. Shows
     model name + timing. State `running` keeps st.status's spinner
     visible during the blocking call; on exit prints elapsed seconds
     and a fast/normal/slow tag.

Why three states and not two:
  Conflating "deterministic by design" with "stub fallback" is dishonest
  demoware. The first is a fixed architectural choice (V/R/A/O never
  call LLMs); the second is a user-controlled disable. A Sanofi reviewer
  asking "why didn't the LLM fire here?" deserves the right answer per
  step, not a generic "stub mode is on" message.

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
    position: tuple[int, int] | None = None,
) -> Iterator["LLMCallController"]:
    """Show a lifecycle box around a blocking step.

    Args:
        label: short title shown in the status box (e.g. "Auto-suggest
            derivations", "Triage unknown rule_kind", "Pipeline run").
        purpose: optional one-line explanation rendered inside the box,
            visible while the call is running.
        expanded: whether the box starts expanded. Live mode usually
            wants True so the user sees the model name; deterministic
            and stub branches use a compact collapsed view.
        deterministic: True when the wrapped work definitely does not
            contact the LLM, by design (e.g. dataset profiling, audit
            writes). Routes to the ⚙️ deterministic-by-design branch
            below. Honesty knob — a step that doesn't call out should
            not look like it does, AND should not be misrepresented as
            a stub fallback.
        position: optional (current, total) tuple shown as "x / y" in
            the running label. Useful when this is one of N LLM calls
            in the same workflow (e.g. SR over 5 spec entries → pass
            position=(3, 5) on the 3rd entry).

    Yields:
        LLMCallController — caller can attach detail lines via .note()
        (visible once the with-block exits; Streamlit can't paint
        during a blocking Python call).

    The three internal branches share the same controller protocol so
    callers don't have to know which branch fired.
    """
    # Branch 1: deterministic-by-design.
    if deterministic:
        with st.status(
            f"⚙️ Deterministic — {label}",
            state="running",
            expanded=False,
        ) as status:
            if purpose:
                status.write(f"_{purpose}_")
            status.write(
                "This step is deterministic by design — it never contacts "
                "the LLM, regardless of Settings."
            )
            ctrl = LLMCallController(status, mode="deterministic", started=time.monotonic())
            try:
                yield ctrl
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.monotonic() - ctrl.started) * 1000
                status.update(
                    label=f"⚠️ {label} failed after {elapsed_ms:.0f}ms — {exc}",
                    state="error",
                )
                raise
            elapsed_ms = (time.monotonic() - ctrl.started) * 1000
            status.update(
                label=f"⚙️ Deterministic — {label} ({elapsed_ms:.0f}ms)",
                state="complete",
                expanded=False,
            )
        return

    mode = current_mode()

    # Branch 2: stub fallback (LLM disabled in Settings).
    if mode == "stub":
        with st.status(
            f"⚙️ Stub — {label}",
            state="running",
            expanded=False,
        ) as status:
            if purpose:
                status.write(f"_{purpose}_")
            status.write(
                "**Stub mode** — this step would call the LLM, but it is "
                "**disabled in Settings**. Using deterministic fallback "
                "logic instead. Enable the LLM in Settings → save to see "
                "the live agentic loop."
            )
            ctrl = LLMCallController(status, mode="stub", started=time.monotonic())
            try:
                yield ctrl
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.monotonic() - ctrl.started) * 1000
                status.update(
                    label=f"⚠️ Stub step failed after {elapsed_ms:.0f}ms — {exc}",
                    state="error",
                )
                raise
            elapsed_ms = (time.monotonic() - ctrl.started) * 1000
            status.update(
                label=f"⚙️ Stub — {label} ({elapsed_ms:.0f}ms, no LLM)",
                state="complete",
                expanded=False,
            )
        return

    # Branch 3: live LLM. The running label is the user's main signal,
    # so we pack it with concrete info: backend identity + model name +
    # endpoint (Ollama only) + position counter. That answers
    # "what's being contacted?" without the user having to expand the box.
    #
    # We import dispatcher lazily so this UI module doesn't pull the LLM
    # client stack at module load — keeps the test suite light for
    # non-UI test cases.
    try:
        from clinitrace.llm import dispatcher  # noqa: PLC0415
        backend_name = dispatcher.backend_label()  # "Ollama" or "OpenAI"
        backend_module = dispatcher._backend_module()
        model_name = backend_module.model_name()
    except Exception:  # noqa: BLE001
        backend_name = "LLM"
        backend_module = None
        model_name = "(unknown model)"

    # Endpoint is meaningful for Ollama (localhost:11434 etc.) but
    # constant for OpenAI (api.openai.com). For the running label we
    # show backend + model; for the expanded body we add endpoint/timeout
    # details specific to the active backend.
    server_url: str | None = None
    timeout_s: float | None = None
    if backend_module is ollama:
        try:
            url, _, t = ollama._config()
            server_url = url
            timeout_s = t
        except Exception:  # noqa: BLE001
            pass
    else:
        # OpenAI client: it also has _config(), with a (key, model, timeout, base_url)
        # shape — but we never log the key. Pull only the non-secret bits.
        try:
            from clinitrace.llm import openai_client  # noqa: PLC0415
            _, _, t, base = openai_client._config()
            server_url = base or "api.openai.com"
            timeout_s = t
        except Exception:  # noqa: BLE001
            server_url = "api.openai.com"

    short_endpoint = (server_url or "").replace("http://", "").replace("https://", "")
    position_str = f" — call {position[0]} / {position[1]}" if position else ""

    # Format: `🤖 OpenAI: gpt-5-mini — call 1 / 1 — LLM augmentation…`
    # or:     `🤖 Ollama: gpt-oss:20b @ localhost:11434 — call 1 / 1 — …`
    if backend_module is ollama and short_endpoint:
        endpoint_in_label = f" @ `{short_endpoint}`"
    else:
        endpoint_in_label = ""
    running_label = (
        f"🤖 {backend_name}: `{model_name}`{endpoint_in_label}"
        f"{position_str} — {label}…"
    )

    with st.status(
        running_label,
        state="running",
        expanded=expanded,
    ) as status:
        status.write(f"**Backend**: {backend_name}")
        status.write(f"**Model**: `{model_name}`")
        if server_url:
            status.write(f"**Server**: `{server_url}`")
        if timeout_s is not None:
            status.write(f"**Timeout**: `{float(timeout_s):.0f}s`")
        if position is not None:
            status.write(f"**Position**: call **{position[0]} of {position[1]}**")
        status.write("📤 Sending request… (timer starts now; spinner runs until response or timeout)")
        if purpose:
            status.write(f"_{purpose}_")
        ctrl = LLMCallController(status, mode="live", started=time.monotonic())
        try:
            yield ctrl
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - ctrl.started
            status.update(
                label=(
                    f"⚠️ {backend_name} error after {elapsed:.1f}s "
                    f"on `{model_name}`{endpoint_in_label}{position_str} — {exc}"
                ),
                state="error",
            )
            raise
        elapsed = time.monotonic() - ctrl.started
        # Flag slow responses so the user can tell when the model is
        # struggling vs. when the call was crisp.
        speed_tag = "fast" if elapsed < 2 else ("normal" if elapsed < 10 else "slow")
        status.update(
            label=(
                f"🤖 {backend_name} ← `{model_name}`{endpoint_in_label}"
                f"{position_str} — {label} ({elapsed:.1f}s, {speed_tag})"
            ),
            state="complete",
            expanded=False,
        )


class LLMCallController:
    """Handle the caller uses to add detail lines to an open status box.

    The .mode attribute lets callers gate behaviour on whether they're
    in "deterministic", "stub", or "live" without having to re-read
    current_mode() inside the with-block (which could disagree with the
    branch we actually rendered).

    Lines added via .note() appear in the status box once it re-renders
    (which is when the with-block exits — Streamlit can't paint during
    a blocking Python call). So .note() is best for post-mortem detail:
    "matched rule_kind 'bin' with confidence 0.87", "augmented 2 new
    derivations", etc.
    """

    def __init__(
        self,
        status: "st.delta_generator.StatusContainer",
        *,
        mode: str,
        started: float,
    ):
        self._status = status
        self.mode = mode  # "deterministic" | "stub" | "live"
        self.started = started

    def note(self, text: str) -> None:
        """Append a line inside the status box."""
        self._status.write(text)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started
