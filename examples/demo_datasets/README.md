# Demo datasets

Each CSV here exposes a different clinical-data-quality issue, paired with
the ambiguous spec at `examples/demo_spec_ambiguous.yaml`. Together they
form the demo script for showing the agentic loop:

  - **SR** sees a rationale-vs-body gap and emits a ticket.
  - **HITL** opens in the UI; reviewer picks a resolution.
  - **CG** invokes the LLM (live mode, cold LTM) to normalise the patched body.
  - **V** runs L1+L2+L_p deterministic checks.
  - **A** writes lineage + audit trail.
  - **LTM** captures the resolved pattern so the next run skips the LLM.

| Dataset                          | Pairs with rule       | The clinical issue                                                   |
|----------------------------------|-----------------------|----------------------------------------------------------------------|
| `clean.csv`                      | (all)                 | Control. Nothing to flag; demonstrates the happy path.               |
| `unknown_response.csv`           | RESPONSE_FLAG         | 30% of patients have `response='unknown'` — not in the mapping.      |
| `pediatric.csv`                  | AGE_GROUP             | Several patients under 12 — exposes the missing pediatric stratum.    |
| `negative_duration.csv`          | TREATMENT_DURATION    | Three rows have `visit_date` BEFORE `treatment_start_date`.          |
| `short_exposure.csv`             | ANALYSIS_POP_FLAG     | Several patients had <7 days of treatment exposure.                  |
| `critical_labs.csv`              | RISK_GROUP            | A 30-year-old with lab=92 — should be 'high' per rationale.          |
| `garbled_labs.csv`               | RISK_GROUP            | Free-text lab values ('N/A', 'pending', '<5') — surfaces type errors.|

## How to demo

Cold LTM, live LLM, headless replay (CI-friendly):

```sh
CLINITRACE_LLM=live uv run clinitrace run \
  --spec examples/demo_spec_ambiguous.yaml \
  --data examples/demo_datasets/unknown_response.csv \
  --replay examples/demo_resolutions.json \
  --out demo_out --no-ltm
```

Cold LTM, live LLM, interactive HITL via the UI:

1. Settings → enable LLM, save.
2. Settings → Reset everything → tick "LTM database" → confirm.
3. New Import Task → upload `unknown_response.csv` → pick the ambiguous spec.
4. SR flags 1+ ticket on the IDC Clarifications page → resolve.
5. Watch CG invoke the LLM to normalise; V validates; A writes lineage.
6. Re-run the same task → SR finds the same issue, but LTM auto-resolves.
