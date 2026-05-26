"""Faint-watermark background image for the Streamlit app.

Reads a PNG from disk, base64-embeds it into the HTML, and applies a
CSS rule that places it as a fixed background on the main app container.
A translucent white gradient overlays the image so content cards stay
legible — the overlay opacity is the knob that controls how visible the
wallpaper is.

Why base64 inline and not a /static/ URL:
  Streamlit's static-file serving depends on `server.enableStaticServing`
  and a `static/` folder next to the script. That works in most cases
  but breaks when the app is launched from an unexpected CWD or when
  Streamlit Cloud reshapes the deployment layout. Embedding the image
  as a base64 data URL sidesteps both — the image lives entirely in the
  HTML the browser receives.

Trade-off: the inline image bloats the initial HTML by ~1.5x the raw
PNG size (base64 overhead). For a 1.5 MB wallpaper that's an extra
~500 KB on first paint. Acceptable for a desktop demo; a production
deploy should switch to a CDN-served URL.

Why a translucent white overlay (not CSS `opacity` on the image):
  Setting `opacity` on the background-image element would also fade
  everything inside it — child content would inherit the alpha and
  become unreadable. The "two stacked backgrounds" trick (a
  `linear-gradient` of translucent white over the image) keeps content
  fully opaque while fading the image alone.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import streamlit as st

log = logging.getLogger("clinitrace.ui.wallpaper")


def _encode_image(path: Path) -> str | None:
    """Return base64-encoded PNG content, or None if the file can't be
    read. Fail-open: a missing wallpaper logs at debug level and the
    caller renders without one — never breaks the app.
    """
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        log.debug("wallpaper not loaded (%s): %s", path, exc)
        return None


def apply(image_path: Path, *, overlay_alpha: float = 0.82) -> None:
    """Inject CSS so the Streamlit app shows ``image_path`` as a fixed
    background watermark.

    Args:
        image_path: absolute path to the PNG file.
        overlay_alpha: opacity of the white overlay (0.0 = image fully
            visible, 1.0 = image fully hidden behind white). Default
            0.82 gives a "faint watermark" feel — image visible at ~18%.

    Idempotent across Streamlit reruns: calling this multiple times in
    one session re-emits the same CSS, which the browser dedupes by
    rule. Safe to put in ``main()`` before any other rendering.
    """
    encoded = _encode_image(image_path)
    if encoded is None:
        return

    # `linear-gradient` of two stacked solid colours is the simplest way
    # to lay a translucent white sheet over the image without affecting
    # child content. Both layers use the same `rgba(255,255,255,α)` so
    # the result is a uniform white veil.
    alpha = max(0.0, min(1.0, overlay_alpha))
    css = f"""
    <style>
    [data-testid="stAppViewContainer"] {{
        background-image:
            linear-gradient(rgba(255,255,255,{alpha:.3f}),
                            rgba(255,255,255,{alpha:.3f})),
            url("data:image/png;base64,{encoded}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
        background-repeat: no-repeat;
    }}
    /* Header bar also gets the same treatment so it doesn't look like
       a solid stripe of contrasting colour above the watermarked page. */
    [data-testid="stHeader"] {{
        background-color: rgba(255,255,255,0);
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
