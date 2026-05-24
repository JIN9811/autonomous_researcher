# Windows PyAutoGUI Bridge Setup Guide

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

The Windows bridge service should expose only these endpoints:

- `GET /health`
- `GET /programs`
- `POST /execute`

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

The exact command depends on the bridge server implementation file.

Recommended future file location in this project:

```text
install/windows_pyautogui_bridge_server.py
```

Expected start command on Windows:

```powershell
py C:\path\to\windows_pyautogui_bridge_server.py
```

The bridge should print:

```text
Windows PyAutoGUI bridge listening on 0.0.0.0:8765
Token authentication: enabled
PyAutoGUI available: true|false
PyAutoGUI FAILSAFE: True when available
```

Keep this terminal open during live operation unless the bridge is installed as a Windows service later.

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

- The project guideline exists for the Linux/server side.
- This document defines the Windows-side setup and operating contract.
- The Windows-side contract now includes macro discovery through `/programs` and demo macro execution with `program_id: "program1"`.
- The bridge should support communication and dependency reporting even before PyAutoGUI is installed.
- The actual Windows bridge server implementation has not yet been added.
- The current `equipment_agent` still uses the existing UTM-style tool until the next implementation phase.

Next implementation phase:

1. Add `device_bridges/windows_pyautogui_bridge.py`.
2. Add `mcp_tools/equipment_tools.py`.
3. Add simulator and live mode unit tests.
4. Add optional `install/windows_pyautogui_bridge_server.py`.
5. Update `equipment_agent` to prefer `equipment.pyautogui.run`.
