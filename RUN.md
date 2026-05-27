# Running CliniTrace

Two clear entry points for different workflows:

## 1. **Interactive Web UI** (Recommended for Human-in-the-Loop)

```bash
python -m clinitrace ui
```

Launches a Streamlit web interface for:
- Reviewing and approving transformation rules
- Resolving ambiguities (HITL workflow)
- Viewing audit trails and run history
- Browsing long-term memory

**Default:** http://localhost:8501

**Options:**
```bash
python -m clinitrace ui --host 0.0.0.0 --port 8000
```

---

## 2. **Batch CLI** (For Automation & Testing)

```bash
python -m clinitrace run \
  --spec examples/demo_spec.yaml \
  --data examples/demo_data.csv \
  --out ./runs
```

For batch processing with optional pre-recorded reviewer decisions:

```bash
python -m clinitrace run \
  --spec examples/demo_spec.yaml \
  --data examples/demo_data.csv \
  --out ./runs \
  --replay examples/demo_resolutions.json \
  --poll-timeout 120
```

**Options:**
- `--verbose`: Stream per-stage progress
- `--ltm PATH`: SQLite LTM database (default: `ltm.db`)
- `--no-ltm`: Skip memory (fresh run)
- `--poll-timeout SEC`: Wait time for HITL resolutions (default: 60)
- `--poll-interval SEC`: Outbox check interval (default: 0.5)

---

## Requirements

```bash
pip install -e "."  # Installs clinitrace, Streamlit, and option-menu
```

Or for batch only:
```bash
pip install -e "."  # Minimal dependencies
```

---

## Demo

Both modes work with the included demo:

```bash
# Interactive: click through the UI
python -m clinitrace ui

# Or batch: auto-resolves from replay file
python -m clinitrace run \
  --spec examples/demo_spec.yaml \
  --data examples/demo_data.csv \
  --out ./demo_run \
  --replay examples/demo_resolutions.json
```

---

## Demo scenarios - "where does the LLM fire?"

Two specs ship with the repo:

- **`demo_spec.yaml`** - strict, fully-specified. Used to show the happy
  path and the LTM-warm flow. SR finds at most one ambiguity (the
  `unknown` response value); CG never invokes the LLM because the rule
  bodies are already valid Pydantic.

- **`demo_spec_ambiguous.yaml`** - every rule has a deliberate
  rationale-vs-body gap. With cold LTM and live LLM enabled, SR has to
  invoke for each gap and CG has to normalise a real LLM completion into
  a validated body.

Datasets under `examples/demo_datasets/` pair with the ambiguous spec to
isolate one issue at a time:

| Dataset                    | Exposes the gap in | What goes wrong                                           |
|----------------------------|---------------------|-----------------------------------------------------------|
| `clean.csv`                | (control)           | Nothing - happy path                                      |
| `unknown_response.csv`     | RESPONSE_FLAG       | 30% have `response='unknown'`, not in the mapping         |
| `pediatric.csv`            | AGE_GROUP           | Patients under 12 - missing pediatric stratum             |
| `negative_duration.csv`    | TREATMENT_DURATION  | `visit_date` before `treatment_start_date` (EDC error)    |
| `short_exposure.csv`       | ANALYSIS_POP_FLAG   | <7 days of treatment - third inclusion criterion missing  |
| `critical_labs.csv`        | RISK_GROUP          | Young patient with critical lab - should be 'high'        |
| `garbled_labs.csv`         | RISK_GROUP          | Free-text lab values ('N/A', 'pending') - type errors     |

### Cold-LTM, live-LLM batch run

The combination that actually forces the LLM to fire:

```bash
# Wipe the LTM so CG can't short-circuit via the rule-pattern cache.
rm -f demo_ltm.db ltm.db

# Live LLM via Ollama (default model: gpt-oss:20b, default URL: localhost:11434).
# Pair the ambiguous spec with the matching replay file so all 5 gaps get
# resolved headlessly.
CLINITRACE_LLM=live python -m clinitrace run \
  --spec examples/demo_spec_ambiguous.yaml \
  --data examples/demo_datasets/unknown_response.csv \
  --replay examples/demo_resolutions_ambiguous.json \
  --out demo_out \
  --no-ltm
```

Expected counts on the first cold-LTM run:
```
sr_findings: 5, hitl_tickets_opened: 5, cg_ltm_hits: 0
ltm writes: {rule_patterns: 5, ambiguity_resolutions: 5}
```

Re-running the same command (with LTM enabled this time) should flip to:
```
sr_findings: 5, sr_auto_resolved: 5, hitl_tickets_opened: 0, cg_ltm_hits: 5
```
This is exactly the agentic memory loop the design doc describes.

### Cold-LTM, live-LLM, interactive HITL via UI

1. Settings > **Reset everything** > tick **LTM database** > confirm.
2. Settings > enable LLM (Local Ollama), save.
3. **Import new DB** > upload `unknown_response.csv` > pick the
   `demo_spec_ambiguous.yaml`.
4. **IDC Clarifications** lists each gap; resolve them one by one.
5. Re-run the same task; LTM hits resolve the ambiguities automatically
   and the LLM stays silent.

---

## Reset everything

To wipe user state between demos:

**Via UI:** Settings page > expand **Reset everything (advanced)** >
tick what you want to remove > confirm. You can selectively wipe:
- Settings file (`.clinitrace_settings.json`)
- LTM database (`demo_ltm.db`)
- Task history (`demo_out/run-*`)

The preview pane shows the exact paths + sizes before you click.

**Via shell:** `rm -f .clinitrace_settings.json demo_ltm.db ltm.db && rm -rf demo_out/run-*`
