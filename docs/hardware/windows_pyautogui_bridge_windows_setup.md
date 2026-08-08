# Windows PyAutoGUI Bridge Setup Guide

## Current Standalone Deployment

The canonical deployment is the complete `Pyautogui_server_for_window`
package, not the compatibility copy in `install/`. Install and start it from an
interactive Windows user session:

```text
Double-click INSTALL_WINDOWS_BRIDGE.cmd from any extracted directory.
```

The launcher resolves its own directory, installs the dedicated environment,
creates Desktop and Start Menu shortcuts, and starts the bridge. The equivalent
manual commands are:

```powershell
cd C:\path\to\Pyautogui_server_for_window
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -OpenBrowser -ShowToken
```

The installer creates a package-specific `.venv`. Mutable artifacts, locators,
UTM exports, registered programs, recordings, and the protected token are all
stored under `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`. Use
`-RegisterLogonTask` only when logon startup is wanted. A Windows service is
not supported because PyAutoGUI requires the interactive desktop.

Before deployment approval, run the non-actuating checks and then the explicit
Windows-native acceptance:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native_acceptance.ps1
# Moves the pointer only when explicitly approved:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native_acceptance.ps1 -RunProgram1
```

Linux/X11/Xvfb evidence validates the protocol and demo logic but does not
constitute Windows-native acceptance. The acceptance JSON records the actual
Windows host, desktop readiness, dependency readiness, assets, and optional
bounded Program 1 result.

## Common Equipment Profile Use

The Windows package remains the execution driver for the Lab Equipment
Workspace. In ATR, select the UTM profile (`utm_windows_v1`) from
`/equipment/windows`. The Workspace uses this package for both modes:

- **Test**: invokes the registered UTM protocol with
  `simulate_utm_protocol=true`; it creates simulated screen evidence, request
  log entries, and a parseable CSV without controlling the physical UTM.
- **Live**: invokes the same selected bridge and registered program with
  `simulate_utm_protocol=false`; the UTM application, locators, export path,
  and evidence gates must be ready before execution.

No second mock bridge server is required or supported. Keep this package
running on the Windows PC for physical operation.

## Local Ubuntu Development Target

ATR can run the same bridge server, Web GUI, Program Manager, authenticated API,
allowlist, request audit, and `atr.pyautogui_program.v1` macro schema on the
current Ubuntu workstation. This is an actual X11 desktop-control target, not a
simulator and not an automatic fallback for Windows.

Install once:

```bash
bash install/bootstrap_linux.sh --with-local-pyautogui
```

Then open `/equipment/windows` and use **PyAutoGUI Bridge on This PC**:

1. `Start` launches the ATR-owned process at `127.0.0.1:8767` and registers
   `local_development` as a standby candidate.
2. `Health` must show X11 and PyAutoGUI ready.
3. `Select` explicitly changes the shared bridge candidate. Start never changes
   an existing Windows selection by itself.
4. `Open Windows GUI` opens the same complete console through the selected
   bridge proxy. Program Manager files are stored under
   `memory/local_pyautogui_programs`.
5. `Stop` terminates only the ATR-owned localhost process.

The token is generated once at `memory/local_pyautogui_bridge.token` with mode
`0600`; GUI/API responses expose only whether it is configured. Runtime logs and
artifacts are under `runs/local_pyautogui_bridge`. Keep the mouse away from a
screen corner when intentionally running `program1`, because PyAutoGUI fail-safe
remains enabled. A JSON macro can be transferred to Windows, but window titles,
coordinates, image locators, and file paths must be recalibrated there.

Port `8766` is not used by this bridge because it belongs to the Isaac Sim OMX
mirror receiver.

### Open the Same Console in ATR

After saving and selecting this Windows bridge in ATR, open
`http://localhost:7860/equipment/windows`. The **Windows Bridge Console**
opened from that workspace is the same HTML console this server serves at
`http://<windows-host>:8765/`. ATR proxies the console's API calls to the
selected bridge and injects the saved token on the Linux server. Do not add the
token to browser URLs. A directly opened Windows console keeps a manually
entered token in that browser profile's local storage until Clear Token is
pressed. Use a dedicated trusted Windows browser profile.

## 2026-08-04 Complete Windows Bridge Console

The Windows-local screen exposes the complete bridge backend. The bridge protocol,
allowlisted program definitions, and execution behavior remain unchanged.

The page contains these operator areas:

1. **Connection and Safe Diagnostics**: bridge URL, token, Health, readiness, Safe Preflight, request log, screenshot, and locator state.
2. **Default program controls**: `program1`, UTM simulation/live/abort, payload preview, and generic JSON execution.
3. **Evidence**: result trace, screenshots, artifacts, request audit, proof checklist, and run timeline.
4. **Program Manager**: search, filter, inspect built-ins, and edit, enable, validate, test, or delete registered custom JSON macros.
5. **Browse / Template / Add**: `Browse JSON` loads a definition into the editor only, `Download Template` saves an editable starter file, and `Add to Registry` validates and persists the macro.
6. **Capability Examples**: `EXAMPLES` loads eight read-only examples into the editor and opens a deterministic local Capability Lab. Loading an example never registers or deploys it.

Simplification means grouping and labeling controls. It must not delete a backend-supported function or remove its only operator UI. Program Manager supplements the fixed bridge controls; it does not replace them.

The default registry contains `program1`, `utm_compression_start_v1`, `utm_export_csv_v1`, `utm_manual_save_csv_v1`, and `utm_stop_or_abort_v1`.

### Recording And Skill Management

Program Manager provides `PROGRAMS`, `EXAMPLES`, `RECORD`, and `SKILLS` tabs. Recording is optional
and requires `pynput`; ordinary registered-program execution does not.

```powershell
py -m pip install "pynput>=1.7.7,<2" Pillow opencv-python
$env:WINDOWS_PYAUTOGUI_RECORDING_DIR = "C:\ATR\recordings"
$env:WINDOWS_PYAUTOGUI_ATR_API_URL = "http://<linux-atr-host>:7860"
py windows_pyautogui_bridge_server.py --recording-dir "C:\ATR\recordings"
```

Recording routes are authenticated with the existing bridge token:

- `GET /recordings`, `GET /recordings/status`, `GET /recordings/{recording_id}`
- `POST /recordings/start`, `/recordings/checkpoint`, `/recordings/stop`
- `POST /recordings/{recording_id}/save`

The Record page uses one `RECORD` button for both start and stop. The first
click runs a five-second preparation countdown; clicking again during the
countdown cancels it. After the countdown, the button changes to
`STOP RECORDING` and a small borderless Windows topmost banner shows a red
recording dot and the elapsed `HH:MM:SS` time. Clicking the same button stops
the listeners and removes the banner. Refreshing the page restores the button
from `/recordings/status`. Bridge shutdown also stops an active recording and
removes the native banner. If Tkinter cannot create a desktop window, recording
continues and only the optional indicator is reported unavailable.

The recorder captures sampled pointer motion, click-versus-drag transitions,
two-axis scroll events, key/hotkey events, and explicit screenshot checkpoints.
New recordings are image-first (`atr.equipment_recording.v2`). At pointer press
the bridge keeps local full-frame evidence and embeds bounded 64x64 tight and
192x128 contextual PNG crops in the portable recording. A drag additionally
captures its release target. Full frames are not forwarded inside the Skill.
Consecutive printable keys compile into one bounded `write` action; special
keys and shortcuts remain explicit. Only one recording may be active. Stop and
save are idempotent. The recorder cannot infer whether an arbitrary third-party
field contains a credential, so never record password, token, or secret entry.
`Image tracking` is enabled by default. `Allow coordinate fallback` is disabled
by default and must remain off unless an operator has reviewed the exact target
window and accepts coordinate replay. Missing required locator images block
draft compilation or replay; they never trigger an implicit coordinate click.
The Record tab shows locator readiness and both crop previews before draft
creation. Inline crops are SHA-256 verified, PNG-only, and bounded to 256 KiB
per crop, 32 MiB per recording, and 200 pointer events.
Create Draft forwards the exact saved
recording to Linux; Skill lifecycle actions proxy `/api/equipment/skills/*`.
Test uses the deployed exact version in test mode. Delete requires Disable
first. The Windows browser never receives ATR model credentials.

