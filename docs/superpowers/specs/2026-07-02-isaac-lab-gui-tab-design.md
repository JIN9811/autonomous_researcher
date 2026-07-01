# Isaac Lab GUI Tab Split Design

Date: 2026-07-02

## Objective

Separate the Isaac Lab workflow from the dense LeRobot main workflow page without changing the training pipeline or Isaac Sim runtime.

The LeRobot GUI should keep section 7 as a small launcher. When the operator clicks the launcher, the same browser window should switch to an internal `Isaac Lab` tab inside the LeRobot GUI. The new tab should contain the controls currently embedded in section 7 for Isaac Lab synthetic intelligence, including validation, build, HDF5 export, Mimic, RL teacher, status, progress, and reports.

## Explicit Non-Goals

- Do not change LeRobot training command construction, dataset mix logic, fidelity weighting, or training adapters.
- Do not change Isaac Sim mirror, Isaac stage files, USD physics, active robot-cam, or teleoperation runtime behavior.
- Do not implement the real Isaac Lab `RobotisOMXPickPlace` environment in this GUI split pass.
- Do not change existing `/api/lerobot/isaac-lab/*` endpoint behavior unless a UI-only payload compatibility issue is found.

## Current State

The current LeRobot GUI is a single long page with anchor navigation. Section 7, `Isaac Lab Synthetic Intelligence`, currently lives inside the `Augment` workflow card and mixes these responsibilities:

- Replicator and common image/depth augmentation setup.
- Isaac Lab path, Isaac Sim Python path, and stage path controls.
- HDF5 export hook.
- Mimic and RL teacher hook controls.
- Synthetic status cards, progress bar, step trace, and full response output.

This makes the main operator page too crowded and makes Isaac Lab feel like a subsection of augmentation even though it is becoming its own workflow.

## Chosen Approach

Use an in-page tab system.

The existing LeRobot page remains the only browser page. A lightweight tab bar is added near the top of the GUI. The default tab is `LeRobot`. A second tab, `Isaac Lab`, is available but initially can be hidden or inactive until launched. Clicking the section 7 launcher activates the `Isaac Lab` tab and scrolls/focuses to the top of that tab.

This approach matches the requested behavior: same LeRobot GUI window, new internal tab, automatic switch to the Lab GUI.

## Page Structure

### Main LeRobot Tab

The main tab keeps the current operator workflow:

- Profile and execution.
- Device port setup.
- Isaac Sim link.
- Local paths.
- Teleoperation.
- Recording.
- Augmentation.
- Visualization.
- Training.
- Rollout.
- Manipulation Agent.
- Logs.

Section 7 is reduced to a compact launcher:

- Title: `7. Isaac Lab Synthetic Intelligence`
- Short status summary showing the latest Lab sidecar state if available.
- Primary button: `Open Isaac Lab GUI`
- Optional small links or badges:
  - latest output root
  - latest validation state
  - latest Mimic/RL job state

The old Lab controls are removed from this section and moved to the `Isaac Lab` tab.

### Isaac Lab Tab

The Isaac Lab tab is a dedicated workflow surface with five groups:

1. Setup
   - Synthetic pipeline mode.
   - Fallback policy.
   - Source intent.
   - Isaac Lab path.
   - Isaac Sim Python path.
   - Isaac stage path.
   - Enable Replicator, HDF5 export, Mimic, and RL teacher.

2. Build and Export
   - Check Digital Twin.
   - Build Synthetic Dataset.
   - Run Replicator Worker.
   - Run Replicator Smoke.
   - Preview Synthetic Sources.
   - Export HDF5.

3. Mimic
   - Mimic trials.
   - Mimic env count.
   - Run Mimic.
   - Run Mimic Smoke.
   - Mimic Status.
   - Stop Mimic Job.

4. RL Teacher
   - RL teacher steps.
   - Run RL Teacher.
   - Run RL Smoke.
   - RL Status.
   - Stop RL Job.

5. Reports
   - Compatibility card.
   - Digital twin card.
   - Source labels card.
   - Canonical index card.
   - Generation card.
   - HDF5 card.
   - Training exposure card.
   - Progress bar.
   - Step trace.
   - Full response output.

The controls keep their existing DOM IDs where practical so the current JavaScript functions can be reused. When DOM IDs must move, the move should preserve one unique element per ID.

## Interaction Design

### Tab Behavior

