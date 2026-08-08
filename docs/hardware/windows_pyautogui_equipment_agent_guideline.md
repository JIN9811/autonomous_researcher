# Windows PyAutoGUI Equipment Agent Runtime Guideline

## Recorded Equipment Skills

New operator demonstrations use `atr.equipment_recording.v2` and image-first
pointer targets. Click replay resolves a SHA-256-verified tight/context PNG pair;
drag replay resolves separate source and destination pairs. Recorded x/y values
are evidence only unless the operator explicitly enabled coordinate fallback.
Required image misses save current-screen evidence and return
`UI_LOCATOR_NOT_FOUND`; they do not silently execute the recorded coordinate.
Legacy v1 coordinate recordings remain supported for compatibility.

The Equipment stage can run a versioned recorded Skill without adding another
top-level agent or graph stage. Linux is authoritative for Skill packages and
execution state; Windows records demonstrations and executes the compiled
bounded programs.

Runtime path:

`EquipmentAgent -> equipment.pyautogui.run -> WindowsPyAutoGUIBridge -> exact registered atr.pyautogui_program.v1 segment`

Normal execution is deterministic and does not call an LLM. Annotation and a
single bounded pre-actuation recovery decision use the provider/model snapshot
stored with the Skill. If that exact model is unavailable, the operation is
reported as unavailable; no model fallback is attempted. Windows stores no API
key and exposes no model selector.

Lifecycle:

`recording -> draft -> annotated -> compiled -> validated -> deployed -> tested -> disabled -> deleted`

- One exact `skill_id@version` is selected; there is no latest-version fallback.
- Compilation preserves the 100-action maximum per registered segment.
- Deployment verifies every canonical program SHA-256 before marking the Skill
  deployed.
- Deletion is blocked until the deployed version is disabled.
- Recovery is limited to allowlisted pre-actuation operations and one Guardian-
  approved attempt. Partial actuation escalates instead of replaying blindly.

Authoritative storage:

- Skill package: `memory/equipment_skills/<skill_id>/<version>/`
- Execution state: `memory/equipment_skill_executions/<execution_id>/state.json`
- Windows recordings: `WINDOWS_PYAUTOGUI_RECORDING_DIR`, default
  `C:\ATR\recordings`

The Windows Program Manager provides `PROGRAMS`, `EXAMPLES`, `RECORD`, and
`SKILLS` tabs. `EXAMPLES` is a read-only catalog backed by `GET /examples`; it
loads definitions into the normal editor without implicit registration. The
local Capability Lab is served at `/capability-lab`.
The eight bundled definitions collectively cover the complete exposed
safe-core action catalog. Five coordinate-bounded examples are directly
testable; image matching, stable-file waiting, and operator dialogs require
their explicit setup or confirmation before execution.
Its Test/Delete controls proxy the same Linux API used by CUI clients. Live GUI
projects the exact version, target profile, completed segments, model snapshot,
exception boundary, and recovery history into the Equipment report.

Recording normalization classifies click and drag on button release, suppresses
intermediate drag motion, captures horizontal/vertical scroll, and compacts
consecutive printable keys into one `write` action. Every draft stores
`capability_coverage` in both `manifest.json` and `workflow.json`, allowing GUI
and CUI clients to inspect the exact mouse/keyboard/screen families exercised by
the demonstration. Credentials must never be entered while recording because a
global input recorder cannot reliably identify secret fields in third-party
applications.

The bounded runtime action surface covers mouse, keyboard, screen/pixel, window,
timing, and manually confirmed dialog families. Runtime validation rejects
out-of-screen absolute coordinates, unbounded repeats, oversized scrolls,
invalid regions/colors, and unattended dialogs. A final cleanup releases held
mouse buttons and keyboard keys on all exits. Shell execution, arbitrary Python,
file deletion, password entry, window close, and process termination remain
outside the Equipment Skill contract.

HTTP/CUI examples:

```bash
curl -s http://127.0.0.1:7860/api/equipment/skills
curl -s -X POST http://127.0.0.1:7860/api/equipment/skills/demo/1.0.0/test \
  -H 'Content-Type: application/json' \
  -d '{"runtime_mode":"test","confirm_execute":false}'
curl -s -X POST http://127.0.0.1:7860/api/equipment/skills/demo/1.0.0/enabled \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
curl -s -X DELETE http://127.0.0.1:7860/api/equipment/skills/demo/1.0.0
```

Live testing requires `runtime_mode=live` and `confirm_execute=true`.

## Common Equipment Workspace

`/equipment/windows` is the common Lab Equipment Workspace. It selects a
registered equipment profile, then uses one shared sequence for connection,
test, runtime, evidence, and Analysis handoff. The initial profile is
`utm_windows_v1`; additional equipment must be registered as profiles rather
than copied into a separate agent path.

### Embedded Windows Console

The **Open Windows GUI** action opens the original HTML GUI served by the
selected Windows bridge in a separate tab through
`/equipment/windows/bridge-ui/`; it does not recreate the Windows controls.
All console calls are proxied only to the saved candidate, and ATR injects the
stored bridge token server-side. The browser receives neither the token value
nor a token-bearing target URL. If the selected bridge is unreachable, the
embedded console returns its bridge failure response while the surrounding ATR
profile state remains available.

### Complete Windows Program Console

As of 2026-08-04, the Windows page exposes a setup-first surface backed by a persistent bounded-macro registry.

- `GET /programs` remains the only source of executable program IDs.
- Built-in programs are immutable and remain visible inside Program Manager.
- Custom macros are validated and stored under `WINDOWS_PYAUTOGUI_PROGRAM_DIR` (default `C:\ATR\programs`).
- `Browse JSON` loads an edited file into the editor without registering it.
- `Download Template` saves an `atr.pyautogui_program.v1` starter definition without registering it.
- `Validate` calls `POST /programs/validate`; `Add to Registry` separately calls `POST /programs/register`.
- Custom enable/disable edits the persisted definition; delete calls `DELETE /programs/{program_id}`.
- Arbitrary `.py`, `.ps1`, `.bat`, `.cmd`, and `.exe` registration is rejected; only bounded bridge actions are accepted.
- Test uses the existing authenticated `POST /execute` route.
- Health, readiness, safe preflight, UTM simulation/live/abort, locator capture, screenshots, artifacts, request audit, generic sequence execution, trace, and timeline remain directly accessible.
- `program1` and the four UTM defaults remain visible after the registry loads.
- Simplification may regroup controls but must not delete a capability or leave a backend function without an operator-accessible control.

The Linux workspace remains authoritative for orchestration, physical validation, handoff trust, and Guardian-visible alarms. The Windows console provides the local control and evidence view of the same bridge.

### Local Development Candidate

The same Workspace can supervise an ATR-owned Linux/X11 bridge at
`127.0.0.1:8767`. It is persisted as candidate `local_development` with
`platform=linux`, `scope=localhost`, and `managed_local=true`. Starting it only
registers a standby candidate; the operator must explicitly select it. This
keeps Windows and local development targets switchable without fallback or a
second Equipment execution implementation. Once selected, agents and GUI/CUI
calls still traverse `WindowsPyAutoGUIBridge` and the existing
`equipment.pyautogui.*` tools.

Local program definitions use the same schema and allowlist. Portable actions
remain reusable, while Windows UIA selectors, target window titles, image
locators, coordinates, and absolute paths are marked for Windows recalibration.
The local bridge requires X11 and fails closed on Wayland or a missing display.

UTM Test and Live use the same saved Windows bridge target, registered program
IDs, locator contract, request log, screenshot contract, CSV contract, and
Analysis payload. Test sends `simulate_utm_protocol=true` to the existing
Windows bridge package. Live sends the same program with simulation disabled.
Live must never silently fall back to simulation.

The Test Bridge is not a second service. It is the existing
`Pyautogui_server_for_window` bridge executing its bounded UTM simulation.
Successful test evidence requires a simulated screenshot, bridge request log,
parseable CSV, and an Analysis-ready handoff payload.

Status: implementation guideline only. No runtime code is defined in this document.

Purpose:

- Extend the existing `equipment_agent` so it can operate, control, and monitor a Windows PC on the internal network through PyAutoGUI.
- Keep the current project stage order, agent names, and `AgentResult` contracts unchanged.
- Use a constrained bridge protocol instead of arbitrary remote-code execution.

Windows host setup:

- See `docs/hardware/windows_pyautogui_bridge_windows_setup.md` for Windows PC installation, firewall, token, bridge startup, and manual validation procedure.
- See `docs/hardware/lab_equipment_utm_visual_control_completion_audit.md` for the Improvement 05 evidence matrix, validation commands, and remaining real-UTM live validation checklist.

Primary target:

- Linux autonomous researcher server runs the orchestration workflow.
- Windows PC runs a small PyAutoGUI bridge service.
- `equipment_agent` lets the LLM select appropriate MCP-style tool calls from the current state, user command, and bridge health.
- The bridge executes only structured, allowlisted actions or registered macro programs.
- The Windows bridge performs GUI automation, returns step traces, screenshots or screenshot metadata, and health status.
- Operators can open `/equipment/windows` from Main GUI -> Device Workspaces to discover, select, save, and test a Windows bridge host.
- The Linux-side `/equipment/windows` GUI exposes `Live Validation Report` as a non-actuating bridge readiness report. It checks live request-log, health, and program registry, persists `lab_equipment_utm_live_validation.json`, and never sends `/execute`. The adjacent `Run Physical Validation` path is guarded by explicit physical-safety confirmation and only then may send `/execute`.
- The standalone Windows bridge Web GUI renders a persistent Program Manager backed by the Windows bridge registry.
- Live situation, readiness, `/execute` evidence, and handoff trust remain in the Linux Lab Equipment Workspace; the Windows page does not duplicate them.

Reference sources:

- PyAutoGUI official docs describe mouse/keyboard control, screenshots, image location, and Windows support: <https://pyautogui.readthedocs.io/>
- PyAutoGUI installation on Windows is `py -m pip install pyautogui`: <https://pyautogui.readthedocs.io/en/latest/install.html>
- PyAutoGUI keyboard functions include `write`, `press`, and `hotkey`-style key composition: <https://pyautogui.readthedocs.io/en/latest/keyboard.html>
- PyAutoGUI mouse functions include `click`, `doubleClick`, movement, scroll, and button selection: <https://autogui.readthedocs.io/en/latest/mouse.html>
- PyAutoGUI screenshot and image-location calls are available, but locate calls can take seconds and `confidence` needs OpenCV: <https://pyautogui.readthedocs.io/en/latest/screenshot.html>
- PyAutoGUI fail-safe is enabled by default and should not be disabled; moving the mouse to a screen corner can abort runaway automation: <https://pyautogui.readthedocs.io/en/latest/index.html>
- Microsoft recommends minimizing Windows Firewall exceptions and notes that opening a port is riskier than allowing a specific app: <https://support.microsoft.com/en-us/windows/risks-of-allowing-apps-through-windows-firewall-654559af-3f54-3dcf-349f-71ccd90bcc5c>
- Microsoft Firewall rules can scope inbound access by app, port, protocol, profile, and other criteria: <https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules>

============================================================
1. Existing Project Constraints
============================================================

Do not change these contracts:

- Stage enum values in `orchestrator/state.py`.
- Stage order in `orchestrator/transitions.py`.
- Stage routing in `orchestrator/router.py` except if explicitly required by a larger architecture change.
- Agent name: `equipment_agent`.
- Agent interface: `async run(state: OrchestratorState, ctx: AgentContext) -> AgentResult`.
- Existing output compatibility:
  - `AgentResult.success`
  - `AgentResult.summary`
  - `AgentResult.data["equipment_result"]`
  - `AgentResult.data["protocol_note"]`

Current workflow route:

`Design -> Specimen Making -> Vision -> Manipulation -> Equipment -> Analysis -> Knowledge -> Guardian`

Current Equipment Agent state:

- File: `agents/equipment_agent.py`
- Current tool: `utm.run_protocol`
- Current summary: `Equipment protocol run completed`
- Current data keys: `equipment_result`, `protocol_note`
- Current implementation is a simple UTM-style mock runner.

Required compatibility rule:

- The new Windows PyAutoGUI path must return `equipment_result` and `protocol_note`.
- Downstream agents must not need to know whether the equipment tool was UTM, simulator, or Windows PyAutoGUI.
- Legacy `utm.run_protocol` may remain as fallback or separate physical-equipment path, but the Windows PyAutoGUI bridge should be the first real-control target for this task.

============================================================
2. Architecture Decision
============================================================

Use this architecture:

`equipment_agent -> ToolRegistry -> equipment.pyautogui.run -> WindowsPyAutoGUIBridge -> Windows bridge HTTP server -> PyAutoGUI`

Do not use:

- Direct Python execution on the Windows PC from the LLM.
- Raw shell command transport.
- Unauthenticated HTTP endpoints.
- Public-network exposure.
- RDP/GUI automation as the primary programmatic interface.
- A new top-level `windows_pc` or `pyautogui` stage.

Reasoning:

- PyAutoGUI is designed for local GUI automation, not secure remote transport.
- A bridge service provides the missing transport boundary.
- Existing project architecture already isolates hardware actions behind MCP-style tools.
- Tool calls can be logged, validated, simulated, and streamed into Live GUI events.

============================================================
3. Agent Role
============================================================

`equipment_agent` should become the stage owner for Windows-hosted equipment software automation.

Responsibilities:

- Select a Windows PyAutoGUI sequence from `state.current_experiment_spec` or use a safe configured default.
- Ask the model only to format or verify a concise action plan, not to invent unsafe low-level clicks without constraints.
- Call `equipment.pyautogui.run`.
- Preserve `equipment_result` and `protocol_note`.
- Surface bridge health, action trace, screenshot metadata, and failure codes to the GUI/logs.
- Fail closed in live mode when connection info or live execution approval is missing.

Non-responsibilities:

- It should not manage Windows firewall rules automatically.
- It should not install Python packages on the Windows PC automatically.
- It should not execute arbitrary Python code from a chat message.
- It should not own Vision/Manipulation stages.
- It should not bypass Guardian or runtime safety gates.

============================================================
4. Tool Contract
============================================================

Add these MCP-style tools:

`equipment.pyautogui.health`

Purpose:

- Check whether the Windows bridge is reachable and whether PyAutoGUI is available.

Minimal payload:

```json
{}
```

Typical response:

```json
{
  "ok": true,
  "tool": "equipment.pyautogui.health",
  "mode": "simulator",
  "bridge": "windows_pyautogui",
  "status": "ready",
  "screen": {"width": 1920, "height": 1080},
  "pyautogui": {"available": true, "failsafe": true, "pause": 0.1}
}
```

`equipment.pyautogui.list_programs`

Purpose:

- Return registered macro programs that the LLM can choose from when deciding the next tool call.
- This allows commands like `program1 실행` or later experiment-specific macros to be resolved without hardcoding every macro into `equipment_agent`.

Minimal payload:

```json
{}
```

Typical response:

```json
{
  "ok": true,
  "tool": "equipment.pyautogui.list_programs",
  "mode": "live",
  "bridge": "windows_pyautogui",
  "programs": [
    {
      "program_id": "program1",
      "description": "Connectivity demo: bounded mouse wiggle and completion log.",
      "requires_pyautogui": true,
      "safe_test": true
    }
  ]
}
```

`equipment.pyautogui.live_validation`

Purpose:

- Build a non-actuating UTM live validation report before any physical UTM execution.
- Confirm live bridge request-log access, PyAutoGUI health, and registered UTM program visibility.
- Persist `artifacts/equipment/<run_id>/live_validation/lab_equipment_utm_live_validation.json`.
- Keep `/execute` out of the touched endpoint list in non-actuating mode.
- In physical mode, require `confirm_live_execute=true` and `confirm_physical_setup_safe=true`, run readiness/preflight first, then send `/execute` only if those gates pass.
- Treat physical completion as proven only when request-log identity, execution completion, screen state evidence, Vision proof, save/export, Linux artifact, and parse probe gates all pass.
- On successful physical validation, promote the report into `equipment_result`, `equipment_report`, `equipment_handoff`, and `utm_data_ready` so `AnalysisAgent` can consume the exported UTM CSV without a separate handoff adapter.
- Do not promote blocked physical validation reports into those standard handoff keys; keep them only as `last_windows_utm_physical_validation` and audit evidence.
- Final Improvement 05 completion requires a persisted proof package plus either `/api/equipment/windows/completion-audit` returning `status=complete_evidence_verified` or `./scripts/audit_lab_equipment_utm_completion.py --latest` returning exit code `0`; preflight-only or simulated reports are not enough.
- The API completion audit must persist `artifacts/equipment/<run_id>/utm/windows_utm_completion_audit_<timestamp>.json` so the final complete/incomplete decision is reviewable after the GUI/server session ends.

Minimal payload:

```json
{
  "confirm_non_actuating": true,
  "program_id": "utm_compression_start_v1",
  "specimen_id": "specimen-live-validation"
}
```

Typical response status:

```json
{
  "ok": true,
  "tool": "equipment.pyautogui.live_validation",
  "schema": "lab_equipment_utm_live_validation.v1",
  "status": "preflight_passed",
  "non_actuating": true,
  "ready_for_physical_live_run": true
}
```

`equipment.pyautogui.run`

Purpose:

- Execute an allowlisted GUI automation sequence on a Windows PC or simulator.
- Execute a registered macro program by `program_id` when the request is a named macro, for example `program1`.

Minimal payload:

```json
{
  "sequence_id": "equipment-check-001",
  "runtime_mode": "test",
  "program_id": "",
  "sequence": [
    {"action": "health"},
    {"action": "screenshot"}
  ],
  "experiment_spec": {}
}
```

Typical response:

```json
{
  "ok": true,
  "tool": "equipment.pyautogui.run",
  "mode": "simulator",
  "bridge": "windows_pyautogui",
  "status": "completed",
  "sequence_id": "equipment-check-001",
  "step_trace": [
    {"step": "CONNECT", "status": "ok"},
    {"step": "HEALTH", "status": "ok"},
    {"step": "SCREENSHOT", "status": "ok", "artifact": "artifacts/equipment/screenshots/example.png"},
    {"step": "DONE", "status": "ok"}
  ],
  "failure_code": null
}
```

