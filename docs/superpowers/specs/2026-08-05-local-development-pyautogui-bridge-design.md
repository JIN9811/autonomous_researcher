# Local Development PyAutoGUI Bridge Design

## Objective

Add a second, localhost-only PyAutoGUI bridge that controls the current Ubuntu desktop through the same authenticated HTTP API, Web GUI, Program Manager, and macro schema used by the deployable Windows bridge. Operators develop and validate bounded GUI programs on the ATR workstation, then transfer the same program JSON to another Windows PC and recalibrate only platform-specific window and visual locators.

## Current Environment

- Host OS: Ubuntu desktop
- Session: X11 on `DISPLAY=:1`
- ATR GUI: port `7860`
- Windows bridge default: port `8765`
- Local development bridge: `127.0.0.1:8767` (`8766` is reserved for the Isaac Sim OMX mirror receiver)
- Pillow and OpenCV are installed.
- PyAutoGUI, python3-xlib, scrot, wmctrl, and xdotool must be added to the project installation requirements.

Wayland is not accepted for actual local control. The local bridge must report a blocked readiness state with `PYAUTOGUI_LOCAL_DISPLAY_UNSUPPORTED` unless an X11 display is available.

## Architecture

### Shared bridge application

The existing bridge server remains the single implementation of:

- token authentication;
- `/health`, `/programs`, validation, registration, deletion, and `/execute`;
- Program Manager and operator Web GUI;
- action allowlisting, request audit, screenshots, artifacts, and PyAutoGUI fail-safe;
- macro schema `atr.pyautogui_program.v1`.

The install copy remains byte-identical to the primary bridge server.

### Platform adapter boundary

Desktop-specific behavior is selected by `--platform auto|windows|linux`:

- `auto` resolves from `sys.platform`;
- `windows` preserves current Windows paths, window activation, UIA, and PowerShell packaging behavior;
- `linux` uses X11-compatible PyAutoGUI, `wmctrl`/`xdotool` window activation, and `scrot` screenshots without pretending that Windows UIA selectors are supported.

Common actions such as mouse movement, click, keyboard input, screenshot, image matching, waits, logs, and registered-program execution retain identical request and response contracts. Windows-only locator fields return an explicit portability warning during Linux validation rather than being silently accepted as tested.

### Local bridge supervisor

ATR owns one supervised local process with this effective command:

```bash
python Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py \
  --platform linux \
  --host 127.0.0.1 \
  --port 8767 \
  --token-file memory/local_pyautogui_bridge.token \
  --artifact-dir runs/local_pyautogui_bridge/artifacts \
  --reference-dir memory/local_pyautogui_locators \
  --program-dir memory/local_pyautogui_programs
```

The token file is private, excluded from Git, and reused across ATR server restarts. Start is idempotent: an already healthy owned process is not duplicated. Stop affects only the owned local bridge process.

### Equipment Workspace integration

The workspace adds a `Local Development Bridge` control group with:

- Start;
- Stop;
- Health;
- Select.

The local bridge appears as a distinct saved candidate using alias `local_development`, URL `http://127.0.0.1:8767`, platform `linux`, and scope `localhost`. Selecting it uses the existing connection-memory and Linux-side HTTP client paths. Windows candidates remain selectable and are not fallback targets.

`Open Bridge GUI` opens the selected candidate through the existing authenticated ATR proxy. The local and remote bridges therefore expose the same operator screen and Program Manager behavior.

## Program Portability

Program definitions are portable when they use common actions. Each validation result includes:

- `platform_tested`;
- `portable_actions`;
- `platform_specific_locators`;
- `requires_windows_recalibration`.

Linux development validates logic, sequencing, bounds, timing, keyboard/mouse behavior, screenshots, artifacts, and HTTP integration. Windows deployment must recalibrate target window identity, screen coordinates, image locators, UIA selectors, and export paths before physical UTM execution.

Program Manager stores local development programs under `memory/local_pyautogui_programs`. Exported JSON is the transfer artifact; no Linux absolute path is embedded unless it is explicitly declared platform-specific.

## Safety And Failure Handling

- Bind the local bridge only to `127.0.0.1`.
- Require `X-Bridge-Token` for all authenticated endpoints.
- Keep `pyautogui.FAILSAFE = True` and the existing action allowlist.
- Do not add shell-command or arbitrary executable actions.
- Refuse actual control when `DISPLAY` is absent, the session is not X11, PyAutoGUI cannot connect to the desktop, or the server is not the ATR-owned localhost process.
- A stopped or unhealthy local bridge remains visible as unavailable; it is never replaced by simulator success.
- Local and Windows bridge selections are explicit. Neither is an automatic fallback for the other.
- Supervisor logs go to `runs/local_pyautogui_bridge/` and exclude the token value.

## Data Flow

```text
Equipment Workspace
  -> local bridge supervisor start
  -> token-backed local candidate registration
  -> existing WindowsPyAutoGUIBridge HTTP client
  -> http://127.0.0.1:8767
  -> shared bridge HTTP/API and Program Manager
  -> Linux desktop adapter
  -> actual Ubuntu X11 mouse, keyboard, window, and screenshot operations
  -> structured result, artifacts, request audit, and GUI status
```

Windows deployment uses the same flow after selecting a Windows candidate; only the final desktop adapter and locator calibration differ.

## Verification

### Automated

- Unit-test platform selection, X11 readiness, token-file persistence, process idempotency, stop ownership, candidate registration, and explicit selection.
- Run the existing Windows bridge helper suite unchanged to protect Windows behavior.
- Run browser audits against port `8767` and verify the full Device Bridge GUI and Program Manager.
- Verify the install copy remains byte-identical.

### Actual local desktop

- Start the local bridge from Equipment Workspace.
- Select `Local Development Bridge`.
- Run Health and confirm `platform=linux`, X11 display readiness, PyAutoGUI availability, and localhost scope.
- Run `program1` and observe one bounded mouse movement plus `program1 completed` in the same GUI path.
- Register, validate, execute, export, and delete a custom macro through Program Manager.
- Stop the local bridge and verify Health becomes unavailable without affecting ATR or remote Windows candidates.

## Documentation And Packaging

- Add Linux local-development installation and operation instructions.
- Add PyAutoGUI, python3-xlib, scrot, wmctrl, and xdotool to installation requirements.
- Document the portability boundary and Windows recalibration checklist.
- Keep the Windows package runnable independently after transfer.

## Out Of Scope

- Treating Linux validation as proof that Windows UIA or exact screen coordinates are valid.
- Arbitrary shell execution.
- Wayland desktop automation.
- Automatic fallback between local and remote bridges.
- Changing the existing UTM execution sequence or Guardian gates.
