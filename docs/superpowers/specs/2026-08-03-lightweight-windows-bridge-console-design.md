# Windows Bridge Console Simplification Design

## Objective

Provide a Windows-local macro setup console, not a runtime control room. The default surface manages bridge connectivity and registered PyAutoGUI macro files. Low-level calibration, evidence, UTM parameter editing, and raw execution diagnostics live only in Advanced Tools.

## Boundary

### Changed

- Connection and PyAutoGUI health display.
- Persistent JSON macro registry under `WINDOWS_PYAUTOGUI_PROGRAM_DIR`.
- Program list sourced from `GET /programs`, including built-in and custom macros.
- Separate New, Browse JSON, Download Template, Validate, and Add/Update Registry operations.
- Existing-program Test action through authenticated `POST /execute`.
- A non-overlapping Advanced Tools surface for diagnostics and low-level configuration.

### Unchanged

- Bridge Python execution logic.
- HTTP endpoint set and payload contracts.
- Built-in program definitions and UTM sequences.
- Token validation, request audit, screenshots, locators, and artifacts.
- Linux Lab Equipment Workspace ownership of UTM operation and evidence.
- Existing console access to readiness, safe preflight, screenshots, locator capture, artifacts, request logs, generic sequence execution, and UTM simulation/live/abort actions.

## Default Screen Layout

1. **Bridge Connection**: token, Health, Refresh, bridge reachability, and PyAutoGUI availability.
2. **Program Manager**: compact rows for built-in and custom macros. `Program1` appears here and has no separate quick-action button.
3. **Program Editor**: hidden until New Program, Browse JSON, or Edit. It exposes the entire JSON definition, not only presentation metadata.
4. **Latest Test Result**: concise response from validate, register, delete, refresh, or test.

The default surface does not include UTM quick actions, artifact controls, request-log controls, or runtime-monitoring cards.

## Advanced Tools Ownership

Advanced Tools is closed by default and owns only features not present on the default surface:

- deployment URL/environment helpers;
- readiness and locator calibration;
- screenshot/OCR/image diagnostics;
- UTM parameter and payload editing;
- evidence, artifacts, request audit, and timeline inspection;
- generic JSON execution and raw result/trace views.

It must not repeat Bridge Token, Health, Program1, Program Manager, or generic registered-program Test controls.

## Simplification Rule

Simplification means reducing visual clutter, grouping related controls, and improving labels. It does not mean deleting backend-supported controls or hiding the only UI path to a function. The default program set must remain visible after connection:

- `program1`
- `utm_compression_start_v1`
- `utm_export_csv_v1`
- `utm_manual_save_csv_v1`
- `utm_stop_or_abort_v1`

## Manager Contract

Program records are server-authoritative JSON files stored under `WINDOWS_PYAUTOGUI_PROGRAM_DIR`, defaulting to `C:\ATR\programs` on Windows.

- `New Program` opens a blank editor and does not register anything.
- `Browse JSON` reads one local `.json` file into the editor and does not register it.
- `Download Template` downloads an editable `atr.pyautogui_program.v1` JSON template and does not register it.
- `Validate` calls `POST /programs/validate` and never writes a file.
- `Add to Registry` or `Update Registry` calls `POST /programs/register`; only a valid definition is written.
- `Delete` calls `DELETE /programs/{program_id}` and applies only to custom macros.
- Built-ins, including `program1`, are read-only and cannot be deleted or overwritten. They may still be tested from Program Manager.
- Test calls the existing authenticated `POST /execute` endpoint with the selected `program_id`.
- Browser `localStorage` is not a program registry.

## Macro File Contract

```json
{
  "schema": "atr.pyautogui_program.v1",
  "program_id": "my_macro",
  "name": "My Macro",
  "description": "Bounded Windows GUI operation",
  "enabled": true,
  "program_type": "macro",
  "sequence": [
    {"action": "press", "key": "esc"},
    {"action": "log", "message": "macro completed"}
  ]
}
```

Validation requirements:

- JSON object with exact schema `atr.pyautogui_program.v1`.
- `program_id` matches `[A-Za-z0-9_-]{1,64}` and does not collide with a built-in ID.
- `name` is non-empty.
- `sequence` contains 1 to 100 object steps.
- Every `action` is already supported by the bounded bridge executor.
- Shell commands, arbitrary Python, PowerShell, BAT, CMD, and EXE registration are rejected.
- Files are written atomically as `<program_id>.json` inside the configured program directory.

## Token Handling

- Direct Windows page: token is held in tab-scoped `sessionStorage`.
- ATR proxy page: token input is disabled and the Linux proxy injects the saved token server-side.
- Tokens are not written to shortcut storage or URLs.

## Verification

- Confirm packaged and install server copies are identical.
- Confirm validation cannot overwrite built-ins or escape the program directory.
- Confirm Browse and template download do not call register.
- Confirm Add/Update persists and survives a server/module reload.
- Confirm custom registered programs execute through the existing bounded sequence executor.
- Run focused bridge tests.
- Run Selenium at 1920x1080 and verify distinct New/Browse/Template/Add behavior, Program1 in Program Manager, Advanced closed, and no horizontal overflow.