Registered macro payload example:

```json
{
  "sequence_id": "macro-demo-001",
  "runtime_mode": "live",
  "program_id": "program1",
  "command": "program1 실행",
  "experiment_spec": {}
}
```

Registered macro response example:

```json
{
  "ok": true,
  "tool": "equipment.pyautogui.run",
  "mode": "live",
  "bridge": "windows_pyautogui",
  "status": "completed",
  "sequence_id": "macro-demo-001",
  "program_id": "program1",
  "program_log": "program1 completed",
  "step_trace": [
    {"step": "CONNECT", "status": "ok"},
    {"step": "HEALTH", "status": "ok"},
    {"step": "RESOLVE_PROGRAM", "status": "ok", "detail": "program1"},
    {"step": "EXECUTE_PROGRAM", "status": "ok", "detail": "demo_mouse_wiggle"},
    {"step": "DONE", "status": "ok", "detail": "program1 completed"}
  ],
  "failure_code": null
}
```

Failure response example:

```json
{
  "ok": false,
  "tool": "equipment.pyautogui.run",
  "mode": "live",
  "bridge": "windows_pyautogui",
  "status": "blocked",
  "failure_code": "PYAUTOGUI_BRIDGE_URL_REQUIRED",
  "requires_connection_info": true,
  "message": "Windows PyAutoGUI bridge URL is required for live execution.",
  "step_trace": [
    {"step": "PRECHECK", "status": "blocked", "detail": "missing bridge URL"}
  ]
}
```

PyAutoGUI-not-installed response example:

```json
{
  "ok": false,
  "tool": "equipment.pyautogui.run",
  "mode": "live",
  "bridge": "windows_pyautogui",
  "status": "blocked",
  "program_id": "program1",
  "failure_code": "PYAUTOGUI_NOT_INSTALLED",
  "requires_install": true,
  "message": "PyAutoGUI is not installed on the Windows bridge host. Install with: py -m pip install pyautogui",
  "step_trace": [
    {"step": "CONNECT", "status": "ok"},
    {"step": "HEALTH", "status": "blocked", "detail": "pyautogui import failed"}
  ]
}
```

============================================================
5. Allowlisted Action Model
============================================================

Allowed Phase 1 actions:

- `health`: verify bridge and PyAutoGUI state.
- `screenshot`: capture screenshot or screenshot metadata.
- `locate_image`: locate a known reference image on screen.
- `wait`: wait for a bounded duration.
- `move_to`: move pointer to safe coordinates.
- `click`: click bounded coordinates or located target.
- `double_click`: double-click bounded coordinates or located target.
- `press`: press one allowed key.
- `hotkey`: press a configured key combination.
- `write`: type bounded text into focused UI.
- `scroll`: scroll bounded amount.
- `run_registered_program`: execute an operator-defined macro by `program_id`.
- `demo_mouse_wiggle`: test-only bounded mouse movement used by `program1`.
- `log`: append a non-secret completion message to the response trace.

Explicitly forbidden in Phase 1:

- `eval`, `exec`, shell commands, PowerShell commands.
- File delete/move outside configured artifact directories.
- Arbitrary URL browsing from Windows.
- OS-level settings changes.
- Credential typing unless the credential value comes from an approved secret path and the action is explicitly enabled.
- Unbounded loops.
- Clicks outside detected screen bounds.
- Disabling `pyautogui.FAILSAFE`.
- Unknown `program_id` values.

Validation rules:

- Every action must have a known `action` string.
- Coordinates must be numeric and inside `pyautogui.size()`.
- Wait durations must have a maximum, e.g. `0 <= seconds <= 30`.
- Text written by `write` must have a maximum length and optional character policy.
- Hotkeys must be checked against a configured allowlist.
- `locate_image` may use `confidence` only if OpenCV is installed on the Windows bridge.
- `screenshot` should store artifacts under the project artifact directory or return metadata only.

============================================================
5.1 Registered Macro Program Model
============================================================

Use a registered macro program model for repeatable Windows automation.

Rationale:

- The operator wants to alternate between multiple macro programs.
- LLM should select the appropriate tool call and `program_id` from context, not follow a fixed hardcoded path.
- `program_id` routing is safer than letting the LLM generate raw low-level click scripts each time.
- The bridge can validate the selected macro before touching the mouse or keyboard.
- Each macro can emit a deterministic completion log, which is easier for Live GUI and run logs to display.

Required macro registry behavior:

- The Windows bridge owns the macro registry.
- LLM/tool caller may request `equipment.pyautogui.list_programs` first, then call `equipment.pyautogui.run` with a selected `program_id`.
- Linux sends `program_id` or a validated action sequence, not arbitrary Python.
- Each `program_id` maps to a fixed allowlisted action sequence.
- Unknown `program_id` must return `PYAUTOGUI_PROGRAM_NOT_FOUND`.
- Every macro must return `program_log`.
- Every macro must return `step_trace`.

Recommended Phase 1 macro registry:

```json
{
  "programs": {
    "program1": {
      "description": "Connectivity demo: move mouse briefly and return completion log.",
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

`program1` test behavior:

- First verify bridge communication.
- Check whether PyAutoGUI imports successfully.
- If PyAutoGUI is missing, return `PYAUTOGUI_NOT_INSTALLED`; do not crash the bridge.
- If PyAutoGUI is available, move the mouse a short bounded distance and return it near the original position.
- Emit `program_log: "program1 completed"`.

Better test recommendation:

- Use `program1` as a mouse wiggle demo only after PyAutoGUI installation is confirmed.
- Before that, let the LLM call `equipment.pyautogui.health` and `equipment.pyautogui.list_programs`, then call `equipment.pyautogui.run` with `program_id=program1` to prove network/token/program routing works without importing PyAutoGUI.
- This two-step test separates communication failure from GUI automation failure and is easier to debug.

============================================================
6. Runtime Modes
============================================================

Test mode:

- Default to simulator.
- No real Windows PC should be touched.
- Return deterministic `step_trace`.
- Simulate screen size, screenshot artifact path, and bridge health.
- Use this path for CI/unit tests and normal `test` workflow.

Live GUI test command:

- If the user enters `테스트 모드` inside Live GUI, keep the global workflow behavior already established for test handoffs.
- For Equipment Agent, use simulator unless a deliberate bench-test option is explicitly selected later.
- Do not silently promote to real Windows control from a chat phrase.

Live mode:

- Require bridge URL.
- Require token if token auth is configured.
- Require `allow_live_execute: true` in config.
- Fail closed if the bridge is unreachable.
- Return explicit `connection_info_required` or `live_execution_blocked` status rather than falling back to simulator.

Bench test mode, optional later:

- A separate config flag may permit real Windows bridge calls during test workflow.
- This must be opt-in, similar to existing printer `test_printer_live_promotion`.
- Default remains virtual.

============================================================
7. Config Design
============================================================

Add under `configs/devices.yaml`:

```yaml
  equipment:
    mode: simulator              # simulator | live
    provider: windows_pyautogui
    windows_pyautogui:
      enabled: true
      bridge_url_env: WINDOWS_PYAUTOGUI_BRIDGE_URL
      token_env: WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
      token_header: X-Bridge-Token
      request_timeout_sec: 10
      discovery_timeout_sec: 0.45
      discovery_port: 8765
      allow_live_execute: false
      allow_screenshot: true
      artifact_dir: artifacts/equipment
      connection_memory_path: memory/windows_pyautogui_connection.json
      allowed_actions:
        - health
        - screenshot
        - locate_image
        - assert_text
        - wait_until_text
        - wait
        - move_to
        - click
        - double_click
        - press
        - hotkey
        - write
        - scroll
        - run_registered_program
        - demo_mouse_wiggle
        - log
      allowed_hotkeys:
        - ["ctrl", "s"]
        - ["ctrl", "o"]
        - ["alt", "f4"]
        - ["enter"]
        - ["esc"]
      limits:
        max_wait_sec: 30
        max_write_chars: 512
        max_steps: 50
      simulator:
        screen_width: 1920
        screen_height: 1080
        screenshot_name: simulated_windows_screen.png
      test_live_promotion:
        enabled: false
        transport: virtual        # virtual | real
        allow_real_network_in_test: false
      default_sequence:
        - action: health
        - action: screenshot
      registered_programs:
        program1:
          description: "Connectivity demo: bounded mouse wiggle and completion log."
          requires_pyautogui: true
          sequence:
            - action: health
            - action: demo_mouse_wiggle
              duration_sec: 1.0
              distance_px: 20
            - action: log
              message: "program1 completed"
```

Environment variables:

```bash
WINDOWS_PYAUTOGUI_BRIDGE_URL=http://<windows-private-ip>:8765
WINDOWS_PYAUTOGUI_BRIDGE_TOKEN=<random-long-token>
```

Connection selection memory:

```text
memory/windows_pyautogui_connection.json
```

The runtime resolves the bridge URL and token in this order:

1. environment variables
2. saved connection memory
3. no live bridge selected

Live GUI setup route:

```text
/equipment/windows
```

This GUI scans the current network or a user-provided subnet for `/health`, lets the operator select a candidate, saves the selected URL/token to memory, runs health/program tests, and can explicitly run `program1`.

Discovery and selection rule:

- The scan request must include the bridge token.
- Hosts are listed only when `/health` succeeds with the supplied token.
- Hosts that answer without token authentication are not listed.
- Hosts that return `401` or `403` with the supplied token are not listed.
- Selecting a host requires a human-readable candidate alias, for example `windows_pyautogui_pc_1`.
- The alias is entered on the discovered candidate card after scan, not before scan.
- The selected candidate is stored under `candidates.<candidate_alias>` in `memory/windows_pyautogui_connection.json`.
- The saved candidate includes host, port, token, token header, and live-execution setting.
- The selected candidate can set `allow_live_execute: true`, which lets Live-mode Equipment Agent tool calls quick-connect to that bridge without editing `devices.yaml`.
- The setup GUI shows saved candidates above the bridge test controls and supports Quick Select/Delete.

Live enablement should require both:

- `devices.equipment.mode: live`
- `devices.equipment.windows_pyautogui.allow_live_execute: true`

============================================================
8. Windows Bridge Service Requirements
============================================================

The Windows PC should run a small local Python service that imports PyAutoGUI and exposes only constrained endpoints.

Required endpoints:

- `GET /health`
- `GET /programs`
- `POST /execute`

Discovery behavior:

- The Linux server scans the current IPv4 `/24` network by default.
- The operator may enter a specific subnet, for example `192.168.0.0/24`.
- Candidates are accepted only when `/health` returns success with the supplied token.
- If token is missing, discovery returns `PYAUTOGUI_TOKEN_REQUIRED`.
- Discovery does not execute GUI actions.

Required authentication:

- Token header, default `X-Bridge-Token`.
- Reject missing or mismatched token when token is configured.

Required network posture:

- Bind only to the Windows PC LAN interface or `0.0.0.0` only when firewall-scoped to a private LAN.
- Prefer a Windows Firewall app rule over a broad open-port rule when practical.
- If a port rule is used, scope it to the private profile and trusted subnet.
- Never expose the bridge to the public internet.

Required PyAutoGUI settings:

```python
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1
```

The bridge must never set `FAILSAFE = False`.

Bridge response requirements:

- Return `ok: bool`.
- Return `step_trace`.
- Return screen size on health.
- Return screenshot path or metadata.
- Return clear `failure_code` values.
- Return registered macro metadata from `/programs`.
- Log every accepted action locally.
- Reject unknown actions before touching the GUI.
- Reject unknown macro program IDs before touching the GUI.

============================================================
9. Files To Add Or Modify Later
============================================================

Implementation should be concentrated in these files:

- `agents/equipment_agent.py`
  - Prefer LLM-selected calls to `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, and `equipment.pyautogui.run` for Windows GUI automation.
  - Preserve `equipment_result` and `protocol_note`.
  - Fall back to `utm.run_protocol` only when the Windows PyAutoGUI tool is not registered or when a legacy UTM profile is explicitly selected.

- `mcp_tools/equipment_tools.py`
  - Register `equipment.pyautogui.health`.
  - Register `equipment.pyautogui.list_programs`.
  - Register `equipment.pyautogui.run`.
  - Convert payloads into bridge calls.

- `device_bridges/windows_pyautogui_bridge.py`
  - Implement simulator and live bridge client.
  - Validate actions and mode gates.
  - Use HTTP calls to the Windows bridge service in live mode.

- `configs/devices.yaml`
  - Add the `devices.equipment` section described above.

- `app/bootstrap.py`
  - Import and call `register_equipment_tools(tools, cfg.get("devices", {}), repo_root=resolve_path("."))`.
  - Register after mock tools and printer tools so the concrete equipment tool overrides only intended names.

- `app/main.py`
  - Expose `/equipment/windows`.
  - Expose `/api/equipment/windows/config`, `/discover`, `/connect`, `/test`, and `/run-program`.

- `web/templates/windows_equipment.html`
  - Dedicated operator GUI for bridge discovery/selection/testing.

- `web/static/windows_equipment.js`
  - Frontend for scan, save, health/program test, and explicit `program1` demo.

- `mcp_tools/schemas.py`
  - Add optional Pydantic schemas for PyAutoGUI health/run payloads if schema validation is desired.

- `install/windows_pyautogui_bridge_server.py`
  - Windows-side helper service.
  - Should remain explicitly installed/run by the operator, not started automatically from Linux.

- `tests/unit/test_equipment_pyautogui_bridge.py`
  - Test simulator success.
  - Test missing live URL failure.
  - Test blocked live execution when `allow_live_execute` is false.
  - Test unknown action rejection.
  - Test unknown macro program rejection.
  - Test `program1` missing-PyAutoGUI response.
  - Test `program1` success response with completion log.
  - Test coordinate bounds validation.