Custom macros are stored as one validated JSON file per program under
`WINDOWS_PYAUTOGUI_PROGRAM_DIR` (default `C:\ATR\programs`). Built-in programs
are immutable. `Browse JSON` and `Download Template` do not modify this
directory. Only authenticated `POST /programs/register` persists a definition;
`DELETE /programs/{program_id}` removes a custom definition. The validator
accepts only schema `atr.pyautogui_program.v1` and bounded bridge actions, so
the manager cannot register arbitrary shell scripts or executables. Test uses
the existing authenticated `POST /execute` contract.

### Capability Lab And Safe Examples

Open `EXAMPLES -> Open Capability Lab`. The lab supplies deterministic targets
for mouse, drag/scroll, keyboard/shortcut, visual/pixel, window, and manual
dialog examples. The authenticated read-only routes are:

- `GET /capabilities`: supported action families and explicit exclusions.
- `GET /examples`: eight validated example definitions. Five are bounded safe tests; image calibration, export-file waiting, and operator dialogs remain explicit manual examples.
- `GET /examples/<example_id>`: one exact example definition.
- `GET /capability-lab`: local target page; no bridge token is embedded.

`Run Safe Test` is enabled only for examples with `safe_test=true`. Manual
dialogs stay disabled in unattended test mode and require
`confirm_execute=true`. Supported bounded actions include relative/absolute
movement, click variants, mouse down/up, drag, vertical/horizontal scroll,
write/press/hotkey/key down/up, screenshot regions, image/pixel checks, and
window activate/minimize/maximize/restore/move/resize. Any held button or key is
released in a `finally` cleanup on both success and failure. PyAutoGUI fail-safe
must remain enabled.

Together, the eight examples cover every action exposed by the safe-core
capability catalog, including relative movement, triple click, explicit
button/key down-up, relative drag, image matching, stable-file waiting, and
window focus. The image and file examples are templates: configure their
locator/export path before registering and running them.

Excluded by design: shell commands, arbitrary Python, file deletion, password
entry, window close, and process termination.

The Windows console exposes local UTM readiness and evidence operations, while the Linux Lab Equipment Workspace remains authoritative for orchestration and final handoff trust. When opened through ATR, the proxy injects
the saved token. When opened directly on Windows, a manually entered token is
kept in browser `localStorage` until Clear Token is pressed.

Purpose:

- Define how to prepare a Windows PC so the autonomous researcher `equipment_agent` can control GUI software through PyAutoGUI over an internal network.
- This is a Windows-side operator guide. It does not replace the Linux server-side Equipment Agent guideline.

Related project document:

- `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`

External references:

- PyAutoGUI official documentation: <https://pyautogui.readthedocs.io/>
- PyAutoGUI Windows installation: <https://pyautogui.readthedocs.io/en/latest/install.html>
- PyAutoGUI keyboard control: <https://pyautogui.readthedocs.io/en/latest/keyboard.html>
- PyAutoGUI mouse control: <https://autogui.readthedocs.io/en/latest/mouse.html>
- PyAutoGUI screenshot and image-location functions: <https://pyautogui.readthedocs.io/en/latest/screenshot.html>
- PyAutoGUI fail-safe behavior: <https://pyautogui.readthedocs.io/en/latest/index.html>
- Microsoft Windows Firewall risk guidance: <https://support.microsoft.com/en-us/windows/risks-of-allowing-apps-through-windows-firewall-654559af-3f54-3dcf-349f-71ccd90bcc5c>
- Microsoft Windows Firewall rules: <https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules>

============================================================
1. Target Topology
============================================================

Expected network:

```text
Linux autonomous researcher server
  -> internal LAN
  -> Windows PC bridge service
  -> PyAutoGUI
  -> target Windows GUI software
```

The Windows PC must:

- Be on the same trusted internal network as the Linux server.
- Run Python.
- Run the PyAutoGUI bridge service.
- Keep the target GUI application visible and unlocked.
- Accept bridge requests only from trusted hosts.

Linux-side setup GUI:

- Open `/equipment/windows` from Main GUI -> Device Workspaces -> `Open Windows Bridge GUI`.
- Enter the bridge token before scanning.
- Use Scan to discover bridge hosts on the current network; only token-verified hosts are displayed.
- Scan first, then use the alias input on each discovered candidate card to save that candidate with token/settings to `memory/windows_pyautogui_connection.json`.
- Saved candidates appear in the Saved Candidates panel above the selected-bridge test controls.
- Use Select for quick connection and Delete to remove a saved candidate.
- Use Test Health + Programs before running any macro demo.
- Use Run program1 Demo only when the operator is physically ready for the mouse movement.
- Use UTM Profile, Readiness, Live Preflight, and Evidence Audit panels to verify screen evidence, Linux CSV pull, and Vision frame readiness before Analysis handoff.
- In the UTM Profile/Test panel, tune the real UTM export contract: `export_glob`, `artifact_timeout_s`, `stable_for_sec`, optional `expected_export_path`, `target_window` or `regex:<target_window_regex>`, required window focus, manual-save fallback, screen assertions, and bench simulation.

Windows-side local Web GUI:

- Open `http://127.0.0.1:8765/` on the Windows PC running the bridge.
- Use Connection to verify token authentication and PyAutoGUI availability.
- Use Safe Diagnostics and UTM Protocol for readiness, simulation, live execution, recovery, screenshots, locators, and evidence.
- Use Program Manager to inspect built-ins and create, edit, enable, validate, test, or delete custom JSON macros.
- Use Browse JSON to load an edited definition without registering it. Use Add to Registry only after validation.
- Inspect local readiness, run evidence, artifacts, request audit, and timeline directly in the Windows console; use the Linux workspace for orchestration and final handoff trust.

The Windows PC must not:

- Expose the bridge to the public internet.
- Run arbitrary commands sent from the LLM.
- Disable PyAutoGUI fail-safe.
- Store bridge tokens in screenshots, logs, or chat messages.

============================================================
2. Windows Prerequisites
============================================================

Required:

- Windows 10 or Windows 11.
- Python 3.10 or newer recommended.
- A normal desktop session with the target GUI software open.
- Internal network connectivity from the Linux server to the Windows PC.

PyAutoGUI installation status:

- The bridge test server should be able to start even when PyAutoGUI is not installed.
- `/health` must report `pyautogui.available: false` when import fails.
- Real GUI actions, including `program1`, require PyAutoGUI.
- If `program1` is requested before PyAutoGUI is installed, the bridge must return `PYAUTOGUI_NOT_INSTALLED` instead of crashing.

Recommended:

- Static DHCP reservation or fixed internal IP for the Windows PC.
- Private Windows network profile, not public.
- Dedicated Windows user account for automation.
- Target GUI software window layout saved or made reproducible.
- Display sleep disabled while live automation is expected.

Check Python:

```powershell
py --version
```

Install PyAutoGUI:

```powershell
py -m pip install pyautogui
```

Optional for image matching with `confidence`:

```powershell
py -m pip install opencv-python
```

Optional and recommended when the UTM software exposes Windows UI Automation controls:

```powershell
py -m pip install pywinauto
```

With `pywinauto` installed, locators can use UIA selectors such as `locator_backend: uia`, `auto_id`, `title`/`name`, `control_type`, `class_name`, and `best_match`. The bridge evaluates UIA locators before PyAutoGUI image matching and before fixed coordinates.

Optional for OCR/text status checks with `assert_text` and `wait_until_text`:

```powershell
py -m pip install pytesseract Pillow
```

`pytesseract` also requires the Tesseract OCR executable to be installed on Windows and visible on `PATH`. If OCR is not installed, required text checks fail closed instead of being treated as successful.

Verify PyAutoGUI import:

```powershell
py -c "import pyautogui; print(pyautogui.size()); print(pyautogui.FAILSAFE)"
```

Expected:

- It prints screen size, for example `(1920, 1080)`.
- It prints `True` for `FAILSAFE`.

If this command fails with `ModuleNotFoundError`, keep the bridge communication test path available and return `PYAUTOGUI_NOT_INSTALLED` for GUI actions until PyAutoGUI is installed.

