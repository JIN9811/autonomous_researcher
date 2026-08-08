# PyAutoGUI Skill Capability Expansion Design

## Objective

Expand the Windows PyAutoGUI bridge and Equipment Skill pipeline so operators can
record, validate, compile, deploy, and test the safe core PyAutoGUI capability
families without exposing arbitrary Python, shell execution, file deletion, or
credential entry.

## Selected Approach

Use a hybrid capability catalog backed by one normalized action contract.

- Recorded demonstrations cover natural keyboard, click, drag, and scroll input.
- Parameterized examples cover actions whose intent cannot be recovered reliably
  from raw input alone, such as image matching, pixel assertions, screenshots,
  and window geometry.
- Both paths compile to `atr.pyautogui_program.v1`, use the same bridge allowlist,
  and traverse the existing Skill lifecycle.

Rejected alternatives:

- Directly exposing arbitrary PyAutoGUI function calls would bypass the current
  program schema and make validation and recovery unreliable.
- A recorder-only implementation cannot preserve image-locator intent, expected
  pixels, window selection, or deterministic postconditions.

## Supported Capability Families

### Pointer And Mouse

- Absolute and relative movement: `move_to`, `move_rel`.
- Clicks: single, multiple, double, triple, left, middle, and right.
- Button lifecycle: `mouse_down`, `mouse_up`.
- Dragging: `drag_to`, `drag_rel` with bounded duration and button.
- Wheel input: `scroll`, `hscroll`, and `vscroll`.
- Pointer query for execution evidence.

### Keyboard

- Text input with bounded length and interval.
- Repeated key presses with bounded count and interval.
- Hotkeys with bounded key count and interval.
- Explicit `key_down` and `key_up` for parameterized programs.
- The recorder groups modifier chords into one hotkey and never records password
  fields intentionally.

### Screen And Visual Location

- Full-screen and bounded-region screenshots.
- Image location, wait, center, and bounded locate-all results.
- Pixel read and pixel-color assertions with tolerance.
- Existing OCR text assertions and UIA locators remain available.

### Window Control

- Query and activate a selected window.
- Minimize, maximize, restore, move, and resize a selected window.
- Window close is excluded because it may discard unsaved equipment state.

### Operator Dialogs

- `alert` and `confirm` are represented in the contract but marked manual-test
  only because they block until an operator responds.
- `prompt` and `password` are excluded from recorded Skills to avoid accidental
  credential capture.

### Existing Runtime Operations

- Health, focus, waits, log events, file-stability waits, screenshots, UIA/image
  location, OCR assertions, and artifact transfer remain compatible.

## Safety Contract

- No shell, PowerShell, arbitrary Python, executable registration, file deletion,
  password entry, or unbounded loops.
- Coordinates must be inside the current screen unless an explicit relative move
  resolves inside the screen.
- Click count, key repeat count, drag duration, text length, scroll distance,
  screenshot region, and locate-all result count are bounded.
- `mouse_down` and `key_down` state is tracked and released in a `finally` block,
  including fail-safe and exception paths.
- PyAutoGUI fail-safe remains enabled.
- Blocking dialogs cannot be run by unattended automatic Skill tests.
- Every coordinate click and drag emits before/after evidence.

## Recording Upgrade

The recorder gains a dedicated mouse state machine.

- Press and release without meaningful movement becomes `mouse_click`.
- Press, movement beyond the drag threshold, and release becomes one
  `mouse_drag` event.
- Wheel events become `mouse_scroll` events with horizontal and vertical deltas.
- Sampled pointer moves are suppressed while a drag is active so replay does not
  duplicate the drag path.
- Existing hotkey grouping remains authoritative.

Compilation normalizes recordings before segmentation:

- Printable consecutive key presses become one bounded `write` action.
- Redundant adjacent pointer moves are coalesced.
- `mouse_drag` becomes `drag_to`.
- Vertical and horizontal wheel deltas become bounded scroll actions.
- A capability coverage summary is stored in the workflow and exposed to the GUI.
- Unsupported or intentionally excluded events block draft creation with a clear
  failure code instead of being silently dropped.

## Example Catalog

A self-contained local capability lab and example catalog provide:

1. Pointer navigation and multi-button click verification.
2. Drag-and-drop plus vertical and horizontal scrolling.
3. Text replacement, repeated key presses, and hotkeys.
4. Screenshot region, pixel assertion, and image-location verification.
5. Window activate, move, resize, minimize, maximize, and restore.
6. Manual alert/confirm verification.

Each example declares whether it is safe for unattended testing. Loading an
example only opens it in the Program Manager editor; registration and execution
remain separate explicit actions.

## GUI Changes

Add an `EXAMPLES` Program Manager tab.

- Show capability family, actions, safety level, prerequisites, and validation
  state.
- `Load Example` opens the exact JSON in the existing editor without registering
  it.
- `Run Safe Test` is shown only for unattended-safe examples.
- The Record tab shows captured capability coverage, event count, hotkey count,
  drag count, scroll count, and any blocked event kinds before Skill creation.
- Skill cards show compiled action coverage and last test status.

## Data Flow

```text
operator input or example
  -> Windows recorder/example catalog
  -> normalized recording/action contract
  -> Linux SkillRegistry draft
  -> annotate -> compile -> validate
  -> exact SHA-verified bridge registration
  -> test/live execution
  -> screenshots, traces, coverage, and postcondition evidence
```

## Error Handling

- Invalid parameters: `PYAUTOGUI_ACTION_PARAMETER_INVALID`.
- Coordinate outside screen: `PYAUTOGUI_COORDINATE_OUT_OF_BOUNDS`.
- Unsupported recording event: `SKILL_RECORDING_EVENT_UNSUPPORTED`.
- Blocking dialog in unattended test: `PYAUTOGUI_MANUAL_CONFIRMATION_REQUIRED`.
- Visual mismatch: existing locator failure plus expected/observed evidence.
- Any held mouse button or key is released before returning an error.

## Verification

- Unit tests fail first for every new recorder event, compiler normalization,
  validator rule, and executor action.
- Source and install bridge copies must remain byte-identical.
- Selenium validates the capability lab without external network access.
- Safe examples run through the ATR GUI proxy against the local X11 bridge.
- At least one recording is converted through the complete Skill lifecycle and
  replayed twice to prove deterministic replacement behavior.
- Existing Equipment Skill and UTM bridge regression suites remain green.

## Explicit Exclusions

- Arbitrary code or shell execution.
- File deletion and filesystem browsing outside existing approved artifacts.
- Credential/password recording or entry.
- Window close and process termination.
- Disabling PyAutoGUI fail-safe.
- Automatic execution of blocking dialogs.