- `tests/unit/test_equipment_agent.py`
  - Test that `equipment_agent` can choose `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, and `equipment.pyautogui.run` through LLM/tool-call planning.
  - Test that output keys remain stable.
  - Test legacy UTM fallback only under expected conditions.

============================================================
10. Equipment Agent Behavior
============================================================

LLM tool-calling behavior:

- The Equipment Agent should not blindly run a fixed default sequence when a user command implies a macro program.
- It should ask the LLM to choose among available tool calls from bridge state and user intent.
- Typical path for `program1 실행`:
  - call `equipment.pyautogui.health`
  - if bridge is reachable, call `equipment.pyautogui.list_programs`
  - if `program1` exists, call `equipment.pyautogui.run` with `program_id: "program1"`
  - if PyAutoGUI is missing, return the install-required result rather than falling back to simulator in live mode

Input priority for action sequence:

1. explicit user command mapped by LLM to `program_id`, for example `program1 실행`
2. `state.current_experiment_spec["equipment_program_id"]`
3. `state.current_experiment_spec["equipment"]["program_id"]`
4. `state.current_experiment_spec["equipment_pyautogui_sequence"]`
5. `state.current_experiment_spec["equipment_sequence"]`
6. `state.current_experiment_spec["equipment"]["pyautogui_sequence"]`
7. Config `default_sequence`

Recommended agent payload:

```json
{
  "sequence_id": "equipment-<run_id>",
  "runtime_mode": "live",
  "program_id": "program1",
  "sequence": [],
  "experiment_spec": {},
  "source_stage_context": {
    "vision": {},
    "manipulation": {},
    "analysis": {}
  }
}
```

Recommended `AgentResult.data`:

```json
{
  "equipment_result": {},
  "protocol_note": "Windows PyAutoGUI bridge sequence prepared and executed.",
  "equipment_bridge": "windows_pyautogui",
  "equipment_handoff": {
    "status": "ready_for_analysis",
    "bridge": "windows_pyautogui",
    "program_id": "program1",
    "sequence_id": "equipment-<run_id>",
    "failure_code": null
  }
}
```

Main-loop integration:

- The stage order is `Manipulation -> Lab Equipment -> Analysis`.
- `RunLoop` stores `equipment_result` in `state.run_metadata.equipment_result`.
- `RunLoop` stores `equipment_handoff` in `state.run_metadata.equipment_handoff`.
- `RunLoop` exposes `equipment_ok`, `equipment_status`, `equipment_program_id`, and any `equipment_failure_code` under `state.latest_analysis`.
- Validation requires `equipment_result` and `protocol_note`; if `equipment_result.ok=false`, the Equipment stage must retry or stop before Analysis.

If live bridge information is missing:

- `success` should be `false`.
- `equipment_result.status` should be `connection_info_required`.
- `equipment_result.failure_code` should be `PYAUTOGUI_BRIDGE_URL_REQUIRED`.
- Live GUI should show the blocked step and required env/config fields.

============================================================
11. Live GUI Event Expectations
============================================================

Tool-level progress should be streamed through the existing `AgentContext.on_tool_event` callback where possible.

Recommended event steps:

- `PRECHECK`
- `CONNECT`
- `HEALTH`
- `VALIDATE_SEQUENCE`
- `EXECUTE_STEP`
- `SCREENSHOT`
- `DONE`

GUI display should show:

- Which Windows bridge URL is targeted, masked to host/port only.
- Whether live execution is blocked or enabled.
- Current action name.
- Screenshot preview when an artifact exists.
- Final step trace.

GUI display should not show:

- Raw token values.
- Credentials typed into GUI.
- Full secret-bearing payloads.

============================================================
12. Safety And Recovery Rules
============================================================

Hard safety rules:

- Fail closed in live mode.
- Keep PyAutoGUI fail-safe enabled.
- Require bounded action count.
- Require bounded wait time.
- Require coordinate bounds checks.
- Require token auth for any real internal-network bridge.
- Require explicit live enablement in config.
- Log every live action.

Recovery behavior:

- If `/health` fails, stop before executing sequence.
- If an action fails, stop remaining actions unless `continue_on_failure` is explicitly enabled for that action.
- If PyAutoGUI raises fail-safe, return `PYAUTOGUI_FAILSAFE_TRIGGERED`.
- If PyAutoGUI is not installed, return `PYAUTOGUI_NOT_INSTALLED` with the Windows install command.
- If a named macro is missing, return `PYAUTOGUI_PROGRAM_NOT_FOUND`.
- If screen size changes mid-run, revalidate coordinates.
- If screenshot or image-location is unavailable, return a soft failure for observation-only actions and a hard failure for click-dependent actions.

============================================================
13. Phase 1 Acceptance Criteria
============================================================

Documentation acceptance:

- This guideline exists under `docs/hardware`.
- Runtime baseline docs mention the new equipment bridge after implementation.

Implementation acceptance, later:

- `pytest` passes.
- Test mode returns deterministic simulated PyAutoGUI bridge results.
- Live mode without bridge URL fails with `PYAUTOGUI_BRIDGE_URL_REQUIRED`.
- Live mode with `allow_live_execute: false` fails with `PYAUTOGUI_LIVE_EXECUTION_BLOCKED`.
- A Windows bridge without PyAutoGUI installed still responds to `/health` and returns `PYAUTOGUI_NOT_INSTALLED` for `program1`.
- `program_id=program1` executes only the bounded demo mouse movement and returns `program_log: "program1 completed"` after PyAutoGUI is installed.
- Unknown macro program names fail with `PYAUTOGUI_PROGRAM_NOT_FOUND`.
- Unknown action fails before any live HTTP call.
- `equipment_agent` still returns `equipment_result` and `protocol_note`.
- Existing UTM/mock tests continue to pass.
- Live GUI can show tool progress for Equipment Agent without adding a new top-level stage.

============================================================
14. Recommended Phase 1 Implementation Order
============================================================

1. Add simulator/live bridge client in `device_bridges/windows_pyautogui_bridge.py`.
2. Add MCP tool registration in `mcp_tools/equipment_tools.py`.
3. Add `devices.equipment` config.
4. Register equipment tools from `app/bootstrap.py`.
5. Update `agents/equipment_agent.py` to call `equipment.pyautogui.run`.
6. Add unit tests for bridge, tools, and agent output compatibility.
7. Add optional Windows bridge server helper under `install/`.
8. Update `docs/runtime/agent_program_baseline.md` and `docs/README.md`.

============================================================
15. Open Design Decisions
============================================================

These should be decided before live implementation:

- Whether screenshots should be transferred as files, base64 payloads, or metadata-only.
- Whether Windows bridge server should use stdlib HTTP server, FastAPI, or Flask.
- Whether bridge config should be stored only in env/config or also in `memory/windows_pyautogui_connection.json`.
- Whether test workflow should include an explicit bench-test prompt for real Windows connection checks.
- Which GUI applications on the Windows PC are valid automation targets.
- Which hotkeys and write-text patterns are allowed for each target application.

Default recommendation:

- Start with stdlib HTTP or FastAPI, token header, JSON only, screenshots saved as files/metadata.
- Keep test virtual by default.
- Enable real Windows bridge only by explicit config.

============================================================
17. 2026-05-29 UTM Visual-Control/Data-Handoff Runtime Update
============================================================

The Equipment stage now separates setup/demo macros from real UTM experiment protocols.

Runtime rules:

- `program1` is only a connectivity demo. It can prove that the Windows bridge and PyAutoGUI can execute a bounded action, but it must not produce `ready_for_analysis`.
- `utm_compression_start_v1` is the default Equipment Agent protocol when no explicit program is selected for the experiment stage.
- A Lab Equipment handoff is valid only when `screen_started`, `physical_motion_started`, `save_completed`, `data_file_created`, and `data_parse_probe_ok` are all true.
- In test mode, the bridge writes a deterministic synthetic UTM CSV under `artifacts/equipment/<run_id>/utm/` so Analysis Agent reads the same file-path contract used by live mode.
- In live mode, the Windows bridge should return `output_artifacts[]`; the Linux bridge client pulls `/artifacts/{artifact_id}` and stores the file locally before setting `result_file` / `utm_csv_path`.
- `equipment_report.v1`, `utm_data_ready.v1`, `handoff_packet`, `decisions`, `metrics`, and `evidence_refs` are emitted by `LabEquipmentAgent`.

Current required output keys:

```json
{
  "equipment_result": {"status": "verified_complete", "result_file": "...csv", "utm_csv_path": "...csv"},
  "equipment_report": {"schema": "equipment_report.v1"},
  "utm_data_ready": {"schema": "utm_data_ready.v1", "status": "ready"},
  "equipment_handoff": {"schema": "utm_data_ready.v1", "status": "ready_for_analysis"}
}
```

Failure handling:

- Demo or non-UTM macro in the Equipment stage returns `UTM_PROTOCOL_REQUIRED` and blocks Analysis handoff.
- Missing exported file returns `UTM_EXPORT_FILE_MISSING`.
- CSV missing required `time_s`, `displacement_mm`, or `force_N` columns returns `UTM_DATA_PARSE_FAILED`.
- Live mode without physical motion evidence must route toward Guardian/recovery instead of Analysis.


Additional 2026-05-29 live bridge gate update:

- The Windows helper no longer treats live UTM as successful by generating a CSV automatically.
- Live success requires an exported CSV from `WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR`, a stable file-size check, and a parse probe for `time_s`, `displacement_mm`, and `force_N`.
- Synthetic CSV generation is allowed only when `WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM=1` or request payload `simulate_utm_protocol=true` is explicitly used for bench/demo testing.
- `equipment_report.v1` and `utm_data_ready.v1` now include `vision_requests` for `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete` so the Vision Agent cross-check requirement is explicit in the handoff evidence.
- The Linux bridge client treats live statuses `verified_complete`, `data_ready`, and `exported_on_windows` as successful statuses before pulling artifacts.
- `configs/devices.yaml` uses `request_timeout_sec: 60` for the Windows bridge so export-folder watch and artifact pull do not time out before the helper returns.
- Live UTM helper runs capture `screen_png` evidence artifacts for `before_start` and `after_complete` when PyAutoGUI screenshots are available.
- In live mode, `LabEquipmentAgent` now requires Vision cross-check evidence for `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete`; otherwise the handoff blocks with `VISION_UTM_*_REQUIRED` and `UTM_NO_MOTION_AFTER_START`.
- The Windows helper executes registered `sequence[]` steps when locators or coordinates are configured. Missing locators become warnings by default, or hard blocks when screen assertions are required.
- Runtime ToolRegistry exposes `vision.equipment_cross_check`; Equipment Agent calls it before UTM protocol execution when a UTM program is planned and merges returned `equipment_vision_check_result` objects into the same `equipment_report.v1` gate.
- Live GUI Equipment messages and report payloads include `vision_cross_checks` so operators can see whether the physical cross-check, not just the Windows macro, passed.
- UTM locator/export profiles are config-driven: `configs/devices.yaml` stores default image locators for `ready_state`, `start_button`, `running_state`, and `complete_state`, plus export glob and file stability parameters. The Windows Equipment GUI can override locators with JSON for calibration tests.

Additional 2026-05-29 locator calibration update:

- Runtime ToolRegistry now exposes `equipment.pyautogui.screenshot`, `equipment.pyautogui.list_locators`, and `equipment.pyautogui.capture_locator` in addition to health/program/run/connection tools.
- The Windows helper supports `POST /screenshot`, `GET /locators`, and `POST /locators/capture` for UTM UI calibration.
- `/equipment/windows` includes `Capture Screen`, `List Locators`, and `Capture Locator` controls. Locator capture writes a Windows-side PNG and merges the returned `{image_path, confidence, region, target}` object into the UTM locator JSON override.
- Locator calibration is a setup action, not proof of experiment completion. Lab Equipment still requires UTM screen checks, Vision physical cross-checks, exported CSV artifact pull, and parse probe before `ready_for_analysis`.
- Screenshot and locator artifacts pulled from the Windows bridge are stored separately from UTM CSV artifacts so report/backend traces can distinguish calibration evidence from experiment data.

Additional 2026-05-29 Guardian alert contract update:

- When Lab Equipment verification blocks Analysis handoff, `LabEquipmentAgent` now emits `hardware_alert.v1` and `incident_record.v1` alongside `equipment_report.v1` and `utm_data_ready.v1`.
- Failure cases such as `UTM_PROTOCOL_REQUIRED`, `PYAUTOGUI_*`, `UTM_EXPORT_FILE_MISSING`, `UTM_DATA_PARSE_FAILED`, `UTM_NO_MOTION_AFTER_START`, and `VISION_UTM_*_REQUIRED` are classified into Guardian-readable `device_class` and `component` fields.
- Runtime/controller state stores `hardware_alerts` into `run_metadata.hardware_alerts`, persists `incident_record.v1` objects into `run_metadata.incident_records`, appends those incidents to `guardian_events.jsonl`, and updates `device_health[device_class]` with `<severity>:<failure_code>` so `GuardianAgent` and Live GUI can stop/recover from the same evidence.
- A blocked Equipment handoff is therefore no longer only a local agent failure. It becomes a Guardian-visible hardware/quality incident with `guardian_decision.v1`, `guardian_contract.v1`, and corrective-action text.
- Verified UTM handoff must not emit hardware alerts. This is covered by the test-mode closed-loop regression.

Additional 2026-05-29 persistent UTM profile update:

- `/equipment/windows` now separates one-shot UTM Protocol Test parameters from the persistent UTM profile used by the autonomous Equipment Agent loop.
- `Load UTM Profile` reads the effective profile from `memory/equipment_utm_profile.json` or falls back to the registered program defaults in `configs/devices.yaml`.
- `Save UTM Profile` writes `program_id`, `export_glob`, `artifact_timeout_s`, `stable_for_sec`, `require_screen_assertions`, `simulate_utm_protocol`, and locator overrides to `memory/equipment_utm_profile.json`.
- `device_bridges/windows_pyautogui_bridge.py` merges the saved profile into `registered_programs.utm_compression_start_v1` during config load, so GUI calibration, CUI tool calls, and Lab Equipment Agent autonomous runs use the same locator/export settings.
- The persistent profile is still setup/calibration data. It does not by itself satisfy the live handoff. Live UTM completion still requires screen checks, Vision physical cross-checks, exported CSV artifact pull, parse probe, and Guardian-visible failure reporting when any gate fails.

Additional 2026-05-29 Analysis handoff update:

- `AnalysisAgent` now reads UTM CSV file references from the full Equipment handoff structure, not only from `equipment_result.result_file`.
- Supported local file fields include `equipment_result.result_file`, `equipment_result.utm_csv_path`, `equipment_report.data_acquisition.linux_path`, `utm_data_ready.result_file`, `equipment_handoff.result_file`, and pulled artifact `local_path` / `path` values.
- This closes the Phase 6 handoff requirement: Lab Equipment can pass `equipment_report.v1` / `utm_data_ready.v1` as the authoritative packet while Analysis still resolves the Linux-local CSV for preprocessing.
- Windows-only paths remain evidence metadata. Analysis requires a Linux-local pulled artifact path before live processing can proceed.

Additional 2026-05-29 UTM control profile trace update:

- `equipment.pyautogui.run` responses now include non-secret `control_profile` metadata for UTM programs.
- The profile trace records `program_id`, `profile_memory_path`, whether the memory profile was applied, export glob, timeout/stable-file settings, screen-assertion mode, simulation flag, and locator count/names.
- `LabEquipmentAgent` copies this metadata into `equipment_report.control_plan.profile`, so report viewers and backend traces can prove which UTM locator/export profile was used for a run.
- The trace is intentionally metadata-only. It does not expose bridge tokens or other connection secrets.

Additional 2026-05-29 BO/Knowledge handoff update:

- `AnalysisAgent` now emits `bo_observation.v1`, `experiment_evaluation.v1`, and `analysis_knowledge_payload.v1` after UTM preprocessing.
- `bo_observation.v1` separates observed UTM metrics, CAE simulation metrics, data quality, parameters, artifact refs, failure tags, and source metadata for BO/MBO consumption.
- `experiment_evaluation.v1` is emitted as a top-level agent result so runtime/controller state appends it to `state.experiment_evaluations`; BO can then use the actual UTM observation as prior evidence.
- `KnowledgeAgent` persists raw artifact refs, observed metrics, and failure tags in `MemoryRecord` so later retrieval can distinguish validated UTM data, synthetic test data, and curve-quality issues.


Additional 2026-05-29 legacy/direct UTM fail-closed update:

- `utm.run_protocol` is no longer a blind success stub. It now follows the same 5번 handoff principle: no readable UTM CSV means no Analysis handoff.
- In `test` mode, `utm.run_protocol` creates a deterministic local CSV under `artifacts/equipment/<run_id>/utm/`, probes the required columns (`time_s`, `displacement_mm`, `force_N`), and returns `status=verified_complete` only when the file is parseable.
- In `live` mode, the legacy/direct UTM path returns `failure_code=UTM_DIRECT_BACKEND_NOT_CONFIGURED` unless an explicit direct backend/file path is provided. It does not fall back to synthetic data.
- `LabEquipmentAgent` now wraps legacy/direct UTM results into the same `equipment_report.v1`, `utm_data_ready.v1`, `equipment_handoff`, metrics, evidence refs, hardware alerts, and incident records used by the Windows PyAutoGUI path.
- This keeps the Windows PyAutoGUI bridge as the primary live UTM control route while preserving `utm.run_protocol` as a safe direct-backend extension point.


Additional 2026-05-29 explicit direct UTM backend payload update:

- `LabEquipmentAgent` now reads explicit direct UTM settings from `current_experiment_spec.direct_utm`, `current_experiment_spec.utm`, `current_experiment_spec.lab_equipment`, or `current_experiment_spec.equipment` when the Windows PyAutoGUI tools are unavailable and the legacy/direct `utm.run_protocol` path is used.
- Supported direct-backend keys are `profile`, `program_id`, `result_file`, `utm_csv_path`, `direct_backend_configured`, and `allow_live_direct_backend`; `result_path`, `csv_path`, and `utm_result_file` are treated as aliases for `result_file`.
- A live direct UTM run can reach `ready_for_analysis` only when the explicit CSV file exists, passes the parse probe, and live Vision cross-check evidence (`utm_pre_start`, `utm_motion_confirm`, `utm_test_complete`) is present.
- This provides a real extension point for vendor API / file-watch / PyVISA style UTM integrations while preserving the rule that synthetic live data is never accepted.


Additional 2026-05-29 passive UTM readiness console update:

- `/api/equipment/windows/readiness` now exposes passive UTM readiness gates without calling live hardware endpoints.
- The readiness contract reports saved bridge selection, token availability, registered UTM program presence, export glob configuration, locator count, required locator names, missing required locator names, screen-assertion mode, and simulation flag.
- `/api/equipment/windows/config` includes the same `utm_readiness` payload so newly opened Equipment GUI windows reflect the current backend state immediately.
- `/equipment/windows` now displays a UTM readiness card and `Check Readiness` button beside the UTM profile controls. This helps operators see why the setup is blocked or warning before attempting a live UTM protocol.
- Readiness is not proof of a physical UTM run; it is a setup gate. The actual `ready_for_analysis` handoff still requires screen checks, Vision physical cross-checks, exported CSV pull, parse probe, and Guardian-visible failure reporting.


Additional 2026-05-30 packaged Windows server update:

- The canonical Windows distribution is `Pyautogui_server_for_window/`.
  `install/windows_pyautogui_bridge_server.py` remains a byte-identical compatibility copy and must not be deployed without the package assets.
- The packaged server is no longer limited to `program1`; it exposes the same UTM-oriented registered programs needed by the autonomous Equipment Agent: `utm_compression_start_v1`, `utm_export_csv_v1`, `utm_manual_save_csv_v1`, and `utm_stop_or_abort_v1`.
- The packaged server supports artifact and calibration endpoints expected by the Linux bridge client: `/screenshot`, `/locators`, `/locators/capture`, `/artifacts`, and `/artifacts/<artifact_id>`.
- The packaged Web GUI includes a bench-only UTM simulation trigger so operators can verify the endpoint/artifact contract before using a real UTM export folder.
- The same fail-closed rule applies: real live UTM success requires a stable parseable CSV export with `time_s`, `displacement_mm`, and `force_N`; synthetic data is accepted only when explicitly requested for bench/demo checks.


Additional 2026-05-30 Live GUI Equipment report surface update:

- Live GUI and `/api/agents/equipment/report` now expose Lab Equipment as `Lab Equipment / UTM Visual Control` instead of a generic bridge-command card.
- Backend role-specific payload includes `control_trace`, `visual_assertion`, `physical_verification`, `data_ledger`, and `handoff_gate` derived from `equipment_report.v1`, `equipment_result`, `utm_data_ready.v1`, and `equipment_handoff`.
- Frontend `planning.js` renders an expanded Equipment detail report with Bridge / Protocol Profile, Preconditions, Screen-State Assertions, Vision Physical Cross-Checks, UTM Data Ledger, Handoff Gate / Blocking Reasons, and Evidence Refs.
- The report is intentionally human-readable: operator-facing rows show program/profile, screen transition counts, Vision motion/alignment/safe-access status, Windows and Linux CSV paths, checksum, row/column parse probe, and the final Analysis handoff gate. Raw JSON remains available in backend trace.
- This closes the software-side report visibility gap for Improvement 05; physical completion still requires real UTM workstation locator capture, export path tuning, Vision evidence, and an operator-approved live run.

Additional 2026-05-30 live UTM preflight update:

- `/api/equipment/windows/live-preflight` performs an operator-confirmed, non-actuating live bridge check before a real UTM protocol run.
- The preflight calls only safe read/calibration endpoints: `/health`, `/programs`, `/locators`, and optionally `/screenshot`. It never calls `/execute` and therefore must not start UTM motion or click the UTM start button.
- `/equipment/windows` now includes `Live Preflight` and optional `Capture screen` controls beside the persistent UTM profile/readiness controls.
- The returned `equipment.pyautogui.live_preflight` payload records `non_actuating=true`, `touched_endpoints`, passive readiness, live bridge health, live program registry, locator-library status, optional screenshot evidence refs, checks, blockers, and warnings.
- This closes the setup-side active verification gap: operators can confirm that the selected Windows workstation and saved UTM profile are reachable before issuing the real UTM protocol. It is still not proof of physical experiment completion; Analysis handoff still requires the UTM CSV artifact, parse probe, screen checks, Vision physical evidence, and Guardian-visible failure reporting.

Additional 2026-05-30 manual save/export fallback update:

- The Windows helper no longer only watches for auto-save output. After `utm_compression_start_v1` runs, if no stable parseable CSV is found, it automatically attempts the registered `utm_manual_save_csv_v1` fallback unless payload `manual_save_required_if_no_artifact=false` is provided.
- The fallback creates the run export directory, sends `Ctrl+S`, types `<WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR>/<run_id>/<specimen_id>.csv`, presses Enter, and then reruns the same stable-file/checksum/parse-probe gate.
- Successful fallback runs report `data_acquisition.save_method=manual_save_dialog` and keep `save_attempted_by_agent=true`; failed fallback runs remain blocked and do not synthesize live data.
- This closes the Phase 5 save-responsibility gap for software behavior. Physical completion still requires the real UTM software save dialog/export behavior to be verified on the Windows workstation.

Additional 2026-05-30 Linux artifact pull/data ledger update:

- After the Windows server reports a pullable `utm_csv` artifact, the Linux bridge must retrieve it through `GET /artifacts/<artifact_id>` before Analysis handoff.
- A successful pull updates `result_file`, `utm_csv_path`, `data_integrity.sha256`, and `data_acquisition.linux_path` / `data_acquisition.local_path`.
- `data_acquisition.status` becomes `pulled_to_linux` after the local file is present and parse-probe metadata has been copied into the ledger.
- Windows-only paths remain provenance metadata. Analysis must use the Linux-local CSV path from `data_acquisition.linux_path`, `data_acquisition.local_path`, `result_file`, or `utm_csv_path`.
- `LabEquipmentAgent` fills missing ledger fields from the local parse probe before emitting `equipment_report.v1`, `utm_data_ready.v1`, and `equipment_handoff`.
- This prevents a live run from appearing ready for Analysis when the Windows export existed but the Linux side never received a readable CSV.

Additional 2026-05-30 live screen-assertion execution update:

- `WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS=1` no longer blocks before the registered protocol runs.
- Required screen assertions are now enforced inside the Windows registered sequence itself through `assert_visible`, `click`, and `wait_until` locator steps.
- If the configured locator images are found, the live UTM protocol may continue to the export/save gate. If a required locator is missing or PyAutoGUI image matching fails, the run blocks with `UI_LOCATOR_NOT_FOUND`.
- This matches the 5번 rule that the Windows bridge must prove the GUI state transition directly instead of trusting a caller-supplied `screen_assertions_verified` flag.

Additional 2026-05-30 screen-state evidence artifact update:

- The Windows UTM protocol now captures screen evidence at the actual `wait_until` transition points.
- When `running_state` is found, the bridge stores an `after_start` screenshot artifact and links it into `screen_checks[].screenshot_artifact`.
- When `complete_state` is found, the bridge stores an `after_complete` screenshot artifact and links it into `screen_checks[].screenshot_artifact`.
- The `after_start` screen check is no longer a bare `ok=true` placeholder. It must reference a concrete screen artifact when the state is observed.
- This improves the Lab Equipment report's Screen State section so operators can distinguish ready, running, and complete evidence instead of only seeing command success.

Additional 2026-05-30 failure evidence retention update:

- Blocked UTM runs now retain screen evidence instead of returning only an error string.
- If the registered screen-control sequence fails, the bridge captures a `failure` screenshot and returns `output_artifacts` plus `screen_checks` with `before_start` and `failure` checkpoints.
- If export/save fails after the screen sequence, the response also preserves already observed `after_start` / `after_complete` evidence and adds a `failure` screenshot.
- This supports the 5번 recovery rule: UI mismatch, no-motion, save dialog, and data-timeout failures must be debuggable from the report and available for Guardian/Knowledge failure memory.

Additional 2026-05-30 Lab Equipment failure-memory handoff update:

- `LabEquipmentAgent` now promotes Windows bridge `output_artifacts` into `equipment_report.artifact_records`, `artifact_refs`, `screen_evidence_refs`, and `data_evidence_refs`.
- `utm_data_ready.evidence_refs` now includes non-data failure evidence such as pulled `screen_png` artifacts in addition to the UTM CSV when present.
- Guardian `hardware_alert.guardian_contract.artifact_refs` and `incident_record.artifact_refs` now receive the same evidence refs, so blocked UTM runs can be reviewed from saved screen artifacts.
- `equipment_report.failure_retry_table` and `equipment_report.recovery` summarize blocked/warning steps, manual save fallback usage, operator intervention need, and recommended recovery action.
- Analysis still uses only `result_file` / `utm_csv_path` / data evidence for curve preprocessing. Screen evidence is for recovery, Guardian, and Knowledge failure memory.

Additional 2026-05-30 Live GUI evidence/recovery surface update:

- The Equipment selected-agent report now renders `Artifact / Evidence Ledger` and `Failure / Recovery` sections.
- Operators can inspect screen evidence refs, data evidence refs, normalized artifact records, fallback macro usage, retry count, and recommended recovery action directly in Live GUI.
- `/api/agents/equipment/report` exposes the same content under `role_specific.artifact_ledger` and `role_specific.failure_recovery`.
- This completes the software-side visibility path for 5번 recovery reporting; physical completion still requires real UTM workstation evidence.

Additional 2026-05-30 Windows bridge focus/operator GUI update:

- The packaged Windows bridge Web GUI is now an operator-oriented UTM setup panel rather than a JSON-only test page.
- The page exposes connection health, program registry, screenshot capture, locator capture, UTM simulation, guarded live UTM execution, result JSON, step trace, and artifact ledger.
- `Run Live UTM` in the Windows page requires an explicit local physical-safety checkbox. This is not a replacement for Linux-side workflow gates; it prevents accidental browser clicks during setup.
- `focus_window` now attempts to activate the real UTM software window using `target_window`, `target_window_regex`, `window_title`, `title`, or `target_app` before screen assertions and clicks.
- `require_window_focus=true` or action-level `required=true` converts a missing target window into `PYAUTOGUI_WINDOW_NOT_FOUND` instead of a warning. This reduces the risk of PyAutoGUI clicking the wrong foreground application.

Additional 2026-05-30 live evidence audit gate update:

- Live Windows PyAutoGUI UTM handoff now includes `live_evidence_audit` in `equipment_report.v1`, `utm_data_ready.v1`, and `equipment_handoff`.
- For `mode=live` with `bridge=windows_pyautogui`, Analysis handoff requires all three screen-state evidence checkpoints: `before_start`, `after_start`, and `after_complete`. Each checkpoint must have `ok=true` and a non-empty `screenshot_artifact`.
- Windows export completion is no longer treated as Linux data readiness. `data_acquisition.status=exported_on_windows` remains blocked until the Linux bridge pulls the CSV and records `status=pulled_to_linux` with a Linux-local path and parse-probe success.
- Vision cross-check success must carry concrete evidence frame IDs. If Vision returns logical success without frame evidence, the handoff blocks with `UTM_VISION_EVIDENCE_FRAMES_REQUIRED`.
- New cross-check keys may appear for live Windows UTM: `screen_evidence_complete`, `linux_artifact_pulled`, and `vision_evidence_complete`.
- Live GUI exposes the same audit under the Equipment detail report as `Live Evidence Audit`, so operators can see whether the block is due to missing screen evidence, missing Linux pull, or missing Vision frame evidence.

Additional 2026-05-30 Windows Equipment post-run evidence audit update:

- `/api/equipment/windows/evidence-audit` now provides a passive post-run audit from current runtime metadata. It does not call the Windows bridge or touch hardware.
- `/api/equipment/windows/config` includes `utm_evidence_audit`, so newly opened Windows Equipment GUI windows can show both setup readiness and last-run evidence status.
- `/equipment/windows` now includes `Audit Last Run Evidence`, rendering the same handoff gates used by LabEquipmentAgent: screen evidence completeness, Linux artifact pull, Vision frame evidence, parse probe, and blocking reasons.
- This separates three operator questions in the Equipment workspace: setup readiness before a run, live preflight before motion, and post-run evidence audit before Analysis handoff.

Additional 2026-05-30 setup-GUI UTM protocol audit update:

- `/api/equipment/windows/run-program` now stores the latest setup-GUI execution result in runtime metadata as `last_windows_equipment_run_result`.
- UTM setup tests are additionally stored as `last_windows_utm_protocol_result`.
- `/api/equipment/windows/evidence-audit` can audit that raw UTM setup-test result even when the full `equipment_report.v1` package has not been produced by LabEquipmentAgent.
- Raw setup-test audit may show screen evidence and Linux CSV pull as passing, but it still blocks Analysis handoff with `UTM_VISION_EVIDENCE_FRAMES_REQUIRED` until the full LabEquipmentAgent stage adds Vision frame evidence.

Additional 2026-05-30 bridge request-audit evidence update:

- `equipment.pyautogui.request_log` is now a first-class bridge tool. In simulator mode it reads `artifacts/equipment/bridge_requests.jsonl`; in live mode it calls the Windows bridge `GET /request-log` endpoint.
- `equipment.pyautogui.health` exposes the bridge artifact context: artifact root, request audit log path, locator root, and UTM export root.
- After a Windows PyAutoGUI run, `LabEquipmentAgent` fetches the request audit log when the tool is available and preserves it in `equipment_report.bridge.request_log_path`, `request_log_event_count`, and `request_log_recent_paths`.
- `equipment_report.live_evidence_audit.request_audit_log`, `utm_data_ready.bridge_request_log_ref`, and `equipment_handoff.bridge_request_log_ref` carry the same provenance reference into the Analysis handoff path.
- The request audit log is provenance only. It proves bridge API/auth traffic and helps debug missing Windows-side actions, but it does not replace screen evidence, Vision physical cross-checks, Linux artifact pull, or CSV parse probes.

============================================================
18. Linux Equipment GUI Request-Audit Panel
============================================================

The Linux-side Windows Equipment workspace (`/equipment/windows`) now exposes a dedicated Bridge Request Audit card.

Purpose:

- Let the operator inspect whether the selected Windows bridge received authenticated API requests.
- Provide evidence that Linux GUI/API calls reached the Windows bridge without exposing token values.
- Keep request audit as provenance, not as a hard equipment handoff blocker by itself.

Backend endpoints:

- `GET /api/equipment/windows/config`
  - Returns saved connection, UTM profile/readiness, last evidence audit, and a simulator-safe `request_audit` preview.
- `POST /api/equipment/windows/request-log`
  - Payload: `{"runtime_mode": "live", "confirm_live": true}` for live Windows bridge review.
  - Non-actuating: this endpoint reads request log state only and must not start UTM motion.
  - Sanitization rule: fields containing token values are removed; boolean metadata such as `token_header_present` and `token_auth_enabled` may remain.
- `POST /api/equipment/windows/live-preflight`
  - Includes `include_request_log=true` by default.
  - Touches `/health`, `/programs`, `/locators` when enabled, `/request-log`, and optional `/screenshot`.
  - Does not call `/execute`.

GUI behavior:

- `Load Bridge Request Log` asks for explicit confirmation before contacting the live bridge.
- `Run Live Preflight` loads request-audit state together with health/program/locator checks.
- `Audit Last Run Evidence` displays `request_audit_log` when present in `equipment_report.live_evidence_audit` or `equipment_report.bridge`.
- The Linux `/equipment/windows` workspace exposes a seven-card UTM proof dashboard: `Windows Bridge`, `UTM Program`, `Vision Preconditions`, `Screen State`, `Physical Cross-check`, `Data Artifact`, and `Analysis Handoff`. These cards are updated by readiness, request-audit, evidence-audit, and proof-package verification results so the operator can see why a run is or is not Analysis-ready.
- `/api/equipment/windows/proof-package/verify` returns the same seven-gate `gate_summary`, so GUI, API, CUI, and later Guardian/Analysis handoff checks can use one explicit verification surface instead of inferring state from raw JSON fields.
- Current rule: for live Windows UTM handoff, request-audit evidence is a hard gate together with screen evidence, Linux CSV pull, Vision evidence, and parse probes. Missing/empty audit logs block Analysis handoff with `UTM_REQUEST_LOG_REQUIRED`; logs without `/execute` block with `UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED`.

Expected evidence payload:

```json
{
  "request_audit_log": {
    "ok": true,
    "path": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
    "event_count": 12,
    "recent_paths": ["/health", "/programs", "/execute"]
  }
}
```

Live validation still required:

- Run live preflight against the real Windows UTM PC.
- Confirm the Windows bridge `bridge_requests.jsonl` records `/health`, `/programs`, `/locators`, and `/execute` during the physical UTM run.
- Confirm token values are not written to the audit file.

Additional 2026-05-30 Windows-side GUI export-control update:

- The Windows bridge operator GUI now exposes UTM export controls for `export_glob`, `artifact_timeout_s`, `stable_for_sec`, and optional `expected_export_path`.
- These controls are included in `/execute` payloads from `Run UTM Simulation`, `Run Live UTM`, and `Fill UTM JSON`.
- This directly supports the 5번 data recovery rule: the bridge waits for a stable exported CSV and returns artifact metadata, while Linux still performs artifact pull and parse-probe before Analysis handoff.

Additional 2026-05-30 Linux-side Windows Equipment GUI parity update:

- The Linux Windows Equipment workspace (`/equipment/windows`) now mirrors the Windows-side UTM export controls used by the packaged bridge GUI.
- `Save UTM Profile` persists `expected_export_path`, `target_window` or `target_window_regex`, `require_window_focus`, and `manual_save_required_if_no_artifact` in addition to export glob, timeout, stable-file seconds, locators, screen assertions, and simulation mode.
- `Run UTM Protocol Test` sends the same fields to `/api/equipment/windows/run-program`, so setup-GUI tests and later autonomous Equipment Agent runs share the same profile semantics.
- `/api/equipment/windows/run-program` forwards these fields to `equipment.pyautogui.run` with `force_live_bridge=true` and `confirm_setup_gui_execute=true`; it does not rely on hidden frontend state.
- The Linux bridge client also merges the persisted profile into registered UTM programs before `/execute`, allowing GUI, CUI, and agent-loop paths to stay aligned.
- This update is still software-side validation. Real completion requires a live Windows UTM request log, focused UTM application window, captured screen-state artifacts, pulled Linux CSV artifact, parse probe, and Vision evidence before Analysis handoff.

Additional 2026-05-30 Windows UIA locator backend update:

- The Windows bridge helpers now support optional UIA/pywinauto locators in `assert_visible`, `wait_until`, and `click` actions. They also support optional OCR/text checks through `assert_text` and `wait_until_text` when `pytesseract` is available on the Windows PC or a test bridge provides OCR text.
- A locator is treated as UIA when `locator_backend`, `backend`, or `type` is `uia`/`pywinauto`/`windows_uia`, or when selector fields such as `auto_id`, `automation_id`, `title`, `name`, `control_type`, `class_name`, or `best_match` are present.
- Lookup order is UIA first, PyAutoGUI image matching second, and explicit coordinates last. This implements the 5번 priority rule that fixed coordinate clicks must be the last fallback.
- `pywinauto` remains optional on the Windows PC. If it is absent, the bridge reports `pywinauto unavailable` in the step detail and continues to image/coordinate fallback when available, or blocks when the locator/action is required.
- Example locator JSON for `/equipment/windows` or the Windows-side Advanced JSON panel:

```json
{
  "ready_state": {"locator_backend": "uia", "auto_id": "readyStatus", "control_type": "Text"},
  "start_button": {"locator_backend": "uia", "auto_id": "startButton", "control_type": "Button"}
}
```

Additional 2026-05-30 state-transition and popup-failure update:

- The Windows bridge helpers now distinguish screen locator failures from post-click state-transition failures.
- Required `assert_visible` failures continue to report `UI_LOCATOR_NOT_FOUND`.
- Required `wait_until running_state` after a successful click reports `CLICK_NO_STATE_CHANGE` with `timeout_failure_code=UTM_RUNNING_STATE_TIMEOUT`; this makes the report separate "clicked the start button" from "UTM software entered running state".
- Required `wait_until complete_state` reports `UTM_TEST_COMPLETE_TIMEOUT` when the completion state does not appear within the wait budget.
- Configured error/modal popup locators are watched before each action, during waits, and immediately after clicks. If a configured popup is detected, the sequence blocks with `UTM_ERROR_POPUP_DETECTED` and the outer UTM protocol preserves failure screen evidence.
- Popup locators can be provided through `error_popups`, `error_popup_locators`, `popup_locators`, or through the normal `locators` map using names such as `error_popup`, `error_dialog`, `warning_dialog`, `communication_error`, or `save_error`. UIA and image locators are both supported.

Additional 2026-05-30 required locator readiness gate update:

- Passive UTM readiness now checks the configured UTM protocol sequence rather than only counting locator entries.
- For the default UTM protocol, the required locator set is `ready_state`, `start_button`, `running_state`, and `complete_state`. If a saved profile overrides `sequence`, required names are inferred from `assert_visible`, `click`, and `wait_until` targets.
- When `require_screen_assertions=true` and any required locator is missing, `/api/equipment/windows/readiness` and live preflight block with `UTM_REQUIRED_LOCATORS_MISSING`.
- The readiness payload includes `gates.required_locator_names`, `gates.missing_required_locators`, and `gates.required_locators_complete`, and the `/equipment/windows` card displays the missing names directly.
- This prevents a live UTM setup from appearing ready when only one locator, such as `ready_state`, has been captured.

Additional 2026-05-30 Windows-side readiness GUI update:

- The Windows bridge operator GUI now has a `Readiness` quick action that calls `GET /readiness` on the Windows PC itself.
- `/readiness` is passive: it does not click the UTM software, does not start a test, and does not execute `/execute`.
- The endpoint checks PyAutoGUI availability, the registered `utm_compression_start_v1` sequence, and the required UTM locator set.
- Default required locator names are `ready_state`, `start_button`, `running_state`, and `complete_state`; if the registered sequence changes, required names are inferred from `assert_visible`, `click`, and `wait_until` targets.
- If any required locator PNG is missing under the Windows locator root for the selected program, the endpoint returns `UTM_REQUIRED_LOCATORS_MISSING` and the Windows GUI shows the missing names in the `UTM Readiness` card.
- This is the Windows-side counterpart to the Linux `/equipment/windows` readiness card, so an operator can calibrate locators directly on the Windows workstation before returning to the Linux autonomous loop.

Additional 2026-05-30 Equipment Agent request-audit handoff gate update:

- Live Windows UTM handoff now treats the Windows bridge request audit log as a required evidence gate, not just optional metadata.
- For `mode=live`, `program_id=utm_compression_start_v1`, and `bridge=windows_pyautogui`, Analysis handoff requires:
  - a request log path such as `bridge_requests.jsonl`,
  - at least one request-log event returned by `equipment.pyautogui.request_log` or the run result,
  - an `/execute` event in recent request paths.
- If the request log is absent or empty, the Equipment Agent blocks with `UTM_REQUEST_LOG_REQUIRED`.
- If request-log events are present but no `/execute` event is visible, the Equipment Agent blocks with `UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED`.
- The gate is reported under `equipment_report.live_evidence_audit.request_audit_log` and `equipment_report.cross_checks.request_audit_log_available`.
- This prevents a live stage from reaching Analysis when the Windows bridge cannot prove that the live UTM command path was audited.

Additional 2026-05-30 Linux Equipment GUI evidence-audit alignment:

- `/api/equipment/windows/evidence-audit` now applies the same strict request-audit rule as `LabEquipmentAgent`: a live Windows UTM run is not displayed as Analysis-ready unless `request_audit_log.ok=true` and `request_audit_log.execute_event_seen=true`.
- The `/equipment/windows` Evidence Audit card shows `request_log=execute-ok` only when recent request paths include `/execute`; a saved path or nonzero event count alone is not enough.
- Raw setup-test results stored as `last_windows_utm_protocol_result` are audited with the same rule, so GUI protocol tests and full agent-loop reports cannot diverge on request-log readiness.
- If the request log exists but does not show `/execute`, the GUI/API blocker remains `UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED`.

Additional 2026-05-30 Windows-side request audit GUI update:

- Both Windows bridge helper variants now show a `Request Audit` card directly on the Windows PC GUI.
- The card displays request event count, recent paths, and `/execute` detection instead of forcing the operator to inspect JSON manually.
- `/request-log` returns `recent_paths`, `execute_event_seen`, `execute_event_count`, and `last_execute_at`, matching the Linux-side evidence audit and Equipment Agent handoff gate.
- This improves operator usability but does not replace the physical proof requirements: screen evidence, Vision evidence, Linux CSV pull, parse probe, and Equipment -> Analysis handoff must still pass.

Additional 2026-05-30 request-log summary handoff compatibility update:

- `LabEquipmentAgent` now accepts the Windows bridge request-log summary fields directly: `recent_paths`, `execute_event_seen`, `execute_event_count`, and `last_execute_at`.
- This means the live request-audit handoff gate no longer depends on the bridge returning the full `events[]` list, as long as the summary proves `/execute`.
- The report carries these fields under `equipment_report.bridge` and `equipment_report.live_evidence_audit.request_audit_log`; the handoff packet also carries `bridge_request_log_execute_event_seen`.
- The rule is unchanged: a live Windows UTM handoff remains blocked unless `/execute` is proven by either recent paths or the explicit `execute_event_seen=true` summary.

Additional 2026-05-30 Equipment report safety-gate surface update:

- `/api/agents/equipment/report` now exposes `role_specific.safety_gate` for the Lab Equipment Agent report.
- The safety gate summarizes Guardian status, hardware-alert count, incident records, human-approval requirement, workflow blocking state, route hint, risk flags, and emergency-stop recommendation evidence.
- The Live GUI Equipment report now renders a dedicated `Safety Gate / Guardian` section between handoff blockers and live evidence audit.
- The same view also shows request-audit details from `live_evidence_audit.request_audit_log`, including `/execute` seen/count and last execute timestamp.

Additional 2026-05-30 Windows-side Live Proof Checklist GUI update:

- Both Windows bridge helper variants now include a `Live Proof Checklist` card in the local Windows Web GUI.
- The checklist combines latest `/health`, `/readiness`, `/request-log`, screen-check, and CSV/parse-probe state into operator-readable live proof items.
- The new `Refresh Evidence` button performs the non-actuating evidence refresh path: `/health` -> `/readiness` -> `/request-log`.
- The new `Auto-refresh request audit` checkbox polls `/request-log` every 5 seconds while the page is visible, without calling `/execute` or moving the UTM software.
- The Windows-side checklist is advisory only. The Linux Equipment Agent still enforces hard gates for request audit `/execute`, screen evidence, Linux CSV pull, parse probe, Vision frame evidence, and Guardian safety status before Analysis handoff.

Additional 2026-05-30 Linux-side evidence proof checklist update:

- `/api/equipment/windows/evidence-audit` now returns `proof_checklist` and `proof_ready` in addition to existing gates/blockers.
- The checklist mirrors the 5번 rule that a live UTM handoff needs explicit proof for Windows `/execute`, screen-state evidence, physical UTM motion, Linux artifact pull, CSV parse probe, and Vision frame evidence.
- The request-audit gate now honors Windows bridge summary fields: `execute_event_seen`, `execute_event_count`, and `last_execute_at`. This prevents false blocking when `/execute` is older than the recent-path tail but the Windows bridge reports the summarized execute evidence.
- `/equipment/windows` displays the checklist under the UTM evidence audit card. Operators can distinguish a missing screen artifact from missing Vision frames, missing Linux CSV pull, or missing request-log `/execute` proof before retrying the Lab Equipment stage.

Additional 2026-05-30 UTM pre-execution readiness gate update:

- `/api/equipment/windows/run-program` now performs a passive UTM readiness check before calling the Windows bridge `/execute` endpoint for any `program_id` beginning with `utm_`.
- For non-simulated UTM execution, the required gate is `ready_for_autonomous_profile=true`: selected bridge, token, registered UTM program, export glob, screen assertions enabled, all required locators complete, and simulation disabled.
- If the gate is incomplete, the endpoint returns `status=blocked`, `failure_code=UTM_PRE_EXECUTION_READINESS_BLOCKED`, `non_actuating=true`, and `bridge_not_called=true`; no Windows `/execute` request is sent.
- For explicit simulation requests, the less strict setup gate `ready_for_setup_test=true` is used because no real UTM motion is expected.
- The readiness check applies request-specific overrides such as `export_glob`, `sequence`, `locators`, `require_screen_assertions`, `target_window`, and `simulate_utm_protocol`, so GUI/CUI calls are validated against the exact payload that would be executed.


Additional 2026-05-30 Windows-side Safe Preflight GUI update:

- Both Windows bridge helper variants now reorganize the local Web GUI around non-actuating diagnostics before live control.
- The `Safe Preflight` control runs `/health -> /readiness -> /request-log` from the Windows page without calling `/execute`.
- `Run Live UTM` is now labeled `Preflight + Run Live UTM` and performs the same local preflight before sending a live `/execute` request. If PyAutoGUI is unavailable, readiness has not been checked, or required UTM locators are missing, the browser renders `LOCAL_LIVE_PREFLIGHT_BLOCKED` and does not send `/execute`.
- The page now separates `Safe Diagnostics` from allowlisted demo/registry actions, shows a persistent preflight banner, limits the local operator log length, and provides an `Artifact Preview` area for image artifacts returned through `GET /artifacts/<artifact_id>`.
- This frontend gate is an operator-usability layer only. The Linux `/api/equipment/windows/run-program` pre-execution readiness gate and Lab Equipment Agent live handoff gates remain authoritative for autonomous runs.


Additional 2026-05-30 Windows-side GUI behavior-test update:

- The Windows bridge GUI live-control contract is now tested with a Node-based DOM/fetch harness, not only static string checks.
- The test executes the embedded browser script, checks the `Preflight + Run Live UTM` click handler, and verifies that failed local preflight calls only `/health`, `/readiness`, and `/request-log` while sending no `/execute` request.
- The complementary pass-case test verifies that when PyAutoGUI and required locator readiness pass, the browser sends one live `POST /execute` payload for `utm_compression_start_v1` with `simulate_utm_protocol=false`.
- This strengthens the 5번 safety rule that local Windows GUI live execution must be guarded by non-actuating preflight before any physical UTM command can leave the browser.


Additional 2026-05-30 Windows UTM proof package update:

- `/api/equipment/windows/proof-package` now returns a consolidated, non-actuating proof package for the current Windows UTM run.
- The package combines passive readiness, last live preflight, last Windows UTM result, post-run evidence audit, proof checklist, request-log `/execute` evidence, screen evidence refs, Linux data refs, data acquisition status, row-count probe, Vision frame IDs, blockers, warnings, and next actions.
- `/equipment/windows` adds `Build Proof Package` beside `Audit Last Run Evidence`. It does not touch hardware; it only summarizes current runtime metadata and passive readiness.
- The proof package is considered `ready_for_analysis` only when the evidence audit is `ready_for_analysis` and every required proof checklist item is passing. Missing request-log `/execute`, missing screen refs, missing Linux CSV pull, missing parse probe, missing physical motion, or missing Vision frames keep the package `incomplete`.
- This gives the operator one JSON object to archive after the real UTM run, but it does not replace the physical evidence itself.

Additional 2026-05-30 Windows bridge GUI usability update:

- The Windows-side PyAutoGUI bridge Web GUI now has a compact sticky navigation bar for Overview, UTM Control, Evidence, Result JSON, and Operator Log so the operator can jump between setup, live control, and evidence without scrolling through the full page.
- The Connection card now shows the current bridge base URL and provides `Copy Linux Env`, which copies `WINDOWS_PYAUTOGUI_BRIDGE_URL` and `WINDOWS_PYAUTOGUI_BRIDGE_TOKEN` export commands for the Linux controller.
- The Live UTM section now includes an explicit `Live interlock` card. It stays blocked until Safe Preflight passes and the physical safety checkbox is enabled. This is a usability layer; backend live gates remain authoritative.
- The Live Proof Checklist now includes a gate-progress meter with the next missing proof item. This makes missing Health, locator readiness, live `/execute` request audit, screen evidence, CSV/parse probe, and safety confirmation visible before Linux handoff.
- `Refresh All` and the improved `Refresh Evidence` path run the non-actuating evidence refresh bundle: Health, Readiness, Request Log, and Artifacts. They do not call `/execute`.
- Operator Log now behaves like an event log with bounded scroll and newest entries appended at the bottom, matching the physical operator workflow.

Additional 2026-05-30 Windows UTM proof package persistence update:

- `/api/equipment/windows/proof-package` now persists the consolidated proof package as a run-local JSON artifact under `artifacts/equipment/<run_id>/utm/windows_utm_proof_package_<timestamp>.json`.
- The response includes `package_artifact` with `kind=windows_utm_proof_package`, `content_type=application/json`, `path`, `local_path`, `filename`, `ready_for_analysis`, `proof_ready`, and `missing_required_item_count`.
- `manifest.proof_package_path` points to the same JSON file, so GUI, CUI, future audit scripts, and Knowledge/Guardian tooling can review the exact proof package used for handoff review.
- The proof package artifact is non-actuating. It only records current runtime metadata, passive readiness, evidence audit state, request-log status, screen/data references, Vision frame IDs, blockers, warnings, and next actions.
- The Linux `/equipment/windows` GUI appends the saved proof package path to the UTM evidence detail after `Build Proof Package`.

Additional 2026-05-30 Analysis live handoff gate update:

- `AnalysisAgent` now defensively rechecks live Equipment handoff state when live Windows/UTM evidence is present.
- If a live UTM CSV path exists but `equipment_handoff.status != ready_for_analysis`, `utm_data_ready.status != ready`, or required live evidence cross-checks are not true, Analysis blocks instead of computing metrics from the CSV alone.
- This prevents a direct CSV path, failed setup-test result, or partially pulled artifact from bypassing the Lab Equipment Agent proof gate.
- The blocked analysis result includes `equipment_handoff_gate` with `status=blocked`, `failure_code`, blockers, and `required_for_handoff` so Guardian/GUI can report why Analysis did not proceed.

## Additional 2026-05-30: Windows Bridge GUI Proof Verification

The Windows PyAutoGUI bridge GUI now treats proof generation and proof verification as separate operator steps.

- Linux `/equipment/windows` shows a `Current Action` card so scan, preflight, run, audit, package, and verification results are visible without reading raw JSON first.
- `Build Proof Package` persists the current UTM evidence package under `artifacts/equipment/<run_id>/utm/`.
- `Verify Proof Package` calls `POST /api/equipment/windows/proof-package/verify` and re-checks the persisted package schema, request-log `/execute` evidence, screen evidence count, UTM data refs, Linux CSV signal-quality probe, and Vision frame ID availability.
- Verification status is rendered in `equipment-proof-verify-card`; Analysis handoff should only proceed when verification returns `status=verified`.
- The Windows-side local bridge page now includes a command banner above the overview panel. It shows the current endpoint, completion/blocker state, and keeps the operator log as the detailed trace.

Operational rule:
1. Run `Live Preflight` before live UTM motion.
2. Run the UTM protocol.
3. Run `Audit Last Run Evidence`.
4. Run `Build Proof Package`.
5. Run `Verify Proof Package` and resolve blockers before allowing Analysis to consume the UTM CSV.

## Additional 2026-05-30: Strict Proof Package Verification

`POST /api/equipment/windows/proof-package/verify` is now intentionally stricter than the proof package summary.

A package that claims `ready_for_analysis` is not accepted unless verification can prove all of the following from persisted or source-packet evidence:

- The proof package JSON artifact exists and has the expected schema.
- The Windows bridge request audit recorded a live `/execute` event.
- At least three UTM screen evidence refs are resolvable to Linux-local files and those files still exist.
- At least one UTM data evidence ref is resolvable to a Linux-local file and that file still exists.
- The UTM CSV signal-quality probe re-runs the same Linux Equipment Agent gate: exact `time_s`, `displacement_mm`, and `force_N` columns, at least two numeric rows, monotonic time, monotonic displacement in either direction, changing displacement, and nonzero/changing force.
- Vision evidence includes at least three frame IDs representing fixture/pre-start, motion, and complete/safe-access states.

This prevents a stale or summary-only proof package from being treated as Analysis-ready after screenshots or pulled CSV files have been deleted, when the package only contains opaque artifact IDs with no local file proof, or when a CSV has the right headers but all-zero/flat mechanical signals. Specific `UTM_DATA_*` failure codes are surfaced directly in the verification result and GUI.

## Additional 2026-05-30: Windows Bridge Operator HUD GUI

The Windows-side PyAutoGUI bridge Web GUI now includes a compact `Operator runtime status` HUD above the Overview panel.

- `Safety` summarizes Safe Preflight and proof-gate readiness.
- `Command` mirrors the current endpoint/action state so the operator does not need to read the raw JSON first.
- `Evidence` shows whether required UTM screen evidence is complete.
- `Data` shows whether the UTM CSV artifact and parse probe are available.
- `Next` names the next required operator action, such as resolving a preflight blocker, confirming live safety, or building the Linux proof package.

The UTM control panel also shows the required operational order: preflight, execute, screen evidence, CSV artifact, then Linux audit. Run ID and Specimen ID are explicitly identified as the values copied into the live `/execute` payload and request-audit context. This is a usability layer only; Linux-side Equipment Agent and Guardian gates remain authoritative.

## Additional 2026-05-30: Strict `/execute` Identity Audit

Live Windows UTM handoff now requires request-log identity proof, not only a visible `/execute` path.

- The Windows bridge writes non-secret `/execute` audit metadata into `bridge_requests.jsonl`: `run_id`, `sequence_id`, `specimen_id`, `program_id`, `payload_sha256`, simulation flag, screen-assertion flag, and result status.
- Token, password, secret, auth, and credential-like fields are stripped before hashing/writing audit metadata.
- `GET /request-log` summarizes `execute_run_ids`, `execute_sequence_ids`, `execute_specimen_ids`, `execute_program_ids`, payload/result event counts, and `last_execute_context`.
- `LabEquipmentAgent` blocks live Windows UTM handoff with `UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED` when the request log proves `/execute` but does not match the current run/sequence/specimen/program identity.
- `/api/equipment/windows/run-program` now sends `run_id` and `specimen_id` in the live `/execute` payload and immediately refreshes `/request-log` after execution so raw setup/live evidence audit can verify the identity.
- Proof package verification now includes `request_log_execute_identity`; a package with `/execute` but mismatched or missing run, sequence, specimen, or program identity is blocked before Analysis handoff.

### 2026-05-30 Windows bridge persisted artifact reindex update

The Windows PyAutoGUI bridge now treats artifact recovery as a restart-tolerant evidence path, not only an in-memory runtime list.

- `GET /artifacts` rebuilds metadata from the bridge artifact root and the UTM export root before returning the artifact list.
- Existing `.csv`, `.json`, `.txt`, and `.png` files are reindexed with `artifact_id`, `kind`, `sha256`, `size_bytes`, `content_type`, and CSV parse probes where applicable.
- `GET /artifacts/{artifact_id}` retries the rebuild path before returning `PYAUTOGUI_ARTIFACT_NOT_FOUND`.
- This supports the Improvement 05 data recovery gate: a Windows bridge restart should not make already exported UTM CSV/screen evidence invisible to the Linux Equipment Agent audit.
- Very large files over 100 MiB are skipped by the lightweight bridge indexer; large raw data should be handled by a dedicated file-share/direct backend.

### 2026-05-30 Linux-side local CSV parse validation update

The Linux Windows-bridge client no longer trusts the Windows bridge CSV metadata as the only parse proof.

- After `GET /artifacts/<artifact_id>` returns a UTM CSV, the Linux client writes the bytes locally and immediately parses the local file contents.
- The local probe verifies the required columns `time_s`, `displacement_mm`, and `force_N` and a positive data row count.
- The pull ledger now records `data_artifact_probe`, `data_artifact_parse_ok`, and per-artifact `parse_ok` values.
- If the CSV is pulled but fails the local parse probe, the file remains in `output_artifacts` and `data_acquisition.local_path` for debugging, but it is not promoted to `result_file` / `utm_csv_path` for Analysis handoff.
- Failed local parse sets `data_acquisition.status=pulled_to_linux_parse_failed` and `artifact_pull_status=pulled_parse_failed`.

This closes a data-integrity gap in Improvement 05: Windows export metadata can be useful provenance, but Analysis readiness must be proven from the Linux-local CSV bytes.

### 2026-05-30 Live save/export responsibility gate update

Live Windows UTM handoff now has an explicit save/export responsibility gate in addition to screen, physical, Linux-pull, parse-probe, and request-log gates.

- `equipment_report.live_evidence_audit.save_export` records `save_method`, `save_attempted_by_agent`, `save_confirmation_screen_ok`, Windows path, Linux path, and whether the save method is recognized.
- `equipment_report.cross_checks.save_export_responsibility_ok` is required for live Windows PyAutoGUI UTM handoff.
- Recognized save/export methods are `windows_export_watch`, `manual_save_dialog`, `export_menu`, `simulated_bridge_export`, `simulated_auto_export`, and `synthetic_test_export`.
- A live Windows run with a readable Linux CSV but no recognizable save/export responsibility evidence is blocked with `UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED`.
- This separates “a file exists” from “the Equipment Agent is accountable for how the UTM software saved/exported it,” matching Improvement 05's save responsibility requirement.

### 2026-05-30 Windows Bridge GUI Save/Export Proof Update

The Windows-side PyAutoGUI bridge GUI and the Linux `/equipment/windows` GUI now expose the same save/export responsibility gate used by the Lab Equipment Agent.

- The Windows bridge page `Live Proof Checklist` now includes `Save/Export Responsibility` as a first-class proof item, increasing the local live proof meter from 6 to 7 checks.
- The proof item is marked ready only when a recognized save/export method is present, the agent attempted or observed the save/export path, and a CSV parse/data artifact exists.
- The Windows UTM protocol response now sets `cross_checks.save_export_responsibility_ok=true` for verified exports and `false` for export failures.
- The Linux `/api/equipment/windows/evidence-audit` summary line now shows `save_export=ok|missing` alongside screen, Linux pull, request-log, parse, and Vision gates.
- The persisted Windows UTM proof package now carries `manifest.save_export`; `POST /api/equipment/windows/proof-package/verify` blocks with `UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED` if that proof is missing.

Operational rule: a readable CSV alone is not sufficient for Analysis handoff. The GUI and proof package must show how the UTM software saved/exported the file and whether the Equipment Agent is accountable for that step.

### 2026-05-30 Live GUI Equipment Report Save/Export Display Update

The Live GUI Equipment selected-agent report now exposes save/export responsibility in both backend report payloads and browser-rendered details.

- `/api/agents/equipment/report` now includes `data_ledger.save_attempted_by_agent`, `data_ledger.save_confirmation_screen_ok`, `data_ledger.save_export_responsibility_ok`, and `data_ledger.recognized_save_method`.
- The same report includes `handoff_gate.save_export_responsibility_ok`, so operator and downstream tools can see whether save/export accountability is part of the handoff decision.
- The Live GUI Equipment details panel now contains a dedicated `Save/Export Responsibility` section with save method, agent-attempt flag, confirmation status, recognized-method flag, Windows path, and Linux path.
- The browser-audit fixture and integration test now require `save_export_responsibility_ok` and visible `Save/Export` wording, preventing future regressions where a CSV path is shown but the save/export responsibility gate is hidden.

### 2026-05-30 Unified Save/Export Cross-Check for Test/Direct/Windows Paths

The save/export responsibility cross-check is now a shared Lab Equipment contract, not only a Windows GUI-only field.

- `equipment_report.cross_checks.save_export_responsibility_ok` is populated for Windows PyAutoGUI, test-mode synthetic UTM, and direct UTM backend paths.
- `utm_data_ready.save_export_responsibility_ok` and `equipment_handoff.save_export_responsibility_ok` carry the same decision into downstream Analysis/Guardian/Knowledge consumers.
- Direct UTM tool results now include `cross_checks.save_export_responsibility_ok`; live direct backend without configuration reports it as false, while verified direct/test exports report it as true.
- Recognized non-Windows save/export methods include `direct_backend_file` and `synthetic_test_direct_backend` in addition to Windows GUI export methods.

This keeps the Improvement 05 invariant consistent across Live, Test, Virtual, Windows-bridge, and direct-backend execution paths: the downstream handoff packet can always inspect whether data export responsibility was satisfied, instead of inferring it from CSV existence alone.

## Additional 2026-05-30: Windows Bridge Operator Console Update

The Windows-side PyAutoGUI bridge GUI has been updated for practical UTM operation.

- A top-bar proof pill mirrors the live proof checklist state so an operator can see whether evidence is complete without scrolling.
- A critical command rail groups the four common actions: Safe Preflight, Evidence Refresh, UTM Simulation, and Live UTM.
- UTM run fields are persisted in browser local storage to avoid losing Run ID, Specimen ID, target window selector, and export settings on refresh.
- The Copy Payload control exposes the exact `/execute` JSON for traceability and Linux/Windows parity checks.
- These UI controls do not weaken backend safety. Live handoff still requires request-log `/execute`, screen evidence, CSV artifact, parse probe, physical/Vision cross-checks, and save/export responsibility.

Safety detail for the Windows bridge operator console:

- Browser local storage is allowed for non-safety setup fields such as Run ID, Specimen ID, target window selector, export glob, artifact timeout, stable-file time, and expected export path.
- The physical safety confirmation checkbox is deliberately not persisted. A refreshed page or new browser session must require a fresh operator confirmation before Live UTM can send `/execute`.
- The command rail is tested as a proxy to the real handlers: Preflight must remain non-actuating, and Live UTM must still run local preflight before a live `/execute` request.

### 2026-05-30 Equipment Report Source-Contract Section Update

`equipment_report.v1` now carries the same operator-facing sections that `/api/agents/equipment/report` exposes in `role_specific`. This prevents Knowledge, Guardian, Live GUI, and future audit tooling from needing to reconstruct the Lab Equipment story differently.

New source-level sections:

- `control_trace`: bridge provider, connection state, program/sequence ID, macro version, locator backend, and sanitized tool result sequence.
- `visual_verification`: screen assertion count, required checkpoints, missing checkpoints, and screen evidence refs.
- `physical_verification`: Vision cross-check state, UTM motion/alignment/safety booleans, evidence frame IDs, and blocking reasons.
- `data_ledger`: save/export method, save responsibility decision, Windows/Linux paths, checksum, row count, columns, parse readiness, and data evidence refs.
- `artifact_ledger`: artifact records plus screen/data/evidence ref counts.
- `handoff_gate`: ready-for-analysis decision, required gate booleans, blocking reasons, and next agent.
- `safety_gate`: Guardian-facing block/allow state, hardware alert count, human-approval requirement, blocked commands, and emergency-stop evidence.

The same selected sections are also copied into `utm_data_ready.v1` and `equipment_handoff` so downstream Analysis, Guardian, and Knowledge consumers do not need to dereference the full report before checking the handoff gate.

### 2026-05-30 Linux Windows Equipment GUI Operator Rail Update

The Linux `/equipment/windows` management page now has a compact operator command rail above the detailed setup forms.

- `Scan`: runs the same token-verified discovery as the original scan button.
- `Readiness`: checks saved bridge selection, token state, UTM program registration, locator completeness, screen-assertion mode, and simulation mode.
- `Preflight`: runs the non-actuating live preflight path. It must not call `/execute`.
- `UTM Run`: proxies to the configured `Run UTM Protocol Test` handler and therefore uses the saved UTM profile, locator JSON, export path, and safety settings already shown in the detailed panel.
- `Evidence`: audits the latest screen evidence, Linux CSV pull, request log, parse probe, Vision evidence, and save/export responsibility before Analysis handoff.

The rail is a UI proxy only. Existing button IDs, backend API paths, and Equipment Agent MCP/tool contracts remain unchanged. The command banner mirrors the latest action status so a new operator can see the current blocker without scrolling through raw JSON first.

Browser audit evidence:

- Repeatable script: `tests/ui/windows_equipment_browser_audit.py`.
- The audit opens the Linux `/equipment/windows` workspace, injects passive readiness/evidence/proof payloads, and verifies the command rail, readiness card, evidence audit, proof checklist, request-log card, proof-package verification, Open Windows GUI, Live Preflight, and Stop/Abort controls are visible.
- The audit explicitly verifies blocked handoff reasons such as `UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED` and `UTM_DATA_NO_FORCE_SIGNAL` appear in the operator-facing UI.
- Latest local result: PASS at 1920px, `scrollWidth=1908`, `clientWidth=1908`, screenshot `artifacts/ui/windows_equipment_browser_audit.png` (`1920x994`).

Linux and Windows registered UTM protocols now expose the same safe public metadata to `list_programs`:

- `preconditions`
- `expected_screen_before`
- `sequence`
- `expected_screen_after`
- `save_policy`
- `output_artifacts`
- `safe_abort`

This lets the GUI and future LLM/tool-calling layer inspect the protocol contract without reading source code or leaking secrets. Connection tokens remain outside program metadata.

### 2026-05-30 UTM Stop/Abort Recovery Macro Gate

`utm_stop_or_abort_v1` is now treated as a recovery macro, not a normal UTM execution protocol.

- The Linux `/equipment/windows` GUI exposes `Run UTM Stop/Abort` and an `Abort` operator-rail card.
- The API still requires `confirm_execute=true` and uses the selected live Windows bridge; it does not silently fall back to simulator.
- Unlike `utm_compression_start_v1`, recovery macro dispatch does not require UTM locator readiness or full live preflight. This is intentional: a stop/abort command must remain callable when the UTM UI is partially stuck, missing locators, or in an unknown state.
- The response marks `recovery_macro=true` and records `pre_execution_readiness.status=bypassed_for_recovery_macro` so downstream Guardian/Knowledge code can distinguish emergency recovery from a verified test execution.
- Request-log audit is still collected after dispatch so the operator can prove that `/execute` reached the Windows bridge.

Operational rule: `utm_stop_or_abort_v1` is allowed to bypass setup-readiness gates only for recovery. It must not be interpreted as `ready_for_analysis`, `verified_complete`, or successful UTM data acquisition.

### 2026-05-30 Vision Freshness Gate for UTM Physical Cross-Check

Lab Equipment now treats Vision evidence freshness as part of the physical UTM gate.

- In live mode, `equipment_vision_check_results[]` and Vision signal-board entries must include `expires_at` in ISO-8601 format.
- If `expires_at` is missing, the check is not freshness-bounded and the live handoff blocks with `VISION_UTM_*_FRESHNESS_REQUIRED`.
- If `expires_at` is in the past, the signal/check is marked stale even when `ok=true` and confidence is high.
- Missing or stale UTM freshness blocks live Analysis handoff with explicit reasons such as `VISION_UTM_PRE_START_FRESHNESS_REQUIRED`, `VISION_UTM_PRE_START_STALE`, or `VISION_UTM_MOTION_CONFIRM_STALE`.
- The stale/fresh state is recorded in `equipment_report.vision_cross_checks.checks`, `equipment_report.physical_verification.blocking_reasons`, `utm_data_ready.warnings`, hardware alerts, and incident records.
- Test mode may still use deterministic simulated Vision checks, but live mode cannot use expired Vision state for fixture occupancy, robot-clearance, UTM motion, or completion proof.

Operational rule: a Vision frame or signal that was true earlier is not proof that the UTM fixture is safe now. Refresh Vision before retrying a blocked Equipment handoff.

### 2026-05-30 Windows-Side Bridge GUI Recovery Update

The Windows bridge GUI now matches the Linux Equipment recovery model.

- `Stop / Abort` is visible inside the Windows-side UTM panel and the critical command rail.
- The browser sends `program_id=utm_stop_or_abort_v1` directly to `/execute` with `require_screen_assertions=false` and `simulate_utm_protocol=false`.
- This is a recovery path only. It bypasses local live preflight by design, but it does not count as UTM test completion or Analysis-ready evidence.
- Linux `/equipment/windows` now has `Open Windows GUI`, allowing the selected bridge URL to be opened from the management page for direct operator inspection.

Required operator follow-up after recovery:

1. Check `Request Log` to prove the recovery `/execute` was received.
2. Refresh evidence and readiness.
3. Retry the normal preflight and UTM run only after the UTM screen state is safe and consistent again.

### 2026-05-30 Equipment Vision Cross-Check Live Event Stream

Lab Equipment now emits Vision physical cross-check progress as Live GUI chat/event messages while the Equipment stage is running.

Event sequence:

- `VISION_PRECHECK_REQUEST`: Equipment Agent requested `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete` physical checks.
- `VISION_CHECK:<check_id>`: each Vision response is streamed with `ok/blocked`, confidence, and frame IDs.
- `VISION_PRECHECK_DONE`: the aggregate Vision cross-check result is available before the Windows UTM protocol proceeds to final handoff packaging.

The controller converts these into `live_chat_message.v1` entries with `role=equipment_ai` and `message_type=signal|status`. This keeps the operator-facing Live GUI aligned with the Improvement 05 rule that screen success alone is not enough: UTM physical motion, fixture state, robot clearance, and completion evidence must be visible as part of the same equipment-control story.

The completed Equipment stage message also carries structured fields for downstream UI/report consumers:

- `visual_assertion`
- `physical_cross_check`
- `data_ledger`
- `data_file_ref`
- `recovery`
- `handoff_packet`

## 2026-05-30 Windows Bridge GUI Operator Console

The Windows-side PyAutoGUI bridge GUI now exposes a local `Local Operator Console` for Lab Equipment UTM operation.

Equipment Agent relevance:
- The Windows operator can preview the exact `/execute` payload for simulation, live UTM, or abort recovery before any command leaves the browser.
- Browser-side validation blocks malformed `Run ID`, `Specimen ID`, `Artifact Timeout Sec`, and `Stable File Sec` values with `WINDOWS_GUI_INPUT_INVALID` before live preflight or `/execute` is attempted.
- The `Stop / Abort` path remains available during busy UI states and maps to the registered `utm_stop_or_abort_v1` recovery macro.
- This GUI-side guard is additive only. The Lab Equipment Agent must still enforce request-log audit, screen evidence, physical cross-check, UTM artifact pull, parse probe, and handoff gating before Analysis.

## 2026-05-30 Bridge Health Metadata Contract

The Lab Equipment Agent now treats Windows bridge health as evidence, not just provider selection.

Reported fields added to `equipment_report.bridge`:
- `bridge_url`: selected Windows bridge base URL when available.
- `bridge_url_host`: parsed Windows host/IP used for the bridge call.
- `remote_server_version`: bridge HTTP server version reported by Windows `/health`.
- `remote_script_version`: Windows helper script/runtime contract version reported by `/health`.
- `client_latency_ms`: Linux-side measured HTTP round-trip latency for live bridge calls.
- `pyautogui_available`: actual `/health.pyautogui.available` value when health evidence exists.
- `pyautogui_failsafe`: actual PyAutoGUI fail-safe state reported by the Windows host.
- `pyautogui_pause`: actual PyAutoGUI pause interval reported by the Windows host.
- `pyautogui_error`: import/runtime error reported by Windows if PyAutoGUI is unavailable.

Rule:
- The GUI must not infer PyAutoGUI availability only from `provider=windows_pyautogui`.
- Live handoff review must use actual health metadata, request-log metadata, screen evidence, Vision cross-checks, save/export responsibility, and pulled UTM data evidence together.

## 2026-05-30 Live GUI Equipment Runtime Event Cards

The Live GUI now renders `equipment.pyautogui.run` progress as structured Equipment runtime cards, not only plain chat text.

Each `live_chat_message.v1` emitted for the Equipment Agent may include:
- `command_id`: normally the bridge `sequence_id`.
- `program_id`: registered UTM program, for example `utm_compression_start_v1`.
- `windows_host`: bridge host when known.
- `macro_command`: structured macro/protocol command metadata, including `target_ui`, step, status, command id, and program id.
- `visual_assertion`: screen/assertion step metadata for ready/running/complete UI checkpoints, including confidence and screenshot artifact when available.
- `physical_cross_check`: equipment motion/cross-check metadata when the event represents physical validation.
- `data_file_ref`: Windows or Linux artifact path observed during save/export/pull/parse steps.
- `data_acquisition`: structured status/path/checksum/row-count/save-method metadata for UTM file recovery.
- `recovery`: operator review recommendation and `failure_code` when a step is blocked/failed/error.

Rendering rule:
- All equipment events are displayed with a `Macro Command` card when command metadata is available.
- Screen/assertion events are displayed as `Visual Assertion` cards.
- Save/export/pull/parse events are displayed as `Data Acquisition` cards.
- Blocked or failed equipment events include a `Recovery` card.
- Live Windows bridge runs often return `step_trace` only after `/execute` completes. `LabEquipmentAgent` replays that trace into the same Live GUI message stream and enriches each event from the returned `screen_checks`, `output_artifacts`, and `data_acquisition` ledger so screenshot artifacts, target UI, checksum, row-count probe, save method, and artifact-pull status remain visible.
- These cards complement the final `equipment_report.v1`; they do not replace the final handoff gates.

## 2026-05-30 Live Bridge Step Trace Replay

A real Windows bridge cannot stream `_event_callback` messages through the HTTP `/execute` call while the command is running. It returns the final `step_trace` after the command completes or blocks.

The Lab Equipment Agent now replays non-simulator `equipment.pyautogui.run.step_trace` entries into the same Live GUI event channel used by simulator callbacks.

Replay behavior:
- `mode=simulator` results are not replayed, because the simulator already emits events during execution.
- Live, disabled, blocked, or locally synthesized non-simulator results with `step_trace` are replayed as `source=bridge_response_trace` events.
- Replayed events preserve `sequence_id`, `program_id`, `bridge_host`, bridge version metadata, latency metadata, failure code, and data-file references when present.
- The controller renders these events as Equipment runtime cards, so screen assertions, save/export, artifact pull, parse probe, and recovery evidence remain visible in the Live GUI even when the bridge only reports at the end of `/execute`.

Operational rule:
- Live GUI progress cards are evidence for operator visibility. Final Analysis handoff still requires the structured `equipment_report.v1`, `utm_data_ready.v1`, request-log proof, physical cross-check, screen evidence, and pulled UTM data verification.

## 2026-05-30 Windows Bridge Execute Action Coverage

The Windows bridge `/execute` protocol runner now supports the Improvement 05 Phase 2 screen-control primitives directly inside registered/custom protocol sequences:

- `screenshot`: captures a screenshot artifact and records both the screenshot artifact step and the sequence step.
- `locate_image`: one-shot visual locator assertion using the existing locator stack.
- `assert_text`: one-shot OCR/text assertion for status labels/dialog text.
- `wait_until_text`: wait-budget OCR/text assertion for status labels/dialog text.
- `wait_until_image`: wait-budget visual locator assertion, equivalent to `wait_until` but explicit for image-driven protocols.
- `focus_window`: keeps the existing window focus precondition behavior.
- `assert_visible`: keeps the existing screen assertion behavior.

Readiness logic treats `locate_image`, `wait_until_image`, `assert_text`, and `wait_until_text` as locator-consuming actions, so the Windows GUI can report missing required locators or OCR/text regions before live UTM control.

Operational rule:
- `screenshot`, `locate_image`, `wait_until_image`, `assert_text`, and `wait_until_text` are protocol primitives, not proof of UTM success by themselves.
- Analysis handoff still requires the combined Equipment gates: screen transition, Vision/physical cross-check, save/export responsibility, Linux artifact pull, parse probe, and request-log audit.

## 2026-05-30 Windows GUI Run JSON Custom Sequence

The Windows bridge GUI `Run JSON` path now executes operator-supplied `sequence[]` payloads even when no registered `program_id` is provided.

Behavior:
- The server labels these runs as `program_id=custom_sequence` and `program_type=operator_sequence`.
- The sequence uses the same guarded protocol executor as registered UTM programs, including `screenshot`, `locate_image`, `wait_until_image`, `assert_visible`, `focus_window`, keyboard, wait, and file-wait actions.
- Screenshot artifacts from custom sequences are returned in `output_artifacts[]` and remain pullable through `/artifacts/<artifact_id>`.
- Successful custom sequences end with `DONE: custom sequence completed`.

Safety rule:
- `custom_sequence` is an operator/debug/calibration path only. It must not be interpreted as a completed UTM experiment or `ready_for_analysis` handoff.
- Autonomous Equipment handoff still uses registered UTM protocols such as `utm_compression_start_v1` and the full evidence gates.

## 2026-05-30 Linux Bridge Visual Action Allowlist Alignment

The Linux Windows-PyAutoGUI bridge client and `configs/devices.yaml` now allow `wait_until_image` in addition to `locate_image`, `wait_until`, `assert_visible`, `focus_window`, and `screenshot`.

Reason:
- The Windows bridge server can execute `wait_until_image` inside `/execute` protocol sequences.
- The Linux bridge validates action names before simulator/live dispatch.
- Without the matching Linux allowlist, a valid Windows-side visual protocol would be blocked before reaching the bridge.

Operational rule:
- `wait_until_image` is a screen-state primitive. It must still be paired with the Equipment handoff gates before Analysis: Vision physical evidence, save/export responsibility, Linux artifact pull, parse probe, and request-log audit.

## 2026-05-30 Click Retry Evidence Rule

The Windows bridge protocol runner now implements the Improvement 05 click-recovery rule for registered and custom sequences.

Behavior:
- If a `click` action cannot resolve its UIA/image locator, the bridge captures a retry screenshot before attempting the locator one more time.
- Retry is capped at one attempt, using the registered program/action `max_retries` setting with a hard cap of 1.
- The retry evidence is recorded in `step_trace` as `<STEP>_RETRY_SCREENSHOT` and `<STEP>_RETRY_LOCATE`.
- The retry screenshot is returned as a `screen_png` artifact when `screen_artifacts` is collected by the protocol.
- If the second locator attempt still fails and the click is required, the run blocks with `UI_LOCATOR_NOT_FOUND`.

Operational rule:
- Retry exists only to recover from transient GUI/locator timing. It must not hide persistent locator drift, wrong UTM window focus, DPI mismatch, or popups. Required click failure remains a blocking Equipment event and should be reviewed through the saved retry screenshot.

## 2026-05-30 Coordinate Fallback Evidence Rule

Fixed-coordinate clicks remain the final fallback after UIA and image-locator paths. When the bridge must use coordinate fallback, it now records explicit evidence required by Improvement 05.

Recorded evidence:
- `screen_size`: PyAutoGUI-reported screen size at click time.
- `dpi_scaling`: payload-provided value or Windows scale-factor best effort, otherwise `unknown`.
- `target_window_rect`: selected UTM/window rectangle when discoverable, otherwise `unknown`.
- Before-click screenshot artifact and SHA-256 hash.
- After-click screenshot artifact and SHA-256 hash.
- Coordinate click details in the main click step trace.

Step trace additions:
- `<STEP>_COORDINATE_BEFORE_SCREENSHOT`
- `<STEP>_COORDINATE_AFTER_SCREENSHOT`
- `<STEP>` detail containing coordinate, screen size, DPI scaling, target window rect, and before/after screenshot hashes.

Operational rule:
- Coordinate fallback evidence does not make coordinate control the preferred mode. It exists to make unavoidable fallback auditable. Registered UTM protocols should still prefer UIA selectors or calibrated image locators.

## 2026-05-30 Wait-For-File Action Verification

The Windows bridge protocol runner now treats `wait_for_file` as a real file-stability check instead of a trace-only marker.

Behavior:
- The action resolves `{run_id}` and `{specimen_id}` placeholders in the configured path/glob.
- It searches the explicit path or matching glob candidates and waits for stable file size using the configured `stable_for_sec` and `timeout_s` / export timeout values.
- If a stable file is found, the step is recorded as `ok` with the path and stability duration.
- If no stable file is found and `required=true`, the sequence blocks with `UTM_DATA_TIMEOUT`.
- If no stable file is found and the action is optional, the sequence records `warning` and continues so the registered UTM protocol can attempt manual save/export fallback.

Operational rule:
- `wait_for_file` warning after auto-save does not mean the experiment succeeded. It means the auto-save path was not sufficient and the Equipment Agent must prove save/export responsibility through fallback, Linux artifact pull, and parse probe before handoff.

## 2026-05-30 Windows Bridge GUI Runtime Timeline

The Windows-side PyAutoGUI bridge GUI now includes a `Run Timeline` panel between the Local Operator Console and the Overview panel.

Purpose:
- Show recent command steps without requiring the operator to inspect raw Result JSON.
- Preserve blocked/failed steps, screenshot/evidence capture steps, and CSV handoff steps in chronological order.
- Keep the Windows operator view aligned with the Linux Live GUI evidence cards.

Behavior:
- Any response with `step_trace[]` is appended to the timeline.
- Responses without `step_trace[]` but with `status`, `tool`, or `failure_code` are still represented as a single timeline item.
- Timeline entries are color-coded from step status: ok/ready/complete as green, blocked/failed/error as red, and intermediate/unknown states as amber.
- The timeline keeps the latest 120 entries internally and renders the latest 60 entries to avoid unbounded browser growth.
- `Clear Timeline` only clears the browser-side visual timeline; it does not delete request logs, screenshots, locator files, or UTM CSV artifacts.

Operational rule:
- The timeline is an operator visibility aid. It is not an acceptance gate by itself. Live handoff still depends on `equipment_report.v1`, `utm_data_ready.v1`, request-log proof, physical/screen cross-checks, Linux artifact pull, and parse verification.

## 2026-05-30 UTM CSV Signal Quality Gate

UTM CSV acceptance now requires signal-level validation. A file with the right name and columns is not sufficient for Analysis handoff.

Required parse checks:
- Required columns must exist: `time_s`, `displacement_mm`, `force_N`.
- At least two non-empty data rows must exist.
- At least two numeric rows must be parseable across all required columns.
- `time_s` must be monotonic non-decreasing.
- `displacement_mm` must change across samples.
- `displacement_mm` must be monotonic in either direction, allowing either positive or negative compression sign conventions.
- `force_N` must contain a nonzero signal and must change across samples.

Failure codes:
- `UTM_DATA_PARSE_FAILED`: missing columns, too few rows, or too few numeric rows.
- `UTM_DATA_NON_MONOTONIC_TIME`: time samples are not ordered.
- `UTM_DATA_NO_DISPLACEMENT_SIGNAL`: displacement does not change.
- `UTM_DATA_NON_MONOTONIC_DISPLACEMENT`: displacement changes direction in the raw probe window.
- `UTM_DATA_NO_FORCE_SIGNAL`: force is zero/flat and therefore does not prove UTM loading.

Where enforced:
- Windows bridge server `_probe_utm_csv()` blocks live protocol success before returning `verified_complete`.
- Linux bridge `_probe_utm_csv_bytes()` re-validates pulled artifacts and refuses to promote `result_file` / `utm_csv_path` if the local copy fails quality checks.
- Lab Equipment Agent `_probe_csv_file()` re-validates the Linux-local file and blocks `utm_data_ready.v1` even if a bridge response incorrectly claimed `data_parse_probe_ok=true`.

Recorded metadata:
- `data_quality.numeric_row_count`
- `data_quality.invalid_numeric_row_count`
- `data_quality.force_nonzero`
- `data_quality.force_changes`
- `data_quality.force_range_N`
- `data_quality.displacement_changes`
- `data_quality.displacement_range_mm`
- `data_quality.displacement_monotonic`
- `data_quality.displacement_direction`
- `data_quality.time_monotonic_non_decreasing`

Operational rule:
- Analysis handoff is allowed only when the Linux-local CSV passes this quality gate. This prevents a GUI macro or export dialog from being treated as a successful mechanical test when the UTM data is all-zero, flat, malformed, or incomplete.
- Any `UTM_DATA_*` quality failure is routed as a `hardware_alert.v1` with `component=utm_data_export`, `device=utm_export_file`, and high `data_integrity` risk so Guardian/Live GUI can distinguish data-quality failure from generic UTM protocol failure.

## 2026-05-30 Analysis Agent Defensive UTM Gate

Analysis Agent now re-validates UTM curve signal quality before computing metrics, objective score, BO observations, or Knowledge payloads.

Reason:
- Equipment Agent and the Linux bridge already validate UTM CSV quality, but Analysis may still receive data through direct `equipment_result`, nested `equipment_report`, `utm_data_ready`, inline curve, or legacy file keys.
- Analysis must not treat an all-zero/flat/malformed UTM curve as a real mechanical test simply because a file was readable.

Behavior:
- File-backed CSV/JSON/JSONL curves are parsed into raw-order points first, then checked before displacement-sorted metrics are computed.
- Inline UTM curves are also checked before metric calculation.
- Negative compression force sign conventions are accepted by using absolute force magnitude for analysis metrics.
- If the signal gate fails, Analysis returns `success=false` and does not emit ready BO/Knowledge handoff payloads.

Analysis failure codes:
- `UTM_DATA_REQUIRED`: no curve points were available.
- `UTM_DATA_PARSE_FAILED`: fewer than two parsed curve points.
- `UTM_DATA_NON_MONOTONIC_TIME`: raw `time_s` samples are not monotonic non-decreasing.
- `UTM_DATA_NO_DISPLACEMENT_SIGNAL`: displacement does not change.
- `UTM_DATA_NO_FORCE_SIGNAL`: force is zero/flat after sign normalization.

Recorded metadata:
- `analysis.source.signal_quality_probe`
- `analysis.data_quality` on blocked analyses
- `analysis.data_quality_gate` on successful analyses

Operational rule:
- Analysis is the final defensive gate. Even if a previous layer incorrectly claims `data_parse_probe_ok=true`, Analysis blocks metric generation unless the actual curve contains a credible force/displacement signal.

2026-05-30 handoff proof update:
- For live Windows PyAutoGUI UTM runs, Analysis also requires `equipment_report.cross_checks.save_export_responsibility_ok=true`; a readable CSV plus `save_completed=true` is not enough.
- Analysis requires `equipment_report.cross_checks.request_audit_execute_identity_match=true` so the `/execute` event must match the expected run/sequence/specimen/program identity, not just exist somewhere in the request log.
- Missing save/export responsibility blocks with `EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:save_export_responsibility_ok` before metrics or BO observations are generated.


## 2026-05-30 Direct UTM Backend Signal Gate

The legacy/direct `utm.run_protocol` path now shares the same signal-level acceptance gate used by the Windows PyAutoGUI bridge and the Linux Equipment Agent artifact pull path. This keeps the direct backend from becoming a bypass around live data validation.

Acceptance requirements for direct UTM CSV files:

- Required columns: `time_s`, `displacement_mm`, `force_N`.
- At least two numeric rows must be parseable.
- `time_s` must be monotonic non-decreasing.
- `displacement_mm` must contain measurable motion and be monotonic in either compression sign convention.
- `force_N` must contain a non-zero, changing force signal; positive and negative compression sign conventions are both accepted.

Failure behavior:

- Live direct backend remains fail-closed when not explicitly configured.
- A supplied CSV that has columns but no real force/displacement signal returns `status=blocked`, `data_acquisition.status=pulled_to_linux_parse_failed`, and a specific failure code such as `UTM_DATA_NO_FORCE_SIGNAL` or `UTM_DATA_NO_DISPLACEMENT_SIGNAL`.
- `cross_checks.data_parse_probe_ok` and `cross_checks.save_export_responsibility_ok` remain false until the CSV passes the same quality probe used by the Windows bridge path.
- Test mode still creates deterministic synthetic UTM CSV data, but the generated file is also checked by the same quality gate before being reported as ready for Analysis.

## 2026-05-30 Windows Bridge GUI Browser Audit

The standalone Windows PyAutoGUI bridge GUI is now covered by a repeatable Selenium browser audit: `tests/ui/windows_bridge_gui_browser_audit.py`.

Audit scope:

- Opens the Windows bridge root page without calling equipment actions.
- Verifies Bridge Connection, full UTM controls, evidence controls, Program Manager, Browse JSON, Download Template, and manager result are present together.
- Exercises the actual `Browse -> no registration -> Validate -> Add to Registry -> Delete` lifecycle and verifies built-ins remain immutable.
- Checks that the 1920px viewport has no horizontal overflow and that buttons remain operator-clickable.

Latest local audit evidence:

- Command: `.venv/bin/python tests/ui/windows_bridge_gui_browser_audit.py --base-url http://127.0.0.1:18765 --out-dir artifacts/ui --width 1920 --height 1080 --geckodriver /snap/bin/geckodriver --token <bridge-token>`
- Result: PASS for both `install/windows_pyautogui_bridge_server.py` and `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`.
- Screenshot: `artifacts/ui/windows_bridge_gui_browser_audit.png` (`1920x994`).
- Layout check: `scrollWidth=1908`, `clientWidth=1908`.
- The packaged bridge copy intentionally keeps additional compatibility hooks (`BridgeConfig`, `BridgeHTTPServer`, `execute_payload`) for legacy launcher/tests; those hooks are not removed during GUI synchronization.

