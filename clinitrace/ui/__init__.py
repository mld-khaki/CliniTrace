"""Streamlit-based GUI surface for CliniTrace.

The Streamlit app is the minimal HITL surface locked in _002 section 5.3 plus
two extra tabs that make sense of finished runs (run inspector + LTM browser).
Optional dependency; install with `pip install -e .[gui]`.

Launch with:
    streamlit run -m clinitrace.ui.streamlit_app  -- --out demo_out --ltm demo_ltm.db
or simply:
    python -m clinitrace ui    (if/when a launcher subcommand is added)
"""
