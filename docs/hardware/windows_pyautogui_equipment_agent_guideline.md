# Windows PyAutoGUI Equipment Agent Runtime Guideline

Status: implementation guideline only. No runtime code is defined in this document.

Purpose:

- Extend the existing `equipment_agent` so it can operate, control, and monitor a Windows PC on the internal network through PyAutoGUI.
- Keep the current project stage order, agent names, and `AgentResult` contracts unchanged.
- Use a constrained bridge protocol instead of arbitrary remote-code execution.

Windows host setup:

- See `docs/hardware/windows_pyautogui_bridge_windows_setup.md` for Windows PC installation, firewall, token, bridge startup, and manual validation procedure.

Primary target:

- Linux autonomous researcher server runs the orchestration workflow.
- Windows PC runs a small PyAutoGUI bridge service.
- `equipment_agent` lets the LLM select appropriate MCP-style tool calls from the current state, user command, and bridge health.
- The bridge executes only structured, allowlisted actions or registered macro programs.
- The Windows bridge performs GUI automation, returns step traces, screenshots or screenshot metadata, and health status.
- Operators can open `/equipment/windows` from Main GUI -> Device Workspaces to discover, select, save, and test a Windows bridge host.

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
