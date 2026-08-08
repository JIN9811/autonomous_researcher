# PyAutoGUI Recorded Image Locator Implementation Plan

> Execute with test-driven development. Do not commit until the user reviews the result.

## Goal

Turn newly recorded PyAutoGUI demonstrations into portable, image-first Skills
that follow visible controls instead of replaying stale screen coordinates.

## Task 1: Lock the recording contract with failing tests

Files:

- `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- `tests/unit/test_equipment_skill_runtime.py`

Steps:

1. Add fake screenshot support for crop, PNG serialization, and dimensions.
2. Test click source capture, drag source/target capture, and explicit capture failure.
3. Test image-first compiler output and missing-locator rejection.
4. Run the focused tests and confirm they fail for the missing behavior.

## Task 2: Implement bounded visual capture

Files:

- `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`

Steps:

1. Add screenshot provider injection to `RecordingManager`.
2. Capture press/release frames without changing keyboard recording behavior.
3. Save full-frame local evidence and embed bounded tight/context PNG crops.
4. Add visual policy metadata to new recordings.
5. Enforce PNG, event-count, per-crop, and total-payload limits.
6. Run the recorder tests.

## Task 3: Compile image-first pointer actions

Files:

- `utils/equipment_skill_runtime.py`
- `tests/unit/test_equipment_skill_runtime.py`

Steps:

1. Preserve visual locator candidates in click and drag actions.
2. Omit executable x/y fields when coordinate fallback is disabled.
3. Reject required missing locators with a stable contract error.
4. Preserve legacy v1 coordinate compilation.
5. Run compiler and Skill API tests.

## Task 4: Execute inline image candidates

Files:

- `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

Steps:

1. Verify and materialize inline PNG candidates under the locator cache.
2. Extend locator resolution to try tight and context candidates in order.
3. Allow image-resolved `move_to` and `drag_to` while retaining coordinate actions.
4. Capture failure evidence and return `UI_LOCATOR_NOT_FOUND` without silent fallback.
5. Run action executor tests.

## Task 5: Add Program Manager visibility

Files:

- `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

Steps:

1. Add image tracking and explicit coordinate fallback controls.
2. Send policy fields to `/recordings/start`.
3. Render locator coverage and bounded crop previews.
4. Show blocked draft readiness when required captures are unavailable.
5. Run HTML contract tests and browser inspection.

## Task 6: Synchronize and verify

Files:

- `install/windows_pyautogui_bridge_server.py`
- `REQUIREMENTS.md`
- `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- `docs/tutorials/user_manual.ko.md`

Steps:

1. Copy the verified source bridge to the install bridge.
2. Document Pillow/OpenCV confidence requirements and image-first behavior.
3. Run focused unit and integration suites.
4. Run bridge source/install parity.
5. Run Selenium/browser verification.
6. Report residual hardware-only validation without committing.