============================================================
3. Bridge Service Requirements
============================================================

Core authenticated program endpoints remain:

- `GET /health`
- `GET /programs`
- `POST /programs/validate`
- `POST /programs/register`
- `DELETE /programs/{program_id}`
- `POST /execute`

Custom macro storage can be configured with either:

```powershell
$env:WINDOWS_PYAUTOGUI_PROGRAM_DIR = "C:\ATR\programs"
py windows_pyautogui_bridge_server.py --program-dir "C:\ATR\programs"
```

The environment variable is the service default. The CLI option overrides it
for the current process.

Discovery expectation:

- The Linux setup GUI scans the current IPv4 `/24` network by default.
- If discovery cannot infer the correct network, enter the subnet manually, for example `192.168.0.0/24`.
- Discovery calls `/health` only. It does not execute macros.
- If no token is entered, discovery returns `PYAUTOGUI_TOKEN_REQUIRED`.
- If the token is wrong, the host is not listed.
- If the Windows bridge accepts no-token traffic, the host is not listed because it is not a valid secure bridge.

Required request authentication:

- Header: `X-Bridge-Token`
- Token value: long random secret generated by the operator.

Required bridge behavior:

- Reject requests without a valid token.
- Reject unknown actions before calling PyAutoGUI.
- Reject unknown macro program IDs before calling PyAutoGUI.
- Validate screen coordinates against `pyautogui.size()`.
- Keep `pyautogui.FAILSAFE = True`.
- Keep a small pause, for example `pyautogui.PAUSE = 0.1`.
- Return structured JSON with `ok`, `status`, `failure_code`, and `step_trace`.
- Log accepted action names and timestamps.
- Append request audit entries to `bridge_requests.jsonl` without storing token values. Required fields: timestamp, client, method, path, token header presence, auth result.
- Expose `GET /request-log` and a Windows-side Web GUI `Request Log` control so operators can inspect recent audit entries without opening the filesystem manually.
- Show artifact root, request log path, locator root, and UTM export root in the Windows-side Web GUI.
- Never accept raw Python, shell, PowerShell, or eval strings.
- Lazy-import PyAutoGUI so `/health` can still answer when PyAutoGUI is missing.

Minimum `/health` response:

```json
{
  "ok": true,
  "status": "ready",
  "bridge": "windows_pyautogui",
  "screen": {"width": 1920, "height": 1080},
  "pyautogui": {"available": true, "failsafe": true, "pause": 0.1}
}
```

Missing PyAutoGUI `/health` response:

```json
{
  "ok": true,
  "status": "degraded",
  "bridge": "windows_pyautogui",
  "screen": null,
  "pyautogui": {"available": false, "error": "ModuleNotFoundError"},
  "message": "Install PyAutoGUI with: py -m pip install pyautogui"
}
```

Minimum `/execute` request:

```json
{
  "sequence_id": "manual-check-001",
  "sequence": [
    {"action": "health"},
    {"action": "screenshot"}
  ]
}
```

Minimum `/programs` response:

```json
{
  "ok": true,
  "status": "ready",
  "bridge": "windows_pyautogui",
  "programs": [
    {
      "program_id": "program1",
      "description": "Demo macro: verify PyAutoGUI, move mouse briefly, and return completion log.",
      "requires_pyautogui": true,
      "safe_test": true
    }
  ]
}
```

Minimum `/execute` response:

```json
{
  "ok": true,
  "status": "completed",
  "bridge": "windows_pyautogui",
  "sequence_id": "manual-check-001",
  "step_trace": [
    {"step": "HEALTH", "status": "ok"},
    {"step": "SCREENSHOT", "status": "ok"},
    {"step": "DONE", "status": "ok"}
  ],
  "failure_code": null
}
```

============================================================
4. Allowed Phase 1 Actions
============================================================

Allowed:

- `health`
- `screenshot`
- `locate_image`
- `assert_text`
- `wait_until_text`
- `wait`
- `move_to`
- `click`
- `double_click`
- `press`
- `hotkey`
- `write`
- `scroll`
- `run_registered_program`
- `demo_mouse_wiggle`
- `log`

Blocked:

- `exec`
- `eval`
- `shell`
- `powershell`
- `cmd`
- arbitrary file deletion
- arbitrary process launch
- disabling fail-safe
- unbounded loops
- clicks outside the visible screen
- unknown macro program IDs

Recommended limits:

```json
{
  "max_steps": 50,
  "max_wait_sec": 30,
  "max_write_chars": 512,
  "allowed_buttons": ["left", "right", "middle"],
  "allowed_hotkeys": [
    ["ctrl", "s"],
    ["ctrl", "o"],
    ["enter"],
    ["esc"]
  ]
}
```

============================================================
4.1 Registered Macro Programs
============================================================

Use named macro programs when the operator wants to switch between several repeatable automation routines.

The LLM/tool-calling layer should choose which macro to run from the current state and user command. The Windows bridge should only expose and execute registered macro IDs.

Recommended tool-call flow for `program1 실행`:

1. `GET /health`
2. `GET /programs`
3. `POST /execute` with `program_id: "program1"`

Recommended command model:

```json
{
  "program_id": "program1",
  "command": "program1 실행"
}
```

Do not let the Linux server or LLM send raw Python code. It should send only a `program_id`; the Windows bridge maps that ID to a local registered macro.

Minimum Phase 1 registry:

```json
{
  "programs": {
    "program1": {
      "description": "Demo macro: verify PyAutoGUI, move mouse briefly, and return completion log.",
      "requires_pyautogui": true,
      "sequence": [
        {"action": "health"},
        {"action": "demo_mouse_wiggle", "duration_sec": 1.0, "distance_px": 20},
        {"action": "log", "message": "program1 completed"}
      ]
    }
  }
}
```

`program1` behavior:

- It is a connectivity and GUI-control demo, not a real experiment macro.
- It checks bridge communication and token auth first.
- It lazy-imports PyAutoGUI.
- If PyAutoGUI is missing, it returns `PYAUTOGUI_NOT_INSTALLED`.
- If PyAutoGUI is installed, it records the current mouse position, moves the mouse a short bounded distance, moves it back near the original position, and returns `program_log: "program1 completed"`.
- It must not click, type, open programs, or change files.

Why this is the recommended test:

- Network/token routing can be tested before PyAutoGUI is installed.
- Missing dependency is reported clearly.
- The visible mouse movement proves real GUI control after installation.
- It is safer than click/type tests because it does not interact with the target application.

============================================================
5. Token Setup
============================================================

Generate a token in PowerShell:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

Set it for the current PowerShell session:

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<generated-token>"
```

Set the listening host and port for the current session:

```powershell
$env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
```

Use `0.0.0.0` only when Windows Firewall restricts access to the trusted internal network.

============================================================
6. Firewall Setup
============================================================

Preferred firewall policy:

- Allow the Python bridge application only on the private network profile.
- Restrict inbound traffic to the Linux server IP if possible.
- Do not open the port on public networks.

Example PowerShell inbound rule:

```powershell
New-NetFirewallRule `
  -DisplayName "Autonomous Researcher PyAutoGUI Bridge" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8765 `
  -Profile Private
```

More restrictive example with Linux server IP:

```powershell
New-NetFirewallRule `
  -DisplayName "Autonomous Researcher PyAutoGUI Bridge From Linux Server" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8765 `
  -RemoteAddress "<linux-server-private-ip>" `
  -Profile Private
```

Remove the rule if the bridge is retired:

```powershell
Remove-NetFirewallRule -DisplayName "Autonomous Researcher PyAutoGUI Bridge"
```

============================================================
7. Starting The Bridge
============================================================

The canonical package location in this project is:

```text
Pyautogui_server_for_window/
```