Operational boundary:

- This audit never presses a program's Test button. It registers and deletes one bounded audit macro in an isolated program directory; real UTM handoff remains a Linux Lab Equipment Workspace responsibility.


### 2026-05-30 Windows packaged bridge smoke-test update

The packaged Windows bridge folder `Pyautogui_server_for_window/` now carries the same operator-GUI and proof-loop smoke expectations used by the Linux-side Lab Equipment path.

- `Pyautogui_server_for_window/tests/smoke_test.py` starts the packaged compatibility server with `BridgeConfig` / `BridgeHTTPServer` and verifies the Web GUI contains `Run Timeline`, `Live Proof Checklist`, and `Operator runtime status`.
- The smoke test checks token-gated `/health`, registered UTM programs, `/readiness`, `/request-log`, guarded `/execute`, `program1`, and `/artifacts` without requiring PyAutoGUI to be installed.
- PyAutoGUI-missing environments must return explicit blocked results such as `PYAUTOGUI_NOT_INSTALLED`; they must not report a fake macro success.
- `Pyautogui_server_for_window/scripts/local_e2e_test.ps1` now checks the same GUI/operator panels and readiness/request-log/artifact endpoints before declaring the local Windows package usable.

Operational effect: the Windows-side distribution is no longer validated only as a `program1` demo page. It is validated as the field operator surface for the 5번 UTM visual-control/data-recovery loop.

