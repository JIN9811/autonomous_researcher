# Recorded Complex PyAutoGUI Demos Design

## Goal

Add two independently recorded Equipment Skills that exercise multi-step desktop automation without changing the existing bridge execution contract.

## Skills

### Text Editor Workflow

The operator recording opens the local text editor, enters deterministic demo text, performs a select/copy/paste editing operation, and saves the result to `/tmp/atr_pyautogui_text_demo.txt`. A checkpoint screenshot is captured after the saved document is visible.

### Browser Form Workflow

The operator recording opens a repository-owned local HTML form, fills text and numeric fields, changes a select field, submits the form, and leaves a deterministic success result visible. A checkpoint screenshot is captured after submission. The demo does not access an external website.

## Architecture

Each workflow is one separate `atr.equipment_recording.v1` artifact and one separate `atr.equipment_skill.v1` package. Recorded keyboard and pointer events compile only to the bridge's existing bounded actions. Checkpoints remain evidence artifacts and each Skill follows the existing draft, annotation, compilation, validation, deployment, and test lifecycle.

The browser form is a static repository asset. The text editor output is a disposable local file. Neither workflow changes UTM programs, production Equipment Agent routing, or live hardware behavior.

## Safety

- Target profile is `local_development` only.
- No external network request is required.
- No privileged command is used.
- No physical equipment command is issued.
- Existing user files are not modified.
- The bridge PyAutoGUI fail-safe remains enabled.

## Verification

- Both recordings contain multiple input events and at least one checkpoint.
- Both Skill packages validate exact hashes and reach `deployed` lifecycle.
- Program Manager lists both compiled programs.
- Skill Manager can run `Test` for each Skill through the GUI proxy path.
- The text demo file contains the expected text.
- The browser checkpoint shows the submitted result.

## Change Control

The work remains uncommitted until the user inspects the deployed demos.