Expected start command on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_bridge.ps1 -ShowToken
```

The bridge should print:

```text
Windows PyAutoGUI bridge listening on 0.0.0.0:8765
Token authentication: enabled
PyAutoGUI available: true|false
PyAutoGUI FAILSAFE: True when available
```

Keep this terminal open during live operation, or install the optional
interactive-logon Scheduled Task. Do not run the bridge as a Windows service.

============================================================
8. Linux Server Configuration
============================================================

On the Linux autonomous researcher server, set:

```bash
export WINDOWS_PYAUTOGUI_BRIDGE_URL="http://<windows-private-ip>:8765"
export WINDOWS_PYAUTOGUI_BRIDGE_TOKEN="<same-token>"
```

Alternatively, use the `/equipment/windows` setup GUI. The selected bridge is stored in:

```text
memory/windows_pyautogui_connection.json
```

Saved profile shape:

```json
{
  "selected_candidate": "windows_pyautogui_pc_1",
  "candidates": {
    "windows_pyautogui_pc_1": {
      "candidate_alias": "windows_pyautogui_pc_1",
      "bridge_url": "http://172.30.1.83:8765",
      "host": "172.30.1.83",
      "port": 8765,
      "token": "<stored-token>",
      "token_header": "X-Bridge-Token",
      "allow_live_execute": true
    }
  }
}
```

Keep this file local and protected. The Linux runtime writes it with restricted file permissions when possible.

Project config should later use:

```yaml
devices:
  equipment:
    mode: live
    provider: windows_pyautogui
    windows_pyautogui:
      enabled: true
      bridge_url_env: WINDOWS_PYAUTOGUI_BRIDGE_URL
      token_env: WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
      token_header: X-Bridge-Token
      allow_live_execute: true
```

For normal development and CI:

```yaml
devices:
  equipment:
    mode: simulator
```

============================================================
9. Manual Validation From Linux
============================================================

Health check:

```bash
curl -s \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/health"
```

Expected:

```json
{"ok": true, "status": "ready"}
```

If PyAutoGUI is not installed yet, communication can still be valid:

```json
{
  "ok": true,
  "status": "degraded",
  "pyautogui": {"available": false},
  "message": "Install PyAutoGUI with: py -m pip install pyautogui"
}
```

List registered macro programs:

```bash
curl -s \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/programs"
```

Expected:

```json
{"ok": true, "programs": [{"program_id": "program1"}]}
```

Execute a no-op style sequence:

```bash
curl -s \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"sequence_id":"manual-check-001","sequence":[{"action":"health"},{"action":"screenshot"}]}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/execute"
```

Execute registered demo macro:

```bash
curl -s \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Bridge-Token: $WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" \
  -d '{"sequence_id":"program1-check-001","program_id":"program1","command":"program1 실행"}' \
  "$WINDOWS_PYAUTOGUI_BRIDGE_URL/execute"