### 2026-05-30 Vision cross-check freshness evidence update

`vision.equipment_cross_check` now returns freshness metadata on every UTM physical check result:

- `timestamp`: when the physical/screen observation was produced.
- `expires_at`: the last time the check may be consumed by Lab Equipment.
- `freshness_ttl_ms`: the TTL used for the decision.

Lab Equipment rejects stale explicit Vision checks and now also rejects positive live checks that do not carry an `expires_at` validity bound. This update makes the tool-generated path auditable as well: `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete` are no longer just boolean mock/live responses, but bounded-time evidence. In live mode the default camera tool still fails closed unless an actual external Vision implementation supplies positive checks, and any positive check must carry its validity window into `equipment_report.vision_cross_checks`.

Operational effect: Equipment handoff can be audited for both physical evidence content and evidence freshness. This supports the 5번 rule that UTM motion/fixture safety must not be inferred from old screen or camera observations.

### 2026-05-30 Windows bridge CLI packaging fix

The packaged and install Windows bridge Python servers now honor the CLI arguments used by the PowerShell launch scripts:

- `--host`, `--port`, `--token`, `--token-header`
- `--artifact-dir`, `--reference-dir`, `--utm-export-dir`
- `--allow-no-token`, `--open-browser`

This closes a Windows packaging gap where `run_bridge.ps1` and `local_e2e_test.ps1` passed explicit runtime paths, but the Python server only read environment variables. CLI launch is now covered by `Pyautogui_server_for_window/tests/smoke_test.py`, and the standalone bridge GUI browser audit passed at 1920px against a CLI-started packaged server.