- The default visible tab is `LeRobot`.
- The `Isaac Lab` tab appears in the tab bar.
- Clicking `Open Isaac Lab GUI` does three things:
  - activates the `Isaac Lab` tab
  - marks the `Isaac Lab` tab as selected
  - focuses the first Isaac Lab action/status element
- Clicking the `LeRobot` tab returns to the main workflow without losing form values.
- Tab state should be local to the browser page. It does not need backend persistence.

### Section 7 Launcher

The launcher should not duplicate all Isaac Lab controls. It should show only enough information to make the operator comfortable switching:

- whether latest Lab sidecar exists
- latest synthetic status if available
- button to open the Lab tab

### Status And Errors

Existing `runIsaacSyntheticAction()` behavior should be reused:

- request running state
- timeout handling
- response rendering
- progress rendering
- step trace rendering

If the Isaac Lab tab is not visible when a Lab action completes, the status still updates in the hidden tab. No toast system is required for this pass.

## Data Flow

No backend data flow changes are intended.

The new tab continues to call the existing endpoints:

- `/api/lerobot/isaac-lab/validate`
- `/api/lerobot/isaac-lab/prepare`
- `/api/lerobot/isaac-lab/build-synthetic`
- `/api/lerobot/isaac-lab/run-replicator-worker`
- `/api/lerobot/isaac-lab/preview`
- `/api/lerobot/isaac-lab/export-hdf5`
- `/api/lerobot/isaac-lab/run-mimic`
- `/api/lerobot/isaac-lab/run-mimic-smoke`
- `/api/lerobot/isaac-lab/mimic/status`
- `/api/lerobot/isaac-lab/mimic/stop`
- `/api/lerobot/isaac-lab/run-rl-teacher`
- `/api/lerobot/isaac-lab/run-rl-teacher-smoke`
- `/api/lerobot/isaac-lab/rl-teacher/status`
- `/api/lerobot/isaac-lab/rl-teacher/stop`
- `/api/lerobot/isaac-lab/e2e-smoke`
- `/api/lerobot/isaac-lab/status`

The payload builder can remain `buildIsaacSyntheticPayload()` unless moving fields requires a small selector update.

## Implementation Boundaries

Files expected to change:

- `web/templates/lerobot.html`
- `web/static/lerobot.js`
- `web/static/styles.css`
- `tests/unit/test_lerobot_gui_static.py`

Files that should not change in this pass:

- `device_bridges/lerobot_bridge.py`
- `device_bridges/isaac_lab_synthetic.py`
- training process code
- Isaac Sim mirror extension code
- USD scene files
- active robot-cam code

If a test exposes a missing UI-only selector or stale DOM assumption, fix it only in the frontend files above.

## Testing Plan

Static tests should verify:

- The main LeRobot GUI has a tab bar with `LeRobot` and `Isaac Lab`.
- Section 7 contains `Open Isaac Lab GUI`.
- Section 7 no longer contains the full Isaac Lab control set.
- The moved Isaac Lab tab still contains all existing control IDs used by JavaScript.
- JavaScript binds the launcher button to activate the Isaac Lab tab.
- Existing Isaac Lab action endpoints remain wired.

Browser smoke should verify:

- Page loads without console errors.
- Default tab is `LeRobot`.
- Clicking `Open Isaac Lab GUI` switches to `Isaac Lab`.
- Clicking `LeRobot` switches back.
- Form values remain stable across tab switches.
- No training or Isaac Sim runtime endpoint is called by tab switching alone.

## Acceptance Criteria

- Section 7 is reduced to a launcher and latest-status summary.
- A dedicated Isaac Lab tab exists inside the same LeRobot GUI page.
- Clicking the launcher switches to the Isaac Lab tab.
- Existing Isaac Lab buttons and status cards are still present in the Isaac Lab tab.
- Training pipeline behavior is unchanged.
- Isaac Sim mirror/runtime behavior is unchanged.
- Static tests pass.
- A browser smoke test confirms the tab switch works.

## Follow-Up Improvements

After the UI split is stable, the next work should be planned separately:

- Replace the current manifest/dry-run Mimic bridge with a real Isaac Lab task registration flow.
- Convert exported HDF5 to Isaac Lab dataset handler metadata conventions, including `env_args.env_name`.
- Fix the live Mimic runner command to match the local Isaac Lab CLI.
- Add a real `RobotisOMXPickPlaceMimicEnv` extension or external callback.
- Import real generated Mimic successes into `training_import/manifest.jsonl`.

Those items are intentionally not part of this GUI split.