```

Expected when PyAutoGUI is not installed:

```json
{
  "ok": false,
  "status": "blocked",
  "program_id": "program1",
  "failure_code": "PYAUTOGUI_NOT_INSTALLED"
}
```

Expected after PyAutoGUI is installed:

```json
{
  "ok": true,
  "status": "completed",
  "program_id": "program1",
  "program_log": "program1 completed"
}
```

Do not test clicking or typing until:

- The correct target application is visible.
- Screen coordinates are verified.
- The mouse fail-safe corner is reachable.
- The operator is physically near the Windows PC.

============================================================
10. Operating Procedure
============================================================

Before live workflow:

1. Log into the Windows PC.
2. Open the target GUI application.
3. Put the target window in the expected position.
4. Start the PyAutoGUI bridge terminal.
5. Confirm `FAILSAFE: True`.
6. Run `/health` from Linux.
7. Open `/equipment/windows` or use Main GUI -> Device Workspaces -> `Open Windows Bridge GUI`.
8. Scan, select, and save the Windows bridge candidate.
9. Run Health + Programs test.
10. Run `program1` demo only if the operator accepts the mouse movement.
11. Start the autonomous researcher Live workflow.

During live workflow:

- Keep the Windows display awake.
- Do not move the mouse unless aborting.
- Watch the bridge terminal logs.
- Move the mouse to a screen corner to trigger PyAutoGUI fail-safe if automation goes out of control.

After live workflow:

- Stop the bridge terminal with `Ctrl+C`.
- Close the target GUI application if needed.
- Archive bridge logs and screenshots if they are part of the experiment record.

============================================================
11. Failure Codes
============================================================

Recommended failure codes:

- `PYAUTOGUI_BRIDGE_UNREACHABLE`
- `PYAUTOGUI_AUTH_FAILED`
- `PYAUTOGUI_NOT_INSTALLED`
- `PYAUTOGUI_PROGRAM_NOT_FOUND`
- `PYAUTOGUI_ACTION_NOT_ALLOWED`
- `PYAUTOGUI_COORDINATE_OUT_OF_BOUNDS`
- `PYAUTOGUI_FAILSAFE_TRIGGERED`
- `PYAUTOGUI_SCREENSHOT_FAILED`
- `PYAUTOGUI_IMAGE_NOT_FOUND`
- `PYAUTOGUI_TIMEOUT`
- `PYAUTOGUI_INTERNAL_ERROR`
- `UTM_SAVE_DIALOG_TIMEOUT`

Failure handling:

- If auth fails, stop and rotate token.
- If bridge is unreachable, check Windows IP, firewall, and bridge process.
- If PyAutoGUI is not installed, run `py -m pip install pyautogui` on Windows and retry `program1`.
- If a macro program is not found, check `/programs` and the Windows-side macro registry.
- If coordinate validation fails, re-capture screenshot and update target coordinates.
- If fail-safe triggers, treat it as operator abort and do not auto-retry.
- If image is not found, do not blindly click fallback coordinates unless that fallback is explicitly configured.

============================================================
12. Security Checklist
============================================================

Required before real operation:

- Bridge token is set and non-empty.
- Firewall rule is private-profile only.
- Bridge is reachable only from trusted LAN or trusted Linux server IP.
- No public port forwarding exists.
- No arbitrary command endpoint exists.
- PyAutoGUI fail-safe is enabled.
- Target app does not display secrets in screenshots unless screenshots are protected.
- Bridge logs do not contain token values.

Recommended:

- Rotate token after major testing sessions.
- Use a dedicated Windows account.
- Keep the bridge source file read-only for normal operators.
- Disable the firewall rule when not using the bridge for long periods.

============================================================
13. Current Implementation Status
============================================================

As of this document:

- The Linux-side bridge client exists in `device_bridges/windows_pyautogui_bridge.py`.
- MCP tool registration exists through `mcp_tools/equipment_tools.py`.
- The standalone Windows package exists in `Pyautogui_server_for_window/`.
- `install/windows_pyautogui_bridge_server.py` is a byte-identical compatibility copy for repository tests, not a standalone deployment artifact.
- `/health`, `/programs`, `/execute`, `/artifacts`, and `/artifacts/{artifact_id}` are supported by the helper.
- `program1` remains only a connectivity demo and must not be treated as UTM completion.
- `utm_compression_start_v1` is the registered UTM protocol used by Equipment Agent for Analysis handoff.
- Live UTM success now requires an exported CSV artifact unless `WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM=1` or `simulate_utm_protocol=true` is explicitly set for bench/demo testing.

Next implementation phase:

1. Add real UTM software locator templates or UIA selectors.
2. Add protocol-specific Save/Export macro steps for the installed UTM software.
3. Tune `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR` and file naming with the real UTM export path.
4. Connect Vision Agent responses to `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete`.
5. Add screenshots/OCR artifacts for before/running/complete state assertions.

============================================================
8. UTM Protocol And Artifact Endpoints
============================================================

The bundled Windows bridge helper now exposes UTM-oriented registered programs in addition to `program1`:

- `utm_compression_start_v1`: focus/assert/start/complete/export UTM compression protocol.
- `utm_export_csv_v1`: export CSV after completion.
- `utm_manual_save_csv_v1`: manual Save As fallback.
- `utm_stop_or_abort_v1`: stop/abort recovery macro.

The bridge also exposes artifact endpoints for Linux-side pull:

```text
GET /artifacts
GET /artifacts/{artifact_id}
```

`POST /execute` for `utm_compression_start_v1` returns `output_artifacts[]`. The Linux client calls `/artifacts/{artifact_id}`, writes the payload under `artifacts/equipment/<run_id>/utm/`, and passes that local CSV path to Analysis Agent through `equipment_result.result_file` and `equipment_result.utm_csv_path`.

For real UTM software integration, the helper does not create a synthetic CSV by default. It watches the configured export path and returns success only after the file is stable and parseable.

Live UTM export settings:

- `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR`: default `C:\ATR\utm_exports`.
- `WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB`: default `*.csv`.
- `WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC`: default `2.0`.
- `WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM`: default `0`; set to `1` only for bench/demo testing.
- `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS`: default `0`; set to `1` when UIA/image locator checks are configured and must be enforced.

The returned artifact response fields must stay stable: `artifact_id`, `kind=utm_csv`, `filename`, `size_bytes`, `sha256`, `row_count_probe`, and `columns_probe`. Required CSV columns are `time_s`, `displacement_mm`, and `force_N`.

For live UTM protocol runs, the helper also attempts to save `screen_png` artifacts for `before_start` and `after_complete`. These are evidence artifacts only; `ready_for_analysis` still depends on the UTM CSV parse probe.

Screen/action sequence behavior:

- `utm_compression_start_v1` carries a default protocol sequence: health, focus, ready assertion, start click, running wait, complete wait, export wait.
- The helper accepts payload `sequence[]` to override or specialize that protocol.
- `assert_visible`, `wait_until`, and `click` use payload `locators` or per-action UIA selector / `image_path` / `target_image` / `x` / `y`.
- Locator priority is UIA/pywinauto first when selector fields are present, then PyAutoGUI image matching, optional OCR/text assertion through `assert_text`/`wait_until_text`, then explicit coordinates only when configured.
- If `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS=1` or `require_screen_assertions=true`, missing locator/image match blocks instead of faking success. Pre-start locator misses use `UI_LOCATOR_NOT_FOUND`; a clicked start button followed by missing `running_state` uses `CLICK_NO_STATE_CHANGE` and also reports `timeout_failure_code=UTM_RUNNING_STATE_TIMEOUT`; missing completion state uses `UTM_TEST_COMPLETE_TIMEOUT`.
- Configured popup/error locators such as `error_popup`, `error_dialog`, `warning_dialog`, `communication_error`, or `save_error` are watched before actions, during `wait_until`, and immediately after clicks. If found, the protocol blocks with `UTM_ERROR_POPUP_DETECTED`.
- If screen assertions are not required, missing locators are recorded as warnings, not as proof of screen success. The CSV artifact gate still decides whether Analysis can run.
- The Linux runtime may call `vision.equipment_cross_check` before `/execute`; the Windows helper is still only responsible for GUI control and artifact serving, not physical scene judgment.
- Linux-side `device_bridges/windows_pyautogui_bridge.py` merges each registered program profile into `/execute` payloads. `sequence`, `locators`, `export_glob`, `artifact_timeout_s`, `stable_for_sec`, and `require_screen_assertions` can be defined in `configs/devices.yaml` under `devices.equipment.windows_pyautogui.registered_programs.<program_id>`.
- `/equipment/windows` exposes UTM Protocol Test controls for export glob, timeout, stable-file seconds, expected export path, target window/title regex, window-focus enforcement, manual-save fallback, screen-assertion enforcement, bench simulation, and locator JSON override. These controls are for setup/calibration before using the same program in the autonomous loop.

============================================================
9. UTM Locator Calibration Endpoints
============================================================

The Windows helper now exposes calibration endpoints in addition to `/execute` and artifact pull:

```text
POST /screenshot
GET  /locators
POST /locators/capture
```

Use these endpoints from `/equipment/windows` before enforcing `require_screen_assertions=true`:

1. Select the saved Windows bridge candidate.
2. Open the UTM software on the Windows PC and put it in the expected state.
3. Click `Capture Screen` to record the current full screen as evidence.
4. Enter a locator name such as `ready_state`, `start_button`, `running_state`, or `complete_state`.
5. Enter `x`, `y`, `width`, and `height` for the visible UI region.
6. Click `Capture Locator`.
7. The returned locator is merged into the GUI `Locator JSON override` field.
8. Run `Check Readiness`; it must show all required locators complete before live UTM execution.
9. Run `UTM Protocol Test` with `Require screen assertions` enabled only after the captured locator images/selectors are correct.

Captured locator files are stored on the Windows bridge host under:

```text
%WINDOWS_PYAUTOGUI_LOCATOR_ROOT%\<program_id>\<locator_name>.png
```

Default root:

```text
C:\ATR\equipment_locators
```

The Linux client pulls screenshot/locator artifacts through `/artifacts/{artifact_id}` and stores them under `artifacts/equipment/<run_id>/screenshots/` or `artifacts/equipment/<run_id>/locators/` for operator review. These artifacts are calibration/evidence artifacts. They do not replace the required UTM CSV artifact gate for Analysis handoff.

Security rule: screenshot and locator capture require explicit GUI confirmation on the Linux side. They must not be triggered automatically by an LLM without a human setup/calibration action.

============================================================
10. Persistent UTM Profile for Autonomous Runs
============================================================

After locator capture and export-path tuning, save the settings from the Linux `/equipment/windows` page with `Save UTM Profile`.

The saved profile path is:

```text
memory/equipment_utm_profile.json
```

The profile can contain:

```json
{
  "program_id": "utm_compression_start_v1",
  "export_glob": "*.csv",
  "artifact_timeout_s": 60.0,
  "stable_for_sec": 2.0,
  "expected_export_path": "C:/ATR/utm_exports/<run_id>/<specimen_id>.csv",
  "target_window": "UTM Controller",
  "target_window_regex": "",
  "require_window_focus": true,
  "manual_save_required_if_no_artifact": true,
  "require_screen_assertions": true,
  "simulate_utm_protocol": false,
  "locators": {
    "ready_state": {"locator_backend": "uia", "auto_id": "readyStatus", "control_type": "Text"},
    "start_button": {"image_path": "C:/ATR/equipment_locators/utm_compression_start_v1/start_button.png", "confidence": 0.8}
  }
}
```

The Linux bridge client merges this profile into the registered UTM program before `/execute` is called. This means the same saved calibration is used by:

- UTM Protocol Test in `/equipment/windows`.
- MCP/tool calls through `equipment.pyautogui.run`.
- The autonomous Lab Equipment Agent stage in the closed-loop workflow.

If the UTM screen changes, recapture the affected locator, save the profile again, and rerun the protocol test before enabling a live experiment run.

============================================================
11. Non-Actuating Live Preflight
============================================================

Before running the real UTM protocol, use the Linux `/equipment/windows` page and click `Live Preflight`.

The preflight is intentionally safe:

```text
POST /api/equipment/windows/live-preflight
```

It requires `confirm_preflight=true` and calls only read/calibration endpoints on the Windows bridge:

```text
GET  /health
GET  /programs
GET  /locators
POST /screenshot   # only when Capture screen is checked
```

It never calls `/execute`, so it must not start the UTM program, move the mouse through the UTM start action, or generate a fake UTM result.

The response is `equipment.pyautogui.live_preflight` and contains:

- `non_actuating=true`
- `touched_endpoints` so the operator can confirm `/execute` was not used
- passive setup gates from `/api/equipment/windows/readiness`
- live `/health` and PyAutoGUI availability
- live `/programs` registry check for `utm_compression_start_v1`
- live locator-library status
- optional screenshot evidence path
- blockers/warnings and next actions

Use this sequence before a physical UTM run:

1. Scan/select the Windows bridge candidate.
2. Capture or enter required UTM locators.
3. Save the UTM profile.
4. Run `Check Readiness`.
5. Run `Live Preflight`.
6. Only then run `UTM Protocol Test` or allow the autonomous Lab Equipment Agent stage to call the real protocol.

Manual save/export fallback behavior:

- `utm_compression_start_v1` first watches `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR` for a stable parseable CSV.
- If no CSV appears, the helper runs `utm_manual_save_csv_v1` automatically by default.
- The fallback writes to `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR\<run_id>\<specimen_id>.csv`, then runs the same stable-file and parse-probe checks.
- Set request payload `manual_save_required_if_no_artifact=false` only when the installed UTM software should never receive an automated Save As fallback.
- Success via fallback is visible as `data_acquisition.save_method=manual_save_dialog`; failure remains blocked with the original export/parse failure code.

============================================================
12. Linux Pull Ledger After Windows Export
============================================================

When a UTM run succeeds on the Windows bridge, the response must expose a pullable `utm_csv` artifact. The Linux bridge then calls:

```text
GET /artifacts/<artifact_id>
```

The Linux side stores the CSV under `artifacts/equipment/<run_id>/utm/` and updates the handoff ledger:

```json
{
  "result_file": "artifacts/equipment/<run_id>/utm/<file>.csv",
  "utm_csv_path": "artifacts/equipment/<run_id>/utm/<file>.csv",
  "data_acquisition": {
    "status": "pulled_to_linux",
    "windows_path": "C:/ATR/utm_exports/<run_id>/<file>.csv",
    "linux_path": "artifacts/equipment/<run_id>/utm/<file>.csv",
    "local_path": "artifacts/equipment/<run_id>/utm/<file>.csv",
    "sha256": "...",
    "row_count_probe": 80,
    "columns_probe": ["time_s", "displacement_mm", "force_N"]
  }
}
```

Windows paths are evidence/provenance only. `AnalysisAgent` requires the Linux-local file path and parse-probe metadata before processing UTM data. If the file cannot be pulled or parsed, the workflow must remain blocked instead of fabricating live data.

============================================================
13. Required Screen Assertions
============================================================

When `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS=1` or a request sets `require_screen_assertions=true`, the Windows bridge must execute the registered protocol's locator assertions directly. It should not require a caller-provided `screen_assertions_verified` flag.

Expected behavior:

1. capture the pre-start screen artifact when screenshots are available;
2. run `assert_visible` for `ready_state`;
3. locate and click `start_button`;
4. run `wait_until` for `running_state` and `complete_state`;
5. block with `UI_LOCATOR_NOT_FOUND` if any required locator cannot be found;
6. continue to export watching/manual save only after the screen-control sequence passes.

This keeps the proof of GUI state transition inside the Windows bridge executor, where the actual screen is visible.

============================================================
14. Screen-State Evidence Artifacts
============================================================

For `utm_compression_start_v1`, the bridge records screen evidence at state transition checkpoints:

- `before_start`: captured before running the registered sequence;
- `after_start`: captured when `wait_until running_state` succeeds;
- `after_complete`: captured when `wait_until complete_state` succeeds, or as a fallback after export success if no complete-state screenshot was captured earlier.

The response `screen_checks` must include the artifact IDs:

```json
[
  {"checkpoint": "before_start", "state": "ready", "screenshot_artifact": "screen_before_start_..."},
  {"checkpoint": "after_start", "state": "running", "screenshot_artifact": "screen_after_start_..."},
  {"checkpoint": "after_complete", "state": "complete", "screenshot_artifact": "screen_after_complete_..."}
]
```

These artifacts are separate from the UTM CSV artifact. They prove GUI state observation, while the CSV artifact proves data acquisition.

============================================================
15. Failure Evidence Retention
============================================================

A blocked UTM response should still be useful for debugging and Guardian/Knowledge memory. The Windows bridge therefore returns screen evidence on failure paths:

- sequence failure: keep `before_start`, capture `failure`, return `output_artifacts` and `screen_checks`;
- export/save failure: keep any observed `after_start` / `after_complete` artifacts, capture `failure`, return `output_artifacts` and `screen_checks`;
- no synthetic CSV is generated in live mode just to make the failure look successful.

The Linux side should treat these artifacts as failure evidence, not as Analysis input. Only a pulled parseable `utm_csv` artifact can satisfy the data handoff gate.

============================================================
16. Target Window Focus and Windows Operator GUI
============================================================

The packaged Windows bridge GUI at `http://127.0.0.1:8765/` is now the preferred local setup panel for the Windows UTM workstation. It provides token health, program registry inspection, screenshot capture, locator capture, UTM simulation, guarded live UTM execution, result JSON, step trace, and artifact ledger in one page.