Additional 2026-05-30 Windows-side GUI usability update:

- The packaged Windows PyAutoGUI bridge GUI now includes `Focus Mode` / `Full View` switching. Focus Mode is an operator display optimization only; it does not bypass Linux Equipment Agent, Analysis, or Guardian gates.
- The left connection/UTM setup column is sticky and scrollable, so token, run/specimen ID, target window, export settings, and safety confirmation remain accessible on 1080p operator displays.
- The critical command rail is sticky: `Preflight`, `Evidence`, `Simulate`, `Live UTM`, and `Abort` remain visible while reviewing result JSON, evidence tables, artifact previews, and operator logs.
- Command execution toggles a visible busy state and pulsing status dot. `Abort` remains enabled during busy execution as a recovery control.
- Both source variants must stay aligned: `install/windows_pyautogui_bridge_server.py` and `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`.


## 2026-05-30 Windows Standalone Bridge GUI Proof Gate Strip

The Windows-side PyAutoGUI bridge GUI now mirrors the Lab Equipment proof model directly on the local operator page. The Live Proof Checklist includes a compact seven-gate strip above the detailed checklist:

- Bridge: Windows bridge health and PyAutoGUI availability.
- Locators: required UTM ready/start/running/complete locator capture status.
- Safety: local operator physical setup confirmation before live execution.
- Request: `/execute` presence in the bridge request log for live handoff proof.
- Screen: before/start/complete screenshot evidence.
- Save: recognized save/export responsibility evidence.
- CSV: UTM CSV artifact and parse-probe readiness.

