# Screenshots for README

The README links to three PNGs in this folder. They are not generated
automatically -- capture them once after a clean demo run, drop them in
this folder, and the links resolve.

## Prep

1. From the repo root, do one clean demo run with a known reviewer
   question still open:

       python -m clinitrace run \
           --spec examples/demo_spec.yaml \
           --data examples/demo_data.csv \
           --out demo_out \
           --ltm demo_ltm.db

   Do not pass `--replay`. We want the ambiguity ticket on RESPONSE_FLAG
   to still be open when the GUI loads.

2. Launch the GUI:

       python -m clinitrace ui

3. In the sidebar, confirm Runs folder is `demo_out` and Memory file is
   `demo_ltm.db`.

## What to capture

Use a browser window roughly 1440 wide. PNG format. Crop or shrink for
the README; the originals can live full-size here.

- `menu.png` -- the sidebar navigation visible, with **IDC Rulebook**
  selected and the **Pending** tab open. Capture from the top of the page
  through the first reviewer prompt so the navigation and the locked HITL
  surface are both in frame.

- `review_questions.png` -- the IDC Rulebook Pending tab mid-decision:
  ticket prompt expanded, an option selected, the free-text reasoning
  box populated. Show that the action is a single Save your decision
  button below.

- `documentation_tutorial.png` -- click Documentation in the sidebar,
  then Tutorial in the sub-menu. Capture the heading "How CliniTrace
  works" and at least the first three bullets of the agent roster.

## Filename discipline

Filenames are referenced verbatim from `repo/README.md`. If you rename a
screenshot, update the README link too.