Use it for Windows-side setup only. The autonomous Linux workflow still requires the saved bridge candidate, saved UTM profile, Vision physical cross-checks, pulled CSV, parse probe, Guardian failure reporting, and Analysis handoff.

`focus_window` now activates the real UTM application window before image assertions/clicks when a selector is configured. The payload or registered program may provide `target_window`, `target_window_regex`, `window_title`, `title`, or `target_app`. Placeholder values such as `main` and `main_window_title_or_regex` are ignored as real titles.

Recommended live payload fields:

```json
{
  "program_id": "utm_compression_start_v1",
  "target_window": "<real UTM software title substring>",
  "require_window_focus": true,
  "require_screen_assertions": true,
  "manual_save_required_if_no_artifact": true
}
```

If the target window cannot be activated and focus is required, the Windows bridge must block with `PYAUTOGUI_WINDOW_NOT_FOUND`. This prevents a live UTM macro from clicking a wrong active window.

============================================================
17. Live Evidence Audit Handoff Gate
============================================================

A Windows-side UTM CSV export is not enough to enter Analysis. The Linux Lab Equipment Agent now treats the following as separate live gates for `windows_pyautogui` UTM runs:

```text
screen_evidence_complete  -> before_start, after_start, after_complete screenshots observed
linux_artifact_pulled     -> CSV pulled from Windows artifact endpoint to a Linux-local path
vision_evidence_complete  -> required Vision checks passed with frame evidence IDs
```

A valid live Windows UTM handoff should therefore show:

```json
{
  "data_acquisition": {
    "status": "pulled_to_linux",
    "linux_path": "artifacts/equipment/<run_id>/utm/<file>.csv"
  },
  "cross_checks": {
    "screen_evidence_complete": true,
    "linux_artifact_pulled": true,
    "vision_evidence_complete": true
  },
  "live_evidence_audit": {
    "required_for_handoff": true,
    "screen_evidence": {"ok": true, "missing_checkpoints": []},
    "linux_artifact_pull": {"ok": true},
    "vision_evidence": {"ok": true}
  }
}
```

If the Windows server reports only `exported_on_windows`, the run remains blocked with `UTM_LINUX_ARTIFACT_PULL_REQUIRED`. This prevents Analysis from consuming a path that only exists on the Windows workstation.

============================================================
18. Windows Equipment Post-Run Evidence Audit
============================================================

The Linux `/equipment/windows` page now exposes `Audit Last Run Evidence`. This is a passive check of the current runtime metadata and does not call the Windows bridge.

Endpoint:

```text
GET /api/equipment/windows/evidence-audit
```

Use it after a Lab Equipment stage or UTM protocol test. It answers whether the last run has enough evidence to enter Analysis:

- complete screen evidence refs;
- Linux-local CSV pull;
- Vision frame evidence;
- parse-probe success;
- no blocking reasons from `equipment_report.decision`.

The same payload is included in `/api/equipment/windows/config` as `utm_evidence_audit` so the GUI reflects the latest post-run state when reopened.

============================================================
19. Setup-GUI UTM Protocol Test vs Full Agent Handoff
============================================================

When an operator clicks `Run UTM Protocol Test` on `/equipment/windows`, the endpoint stores the raw Windows run result as runtime metadata. `Audit Last Run Evidence` can inspect this raw result immediately.

Important distinction:

- setup-GUI UTM protocol test can verify Windows screen evidence and Linux CSV pull;
- it does not replace the full Lab Equipment Agent stage;
- it does not provide Vision frame evidence by itself;
- therefore the post-run audit remains blocked for Analysis with `UTM_VISION_EVIDENCE_FRAMES_REQUIRED` until the autonomous Equipment Agent packages Vision cross-check evidence into `equipment_report.v1`.

This prevents a setup/calibration test from being mistaken for a complete physical autonomous experiment.

## 2026-05-30 Windows GUI UTM Export Controls

The Windows-side bridge GUI now exposes the same data-acquisition controls that the UTM registered protocol consumes:

- `Export Glob`: sent as `export_glob`; used when searching `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR` for the UTM CSV.
- `Artifact Timeout Sec`: sent as `artifact_timeout_s`; maximum wait budget for the exported CSV to appear and become stable.
- `Stable File Sec`: sent as `stable_for_sec`; the file size must remain stable for this duration before the bridge treats it as complete.
- `Expected Export Path`: sent as `expected_export_path`; optional exact file path when the operator already knows where the UTM software will save the CSV.