The strip is driven by the same `renderProofChecklist()` state as the detailed proof list, so it is an operator summary of the real local gate state rather than a separate cosmetic widget. The repeatable browser audit `tests/ui/windows_bridge_gui_browser_audit.py` verifies these DOM ids and the 1920px no-horizontal-overflow layout.

## 2026-05-30 Windows Bridge GUI Field Runbook Update

The Windows-side PyAutoGUI bridge GUI now includes a local `Field Runbook` panel in the connection sidebar. It gives the operator a four-step live-use checklist that is driven by the same proof state used by the `Live Proof Checklist`:

1. `Connect bridge`: Health must show PyAutoGUI availability.
2. `Calibrate UTM locators`: Readiness must show required UTM screen locators are captured.
3. `Execute registered protocol`: a live authenticated `/execute` event must be present in the bridge request log.
4. `Verify handoff evidence`: before/start/complete screen evidence, save/export responsibility, and CSV parse-probe evidence must all be available.

This is a GUI usability layer only. It does not weaken the Lab Equipment handoff gates. Linux-side Analysis still requires `equipment_report.v1`, `utm_data_ready.v1`, request identity proof, physical Vision evidence, pulled CSV artifact, and parse verification before accepting UTM data.

## 2026-05-30 Windows Bridge Server Action Fail-Closed Update

