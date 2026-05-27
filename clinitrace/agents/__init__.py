"""Agent modules: SR, CG, R, A, Orchestrator. V lives under clinitrace.verification.

Agents emit structured results back to the Orchestrator. They do NOT call each
other directly; the Orchestrator is the sole loop authority (_002 section 4.3).
"""