These controls are available in both the install helper server and the packaged `Pyautogui_server_for_window` server. `Fill UTM JSON`, `Run UTM Simulation`, and `Run Live UTM` all include these fields in the `/execute` payload. This keeps operator GUI behavior aligned with the Linux Lab Equipment Agent data-recovery gate: Windows export is not enough; the Linux side must still pull the artifact and parse-probe it before Analysis handoff.

Required readiness locator gate:

- Default required locator names: `ready_state`, `start_button`, `running_state`, `complete_state`.
- If the saved UTM profile overrides `sequence`, required names are inferred from `assert_visible`, `click`, and `wait_until` action targets.
- `/api/equipment/windows/readiness` blocks with `UTM_REQUIRED_LOCATORS_MISSING` when screen assertions are required but one or more required locators are missing.
- `/equipment/windows` shows `missing_required_locators` so the operator can capture the exact missing locator before live preflight or UTM protocol execution.

## 2026-05-30 Windows-Side Readiness Button

The packaged Windows bridge GUI and the install helper GUI now include a `Readiness` button.

Behavior:

- Calls `GET /readiness` with the same token authentication as `/health`, `/programs`, and `/execute`.
- Does not execute any UTM macro and does not move the machine.
- Reads the registered `utm_compression_start_v1` protocol and derives required locator names from `assert_visible`, `click`, and `wait_until` steps.
- Defaults to `ready_state`, `start_button`, `running_state`, and `complete_state` when no sequence-derived names are available.
- Reports `configured_locator_names`, `missing_required_locators`, and `required_locators_complete`.
- Blocks with `UTM_REQUIRED_LOCATORS_MISSING` when the Windows locator library is incomplete.

Operator use:

1. Open the UTM software on the Windows PC.
2. Capture `ready_state`, `start_button`, `running_state`, and `complete_state` locators under the same program ID.
3. Click `Readiness`.
4. Proceed to Linux live preflight only when the Windows GUI shows no missing required locators.

## 2026-05-30 Request Audit Gate for Live Handoff

The Linux Lab Equipment Agent now requires request-audit evidence before a live Windows UTM run can hand off to Analysis.

Required live evidence:

- `bridge_requests.jsonl` path is known.
- `/request-log` returns one or more events, or the run result carries `request_log_event_count`.
- Recent request paths include `/execute` when recent paths are available.
- The `/execute` identity matches the expected `run_id`, `sequence_id`, `specimen_id`, and `program_id`.

Blocking codes:

- `UTM_REQUEST_LOG_REQUIRED`: no usable request log path/event evidence.
- `UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED`: request log exists but does not show the live `/execute` call.
- `UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED`: `/execute` is present but the run/sequence/specimen/program identity does not match the Linux request.

This gate is independent from screen evidence, Vision evidence, and CSV parse evidence. All gates must pass for `equipment_handoff.status=ready_for_analysis`.

Linux Equipment GUI alignment:

- `/api/equipment/windows/evidence-audit` uses this same strict rule; the GUI Evidence Audit card reports `request_log=execute-ok` only when `/execute` is visible in recent request paths.
- A request-log file path plus event count is still blocked if the recent path list does not prove the live `/execute` command.
- This keeps the Windows setup helper, Linux Equipment workspace, and Lab Equipment Agent handoff gate consistent.

## 2026-05-30 Windows GUI Request Audit Card

The Windows-side bridge GUI now includes a `Request Audit` card in addition to the raw JSON result panel. The card summarizes:

- total request-log events,
- whether a live `/execute` request has been seen,
- recent request paths,
- the current handoff gate message.

`GET /request-log` now returns `recent_paths`, `execute_event_seen`, `execute_event_count`, and `last_execute_at`. Token values remain excluded from the log. For a live UTM run, `execute_event_seen=true` is required before the Linux Equipment workspace and Lab Equipment Agent can treat the request-audit gate as satisfied.

Request-log summary compatibility:

- Linux no longer requires the full `events[]` array to prove request-audit readiness. The Windows bridge may return summary-only fields when log size or privacy policy requires it.
- Required summary fields are `event_count`, `recent_paths`, `execute_event_seen`, `execute_event_count`, and `last_execute_at`.
- `execute_event_seen=true` is accepted only as proof that `/execute` appeared in the Windows request audit path; all other live gates still apply.

============================================================
Windows-Side GUI Update: Live Proof Checklist
============================================================

The Windows bridge local Web GUI now includes a `Live Proof Checklist` card.

Purpose:

- Show the operator whether the Windows-side evidence is sufficient for a live UTM handoff.
- Keep the Windows PC operator view aligned with the Linux Equipment Agent request-audit gate.
- Avoid treating a visible bridge page or a health check as proof that a live `/execute` command actually reached the Windows bridge.

Checklist items:

- `Health + PyAutoGUI`: requires `/health` to show PyAutoGUI as available.
- `UTM Locators`: requires `/readiness` to report all required UTM locators captured.
- `Live Safety Confirmed`: requires the local operator safety checkbox before `Run Live UTM`.
- `Request Log /execute`: requires `/request-log` to show an actual `/execute` event.
- `Screen Evidence`: expects before-start, after-start, and after-complete UTM screenshots from the live run.
- `CSV + Parse Probe`: expects a verified UTM CSV/data artifact with a parse probe.

GUI controls:

- `Refresh Evidence` calls `/health`, `/readiness`, and `/request-log` in sequence.
- `Auto-refresh request audit` polls `/request-log` every 5 seconds while the page is visible.
- The checklist preserves the latest health/readiness/audit state while the operator inspects result JSON or artifacts.

Operational rule:

- The checklist is a local operator aid. It does not bypass the Linux-side Equipment Agent, Guardian, Vision evidence, Linux CSV pull, or Analysis handoff gates.

## 2026-05-30 Linux `/equipment/windows` Operator Rail

The Linux-side Windows Equipment setup page now mirrors the Windows-side operator-console concept with a five-step command rail:

1. `Scan`: discover token-verified bridge candidates.
2. `Readiness`: validate saved connection and UTM profile readiness.
3. `Preflight`: perform non-actuating live bridge checks.
4. `UTM Run`: execute the configured UTM protocol or simulation through the existing run handler.
5. `Evidence`: verify the latest handoff proof before Analysis consumes UTM data.

The command rail does not introduce new backend privileges. It clicks the existing controls and keeps the detailed forms visible for subnet/token setup, UTM profile editing, locator calibration, proof-package creation, and request-log audit.

Registered UTM protocols listed by the Linux client now include public protocol contract fields such as preconditions, expected screen states, save policy, output artifacts, and safe-abort metadata. Use this output to confirm that Linux and Windows agree on the protocol before a live run.

## 2026-05-30 UTM Stop/Abort from Linux Equipment GUI

The Linux `/equipment/windows` page includes a dedicated `Abort` rail action and `Run UTM Stop/Abort` button for `utm_stop_or_abort_v1`.

This recovery macro intentionally bypasses the normal UTM locator/readiness/live-preflight checks. The purpose is to keep a safe stop path available even if the UTM software is in an unexpected screen state. It still requires explicit operator confirmation and uses the selected Windows bridge token/session. After dispatch, check Request Audit to confirm that `/execute` was recorded.

Do not use the stop/abort response as evidence of a completed test. It is recovery evidence only.

## 2026-05-30 Windows-Side GUI Recovery Rail Update

The Windows-side bridge page now exposes `Stop / Abort` in both the UTM protocol control row and the top command rail.

Behavior:

- The button sends the registered `utm_stop_or_abort_v1` payload to `/execute`.
- It does not run the normal live UTM preflight first, because the recovery macro must remain available when UTM locators, screen state, or the live run are stuck.
- It still records the request in `bridge_requests.jsonl`, so the Linux side can audit that `/execute` reached the Windows bridge.
- After using recovery, run `Request Log` and `Refresh Evidence` before retrying a normal UTM protocol.

The Linux `/equipment/windows` page also includes `Open Windows GUI`, which opens the selected bridge URL in a new tab. Use it after saving/selecting a token-verified candidate so the Windows operator can inspect local health, locator readiness, evidence, and recovery controls directly.