The Windows-side bridge no longer treats unsupported operator-supplied `sequence[]` actions as warnings. If a custom JSON sequence reaches `/execute` with an unsupported action, the bridge returns:

- `ok=false`
- `status=blocked`
- `failure_code=PYAUTOGUI_ACTION_NOT_ALLOWED`
- a blocked `step_trace` row naming the unsupported action

This closes a direct-Windows-GUI bypass where Linux-side action allowlist validation could be skipped by calling the Windows bridge page directly. `custom_sequence` remains available for operator calibration/debug, but unsupported or misspelled actions must not be reported as a completed sequence.

## 2026-05-30 Equipment Vision Identity Gate

Live UTM handoff now requires Vision physical evidence to be tied to the current Equipment run identity, not only to be fresh.

Required identity fields for `equipment_vision_check_result` and Equipment-targeted `vision_signal_item.v1` entries:

- `run_id`: must match the active Lab Equipment `state.run_id`.
- `specimen_id`: must match the specimen currently handed off to the Equipment Agent.
- `expires_at`: remains required and must be in the future.

Blocking behavior:

- Missing freshness still blocks first with `VISION_<CHECK_ID>_FRESHNESS_REQUIRED`.
- Expired evidence blocks with `VISION_<CHECK_ID>_STALE`.
- Fresh evidence without run/specimen identity blocks with `VISION_<CHECK_ID>_IDENTITY_REQUIRED`.
- Fresh evidence with mismatched run/specimen identity blocks with `VISION_<CHECK_ID>_IDENTITY_MISMATCH`.

This prevents reusing a valid-looking Vision frame from a previous specimen or previous autonomous run as physical proof for the current UTM execution.

## 2026-05-30 Windows Bridge GUI Command Kit Update

The Windows-side PyAutoGUI bridge GUI has been refined for field operation on a 1920x1080 display.

- The page no longer auto-calls authenticated endpoints when the browser has no bridge token. It shows `Enter bridge token` first, preventing a misleading red auth failure on first load.
- The critical command rail was widened so `Preflight`, `Evidence`, `Simulate`, `Live UTM`, and `Abort` are readable/clickable as field controls rather than narrow test buttons.
- The Connection panel now includes `Bridge Command Kit`, which copies exact Linux/Windows parity commands:
  - `Copy curl Health`
  - `Copy PowerShell Health`
  - `Copy curl Execute`
- Clipboard fallback is implemented for browsers where `navigator.clipboard` is unavailable.
- Step Trace rows now use status-tinted backgrounds for `ok`, `warn`, and `bad` states, making blocked UTM/export steps easier to identify without reading raw JSON first.
- The top command banner now has `Recommended next action`; it reads the first incomplete Live Proof Checklist gate and routes the operator to token entry, Health, Readiness, safety confirmation, screenshot/evidence refresh, or guarded Live UTM execution.

Operational boundary: these are operator-usability improvements only. They do not bypass token authentication, local preflight, live safety confirmation, request-log identity proof, screen evidence, save/export responsibility, Linux CSV pull/parse, Vision evidence, Analysis gates, or Guardian gates.

## 2026-05-30 Blocked Analysis Evidence Payload Update

Analysis now preserves Equipment evidence even when the UTM run is blocked before valid metrics can be accepted.

- If live Equipment proof gates fail after a CSV is present, `AnalysisAgent` returns `knowledge_payload.raw_artifact_refs` with the CSV path and tags the handoff blocker, for example `UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED` or `EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:<gate>`.
- If no readable UTM CSV exists, nested `equipment_report.artifact_refs`, `screen_evidence_refs`, and other bridge evidence remain in the Knowledge payload so the failed Windows GUI state can be audited later.
- If the CSV exists but has invalid mechanical signal quality, the rejected CSV path is preserved and the signal failure code such as `UTM_DATA_NO_FORCE_SIGNAL` is recorded in `failure_tags`.

Operational effect: blocked live UTM runs still provide a complete failure memory packet for Knowledge, Guardian, and later self-evolution, while remaining blocked for objective scoring and Analysis-ready handoff.

## 2026-05-30 Guardian Blocked-Analysis Review Update

Guardian now reads blocked Analysis state directly in addition to Lab Equipment hardware alerts.

- `latest_analysis.ok=false` with a UTM/Equipment failure code becomes a Guardian consistency issue.
- `latest_analysis.equipment_handoff_gate.status=blocked` records the handoff blocker as a Guardian consistency issue.
- `latest_analysis.failure_tags` carrying `UTM_DATA_*`, `UTM_SAVE_EXPORT_*`, or `EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:*` become Guardian-visible warnings.

This makes a rejected CSV or incomplete Equipment proof gate trigger recovery review rather than looking like a normal completed analysis with a poor score.

## 2026-05-30 Windows Bridge GUI Compact Operations Update

This complete operator layout was restored on 2026-08-04. Program Manager remains additive; the UTM controls and proof panels below are part of the Windows-local backend view, while Linux remains authoritative for orchestration and handoff trust.

### 2026-08-04 Essential Surface and Advanced Tools

The standalone bridge root uses an essential-first presentation without changing Equipment Agent behavior.

- The default surface exposes bridge/PyAutoGUI state, latest manager/test result, and Program Manager.
- Program Manager uses compact rows. Its editor opens only for New, View, Edit, or Browse JSON and closes after Add to Registry or Cancel.
- `Advanced Tools` retains the complete original Windows console and is closed by default.
- Advanced Tools does not duplicate Program Manager or proxy its controls.
- Program persistence is authoritative from the Windows JSON registry; execution remains authoritative from `GET /programs` and authenticated `POST /execute`.
- Linux Lab Equipment Agent remains authoritative for orchestration, evidence acceptance, and downstream handoff.

The standalone Windows PyAutoGUI bridge GUI now prioritizes live-use status over raw payload editing.

- The `Overview` and live proof surface are placed immediately after the command rail/HUD, before `Local Operator Console` and `Run Timeline`, so blockers are visible without scrolling through JSON preview panels.
- Wide-screen overview cards use a two-column layout; proof checklist and bridge-file evidence remain full width to keep gate text and Windows paths readable.
- The left-side Connection, Safe Diagnostics, UTM Protocol, Locator Capture, and Operator Log panels can be collapsed and expanded. The collapsed state is stored only in browser local storage and does not affect bridge execution rules.
- `Focus Mode` still acts only as a display filter. It does not bypass token authentication, safe preflight, live confirmation, request-log proof, screen evidence, CSV artifact proof, or Linux-side handoff verification.

## 2026-05-30 Vision Proof Draft Helper

Linux Equipment GUI now exposes a non-actuating Vision proof draft helper for physical UTM validation:

```text
POST /api/equipment/windows/vision-proof-draft
```

The helper scans current runtime metadata and latest Vision observations for the three required physical checks:

- `utm_pre_start`
- `utm_motion_confirm`
- `utm_test_complete`

When all required checks are present and frame IDs are available, the response returns `status=ready` and a `vision_proof` object that can be pasted into the physical validation request. If any check or frame evidence is missing, the response returns `status=incomplete`, `ok=false`, and explicit blockers such as `VISION_UTM_PRE_START_REQUIRED` or `VISION_FRAME_IDS_REQUIRED`.

This helper is a convenience layer only. It must not be treated as UTM completion evidence by itself. Real completion still requires guarded physical validation, persisted proof package verification, and `equipment.pyautogui.improvement05_completion_audit` returning `complete_evidence_verified`.

## 2026-05-30 Physical Screen Evidence Strictness

`lab_equipment_live_utm_validation.py` now requires physical screen evidence to be file-backed before `screen_state_evidence` can pass. Required checkpoints are `before_start`, `after_start`, and `after_complete`. Each checkpoint must expose a unique `screenshot_artifact`/`artifact`/`path` reference, and that reference must resolve to an existing Linux-local file either directly or via `artifact_records`, `output_artifacts`, or `artifacts`.

Operationally, Windows bridge UTM macros must return screen captures as artifact records, for example `{ "artifact_id": "screen-before", "local_path": "/.../before.png" }`. A bare label without a local file is treated as unresolved and blocks physical validation.

## 2026-05-30 Physical Save/Export Responsibility Strictness

Physical live validation now treats save/export as an evidence-backed gate. `cross_checks.save_export_responsibility_ok=true` is advisory only and cannot pass the gate by itself. The accepted physical methods are `windows_export_watch`, `manual_save_dialog`, and `export_menu`. The report must also include `save_attempted_by_agent=true` or the watched-export method, `save_confirmation_screen_ok=true`, and at least one Windows or Linux export path.

Completion Audit applies the same rule to `manifest.save_export`: `ok=true` is insufficient unless method, attempt, confirmation, and path are all present. This prevents a bridge from claiming save success without proving where the UTM data was exported.

## 2026-05-30 Physical Data Artifact Strictness

`lab_equipment_live_utm_validation.py` now validates the Linux-returned UTM CSV directly before accepting a physical live validation report. The data path is resolved from `result_file`, `utm_csv_path`, `data_acquisition.linux_path`, or `data_acquisition.local_path`. The resolved path must exist on the Linux host. The runner then parses the CSV and requires `time_s`, `displacement_mm`, and `force_N` columns with at least two numeric rows, monotonic time, changing displacement, and a nonzero changing force signal.

Bridge-provided booleans such as `local_parse_ok=true`, `artifact_pull.data_artifact_parse_ok=true`, or `cross_checks.data_parse_probe_ok=true` are no longer sufficient by themselves. A missing file or flat CSV blocks `linux_data_artifact` and/or `utm_csv_parse_probe` before any Analysis handoff.

## 2026-05-30 Physical Vision Proof Strictness

`lab_equipment_live_utm_validation.py` and `/api/equipment/windows/live-validation` now require physical Vision proof to be evidence-bearing, not just boolean.

A physical validation proof must include:

- matching top-level `run_id`;
- matching top-level `specimen_id`;
- `checks.utm_pre_start.ok=true` plus frame/observation evidence;
- `checks.utm_motion_confirm.ok=true` plus frame/observation evidence;
- `checks.utm_test_complete.ok=true` plus frame/observation evidence.
- the combined proof must contain at least three unique frame/observation IDs. Reusing the same frame ID for all checks is blocked before `verified_complete`.

Boolean-only payloads such as `{ "utm_motion_confirm": { "ok": true } }` are blocked because they do not prove fixture/motion/completion states. This rule applies before proof-package verification so a run cannot be promoted as `verified_complete` unless physical Vision evidence is already attached.

### 2026-05-30 Linux artifact record compatibility update

The Linux Windows-bridge client mirrors pulled `output_artifacts[]` into `artifact_records[]` after downloading `/artifacts/<artifact_id>`. Downstream gates should resolve screen and CSV refs from either field, but physical live validation still requires the records to point to existing Linux-local files. This prevents a mismatch where the bridge pull succeeds but a later proof-package or Analysis gate cannot find the same evidence list.

### 2026-05-30 physical live execute proof gate

The Linux evidence audit and proof package verifier now treat guarded physical dispatch as its own required evidence item. The intermediate audit and final package are incomplete unless the physical validation packet proves that `Run Physical Validation` or an equivalent guarded Lab Equipment path actually sent a live `/execute` command with `requested_physical_execute=true`, `execute_sent=true`, `non_actuating=false`, `status=verified_complete`, and matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`. This prevents a ready-looking Equipment report or setup test from being used as Improvement 05 completion evidence without a real physical validation run.

### 2026-05-30 proof package source and uniqueness gate

Live validation, proof package generation, intermediate evidence audit, and Completion verification all check the embedded physical-validation source packet, not only the proof manifest. A hand-written manifest claim is not enough: `source_packets.last_windows_utm_physical_validation` must also prove `requested_physical_execute=true`, `execute_sent=true`, `non_actuating=false`, and `status=verified_complete`. The source packet and manifest must both expose `run_id`, `sequence_id`, `specimen_id`, and `program_id`, and those fields must agree. Screen proof also requires three distinct Linux-local screenshot files with a recognized image signature, so duplicate refs, reused screenshots, placeholder strings, or non-image files remain blocked before `verified_complete`, evidence-audit readiness, or final audit can pass. The intermediate evidence audit also verifies that the referenced Linux-local CSV exists and reruns the CSV parse/signal probe before it advertises Analysis readiness.

============================================================
UTM Screen Artifact Validity Gate
============================================================

For a physical UTM compression run, `utm_compression_start_v1` must not return `verified_complete` unless Windows-side screenshots are real image files. The Windows bridge validates the image signature after every screenshot save and only counts `screen_png` artifacts with `image_signature_ok=true`.

Required compression-run checkpoints:

- `before_start`: UTM ready state before the start command.
- `after_start`: running state after the start command.
- `after_complete`: complete state after the UTM test finishes.

If any checkpoint is missing, duplicated, or backed by a non-image file, the bridge response must stay blocked with `UTM_SCREEN_EVIDENCE_FILES_REQUIRED`. `utm_export_csv_v1` is only a save/export macro and must not be used as standalone physical compression proof.

## 2026-05-30 CLI Live Validation Readiness Gate

`scripts/lab_equipment_live_utm_validation.py` now checks the active UTM profile before a physical CLI run. The runner verifies the selected `program_id`, export glob, `require_screen_assertions`, locator coverage for ready/start/running/complete states, and that bench simulation is off. If `--confirm-live-execute` is passed while this passive profile is incomplete, `/execute` is not sent and the report records `UTM_PHYSICAL_VALIDATION_READINESS_BLOCKED` with `execute_sent=false`.

Operational effect: the CLI path is no longer a weaker route around the GUI readiness gate. Operators can still run non-actuating preflight, but a physical UTM command requires the same autonomous-profile readiness assumptions used by the Equipment workspace.

## 2026-08-08 Inline Advanced Visual Work Queue Skill

`advanced_visual_work_queue_demo` is an inline Equipment Skill, not a resident
subagent. The operator records the workflow once, ATR compiles the recording
into immutable `atr.equipment_skill.v1` and `atr.pyautogui_program.v1`
artifacts, and the Equipment runtime replays deterministic segments through the
existing authenticated Windows PyAutoGUI bridge.

The demonstrated workflow performs all of the following without executable
coordinate fallback:

- selects `specimen-beta` by visible identity after source rows reorder;
- drags the selected row into `ANALYSIS QUEUE` after the window moves;
- configures `Compression`, evidence capture, and load limit `12.5`;
- handles exactly one visible `EVIDENCE REQUIRED` recovery;
- exports matching JSON and CSV evidence;
- blocks before queue mutation when `specimen-beta` is absent.

Normal replay is deterministic and does not invoke an LLM. A future recovery
agent may inspect a failure packet, but it must not mutate or bypass the
recorded action contract. Pointer coordinates remain in `recording.json` only
as audit metadata. Compiled `click`, drag-source `move_to`, and `drag_to`
actions contain embedded PNG candidates and `coordinate_fallback=false`.

The recorder keeps a short, recording-only history of pointer frames and uses
a stable frame captured before pointer hover changes a target's appearance.
The deterministic demo also keeps default and hover colors equal for recorded
controls. The bridge searches the complete screenshot and chooses the globally
highest normalized candidate score rather than the first scan-order match.

Runtime evidence is written under:

```text
runs/equipment_skill_advanced_queue_e2e/
memory/equipment_skills/advanced_visual_work_queue_demo/<version>/
```

Each Skill version is immutable. Rerecording requires a new explicit version;
the runner never deletes or rewrites an existing validated package. A valid E2E
summary reports `analysis_attempts=2`, `recovery_count=1`, one CSV row matching
the JSON object, and missing-target failure code `UI_LOCATOR_NOT_FOUND`.
