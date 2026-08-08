# Advanced Visual Work Queue Skill Design

## Goal

Prove that an ATR Equipment Skill can reproduce a realistic multi-window work-queue workflow using recorded visual locators rather than recorded click coordinates. The replay must remain correct after windows move, source rows reorder, and intermediate dialogs appear.

## Operator Workflow

1. Open the work-queue application in its initial layout.
2. Open a separate input browser and select a validated specimen batch.
3. Select the source table row identified by `specimen-beta`, independent of row order.
4. Drag the selected specimen card into the analysis queue.
5. Open the queued item's configuration dialog.
6. Select the `Compression` method, enable evidence capture, and enter `12.5` as the load limit.
7. Start analysis and wait for the progress state to reach completion.
8. Verify that the completed result identifies `specimen-beta`, `Compression`, evidence enabled, and load limit `12.5`.
9. Open the export dialog, select JSON and CSV, enter `advanced_queue_result`, and save both artifacts.
10. Verify both files exist and contain the same specimen identity and analysis settings.

## Replay Challenge

The replay layout changes all target positions and reverses the source table order. The selected row therefore moves to a different screen position. Every semantic click and both drag endpoints must resolve from recorded tight/context image candidates. Recorded pointer coordinates may remain only as non-executing audit metadata; compiled click and drag actions must not contain executable coordinate fallback.

## Conditional Recovery

The first analysis attempt intentionally exposes a recoverable validation banner when the evidence checkbox is not observed. The Skill may perform one bounded recovery:

1. Capture failure evidence.
2. Reopen the configuration dialog using an image locator.
3. Enable evidence capture.
4. Submit the configuration and retry analysis once.

If the required row, queue target, dialog control, completion state, or export target cannot be visually resolved after the bounded retry, execution stops with a stable failure code. It must never click a recorded coordinate as a fallback.

## Components

### Deterministic Demo Application

A Tk application provides four independently positioned surfaces:

- Main work queue with source table, queue lane, progress, and result summary.
- Input browser for batch selection.
- Configuration dialog for method, evidence, and load limit.
- Export dialog for format selection and output name.

The application writes a machine-readable state file after each transition. It supports `initial`, `shifted`, `reordered`, and `missing_target` modes without changing labels or expected business output.

### Recording and Compilation

The existing Windows PyAutoGUI bridge records pointer and keyboard events with `image_tracking=true` and `coordinate_fallback=false`. ATR compiles the saved recording into an Equipment Skill package. The package uses the existing `atr.equipment_skill.v1` and `atr.pyautogui_program.v1` contracts.

### Visual Replay

Inline image locators use the bridge's global-best OpenCV matching. Context candidates are preferred over tight candidates where repeated controls exist. Clicks and drag endpoints fail closed when the target is absent or ambiguous.

### Artifact Verification

Replay success requires all of the following:

- GUI state reaches `exported`.
- Result summary contains the expected specimen and configuration.
- JSON output parses and equals the expected object.
- CSV output has one data row with matching values.
- Before, completed, and target-absent screenshots are valid PNG files.

## Error Handling

- Missing source row: `UI_LOCATOR_NOT_FOUND` before queue mutation.
- Missing drag destination: `UI_LOCATOR_NOT_FOUND` with screenshot evidence.
- Validation banner after the permitted recovery: `WORKFLOW_VALIDATION_FAILED`.
- Analysis timeout: `WORKFLOW_COMPLETION_TIMEOUT`.
- Missing or inconsistent output files: `ARTIFACT_VALIDATION_FAILED`.
- Target application absent: first required visual action blocks without coordinate fallback.

## Test Strategy

1. Unit-test global-best image matching for repeated controls.
2. Unit-test recorded drag compilation removes executable source and destination coordinates.
3. Record and compile the full workflow through the real bridge binary.
4. Replay in shifted and reordered mode and compare JSON/CSV content.
5. Exercise the one-retry validation recovery.
6. Remove the target application and verify fail-closed behavior.
7. Run the Equipment Skill runtime, bridge helper, demo asset, and API regression suites.

## Constraints

- Do not alter the existing ATR main server or active model processes.
- Do not add shell execution, arbitrary Python execution, password entry, or process termination to a Skill.
- Preserve source/install Windows bridge byte equality.
- Do not modify existing validated Skill packages.
- Do not commit before user review.

## Acceptance Criteria

- The workflow is recorded, compiled, validated, and replayed as an Equipment Skill.
- Shifted windows and reordered source rows do not change the selected specimen or output.
- All semantic clicks and drag endpoints use image locators with no coordinate fallback.
- Exactly one bounded recovery is demonstrated.
- JSON and CSV outputs match expected values.
- Missing targets stop safely with screenshot evidence.
- Relevant automated tests pass.

## Verified Implementation

The inline implementation completed the isolated E2E contract on 2026-08-08.
The recorder retains a bounded in-memory pointer-frame history and selects a
recent pre-hover frame, while the deterministic demo uses stable active colors
for recorded controls. This prevents hover styling from becoming the only
executable visual template.

The verified run records 180 input events, compiles two image-only program
segments, and replays them through the exact packaged bridge on Xvfb `:99` and
port `8878`. Shifted/reordered replay selected `specimen-beta`, produced
matching JSON/CSV output for `Compression` at load limit `12.5`, and completed
with `analysis_attempts=2` and `recovery_count=1`. Missing-target replay blocked
at the drag-source locator with `UI_LOCATOR_NOT_FOUND`, an empty queue, and zero
analysis attempts. Generated evidence and the immutable package remain under
the runtime paths documented in the Windows bridge setup guide.