## 2026-05-30 Windows GUI Operator Console and Payload Preview

The Windows-side bridge GUI now includes a `Local Operator Console` above the runtime overview.

Purpose:
- Show the exact `/execute` payload before a Windows GUI command is sent.
- Distinguish `Simulation`, `Live UTM`, and `Stop / Abort` intent locally on the Windows PC.
- Validate required command identity and numeric artifact timing fields before the browser starts live preflight.
- Keep the registered `Stop / Abort` recovery button available even while another GUI command is marked busy.

Operator flow:
1. Confirm `Health` and token reachability.
2. Fill `Run ID`, `Specimen ID`, export glob, artifact timeout, stable-file time, and optional target window.
3. Use `Preview Sim`, `Preview Live`, or `Preview Abort` to inspect the exact payload envelope.
4. Use `Safe Preflight` before live control.
5. Use `Preflight + Run Live UTM` only after physical setup confirmation.
6. If the UTM GUI becomes stuck, use `Stop / Abort`; it dispatches `utm_stop_or_abort_v1` without requiring the normal live preflight gate.

Validation behavior:
- Empty `Run ID` or `Specimen ID` blocks browser-side command submission.
- `Artifact Timeout Sec` and `Stable File Sec` must be positive numeric values.
- On validation failure, the GUI renders `WINDOWS_GUI_INPUT_INVALID` and does not call `/health`, `/readiness`, `/request-log`, or `/execute` for that command.

This is a local operator safeguard. The Linux Lab Equipment Agent still performs its own bridge audit, request-log audit, screen-state evidence checks, physical cross-check, and UTM data artifact pull before handing off to Analysis.

## 2026-05-30 Bridge Health Version Metadata

The Windows bridge `/health` response now reports:

```json
{
  "server_version": "WindowsPyAutoGUIBridge/0.1",
  "script_version": "windows_pyautogui_bridge_server.py:utm_visual_control_v1",
  "pyautogui": {
    "available": true,
    "failsafe": true,
    "pause": 0.1
  }
}
```

The Linux bridge client adds live-call metadata before the Equipment Agent packages the report:

```json
{
  "bridge_url": "http://<windows-ip>:8765",
  "bridge_host": "<windows-ip>",
  "client_latency_ms": 1.23
}
```

Use these fields when debugging mismatched Windows hosts, stale helper scripts, PyAutoGUI import failures, or unexpected network latency.

## Operator JSON Safety Note

The Windows bridge `/execute` endpoint is fail-closed for unsupported `sequence[]` actions. Direct use of the Windows Web GUI `Run JSON` panel does not bypass the action contract: an unknown action such as `shell` returns `PYAUTOGUI_ACTION_NOT_ALLOWED` and the sequence is blocked. Use registered programs for UTM work and use custom JSON only for bounded calibration/debug actions.

## 2026-05-30 Compact Windows Operator GUI

The Windows bridge page has a compact operations layout for live UTM work.

- `Overview` is shown before the payload console and timeline so the operator sees bridge status, proof gates, request audit, and data/export state first.
- The overview area uses two columns on wide monitors and keeps proof/evidence cards full-width for readability.
- Connection, diagnostics, UTM protocol, locator capture, and operator log sections have `Collapse` / `Expand` controls. These preferences are local to the browser.
- The GUI layout is only an operator convenience layer. Live control remains blocked unless token auth, safe preflight, locator readiness, physical safety confirmation, and `/execute` audit requirements are satisfied.

## 2026-08-04 Essential Windows Operator Surface

The Windows-local bridge page now opens on a compact essential surface intended for normal operation:

1. `Bridge Connection`: token, Health/Refresh, bridge reachability, and PyAutoGUI availability.
2. `Latest Test Result`: the latest validation, registration, deletion, or bounded test response.
3. `Program Manager`: immutable built-ins plus persistent custom JSON macros.

The Program Manager editor is closed by default. It opens only for New, Edit,
View, or Browse JSON and closes after Add to Registry or Cancel. Browse and
template download are deliberately separate from registration.

`Advanced Tools` is closed by default and contains deployment helpers,
readiness, locator calibration, screenshots, UTM controls, timeline, evidence,
artifacts, and generic JSON execution. Duplicate Program Manager and command
proxy controls are not repeated there.

The repeatable browser audit is:

```bash
python tests/ui/windows_bridge_gui_browser_audit.py \
  --base-url http://127.0.0.1:8765 \
  --token '<bridge-token>' \
  --width 1920 --height 1080
```

### Windows Console Device Bridge Layout

The complete standalone console uses the same pale blue-gray workspace, white
cards, cobalt headings/actions, and responsive card grids as the ATR Device
Bridge pages. This covers the header, Bridge Connection, Latest Test Result,
Program Manager, and the collapsed or expanded `Advanced Tools` workspace. The
CSS remains embedded in the Windows server so the packaged GUI does not depend
on the Linux ATR web server.

Operational button labels, status text, and guidance wrap instead of being
truncated. Paths, commands, and JSON remain contained in their own wrapping or
scrolling fields. The browser audit opens the Advanced panel and fails when a
visible operational element clips horizontally. Run the audit at both target
desktop sizes when changing the embedded GUI:

```bash
python tests/ui/windows_bridge_gui_browser_audit.py \
  --base-url http://127.0.0.1:8765 --token '<bridge-token>' \
  --width 1920 --height 1080 \
  --out-dir artifacts/ui/windows_bridge_advanced_1920

python tests/ui/windows_bridge_gui_browser_audit.py \
  --base-url http://127.0.0.1:8765 --token '<bridge-token>' \
  --width 1366 --height 768 \
  --out-dir artifacts/ui/windows_bridge_advanced_1366
```

## Inline Advanced Visual Work Queue Reproduction

The advanced work-queue verification runs on Linux against the exact packaged
Windows bridge source. It uses an isolated X11 display and bridge port so the
ATR main GUI on `7860` and active model servers are not restarted or modified.

Required local components are Tkinter, PyAutoGUI, pynput, Pillow, OpenCV,
pytest, and Xvfb. Install them through the project requirements before running
these commands; do not substitute another bridge implementation.

Run the focused contracts:

```bash
.venv/bin/pytest -q \
  tests/unit/test_advanced_visual_work_queue_demo.py \
  tests/unit/test_advanced_visual_work_queue_e2e.py \
  tests/unit/test_equipment_skill_runtime.py \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_windows_pyautogui_demo_assets.py
```

Create and verify a new immutable Skill version:

```bash
.venv/bin/python scripts/advanced_visual_work_queue_e2e.py \
  --scenario all \
  --version 1.0.6 \
  --display :99 \
  --bridge-port 8878
```

Use a higher unused version for later recordings. Use `--reuse-skill` only to
replay an already validated package without lifecycle mutation. The runner
refuses port `7860`.

Expected evidence:

```text
runs/equipment_skill_advanced_queue_e2e/e2e_summary.json
runs/equipment_skill_advanced_queue_e2e/evidence/recorded_before.png
runs/equipment_skill_advanced_queue_e2e/evidence/recorded_validation_failed.png
runs/equipment_skill_advanced_queue_e2e/evidence/recorded_completed.png
runs/equipment_skill_advanced_queue_e2e/evidence/recorded_exported.png
runs/equipment_skill_advanced_queue_e2e/evidence/shifted_reordered_before.png
runs/equipment_skill_advanced_queue_e2e/evidence/shifted_reordered_exported.png
runs/equipment_skill_advanced_queue_e2e/demo_runtime/output/advanced_queue_result.json
runs/equipment_skill_advanced_queue_e2e/demo_runtime/output/advanced_queue_result.csv
memory/equipment_skills/advanced_visual_work_queue_demo/1.0.6/
```

Success requires shifted/reordered replay to export `specimen-beta`,
`Compression`, `evidence_enabled=true`, and `load_limit=12.5` after exactly one
bounded recovery. The missing-target scenario is successful only when replay
returns `UI_LOCATOR_NOT_FOUND`, preserves an empty queue, performs zero analysis
attempts, and writes screenshot evidence without creating JSON or CSV output.
