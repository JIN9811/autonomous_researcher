# Local Development PyAutoGUI Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a localhost bridge on Ubuntu that performs actual X11 PyAutoGUI actions through the same API, GUI, Program Manager, and saved-candidate path as the Windows bridge.

**Architecture:** Extend the packaged bridge with an explicit platform boundary while preserving its API. Add a focused ATR supervisor that owns only the localhost process and persists its private token. Expose supervisor controls in the existing Equipment Workspace and select the local endpoint through the existing `WindowsPyAutoGUIBridge` client rather than adding a second execution path.

**Tech Stack:** Python 3.12, FastAPI, `http.server`, httpx, PyAutoGUI, X11, wmctrl/xdotool, vanilla HTML/CSS/JavaScript, pytest, Selenium.

## Global Constraints

- Bind the local bridge only to `127.0.0.1:8766`.
- Keep `X-Bridge-Token`, the existing action allowlist, and `pyautogui.FAILSAFE = True`.
- Do not add shell-command or arbitrary-executable actions.
- Local and Windows bridge selections are explicit; neither is a fallback.
- Keep `install/windows_pyautogui_bridge_server.py` byte-identical to the primary bridge server.
- Do not alter the UTM sequence or Guardian gates.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: Shared Bridge Platform Contract

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Produces: CLI `--platform auto|windows|linux` and `--token-file PATH`.
- Produces: `/health.platform` object with `name`, `session_type`, `display`, `scope`, and `desktop_control_ready`.
- Produces: validation portability fields `platform_tested`, `portable_actions`, `platform_specific_locators`, and `requires_windows_recalibration`.

- [ ] **Step 1: Write failing tests for Linux platform selection, token-file loading, X11 readiness, and portability metadata.**
- [ ] **Step 2: Run the focused helper tests and verify failures are caused by missing platform support.**
- [ ] **Step 3: Add platform parsing, platform-specific default paths, token-file loading, and X11 readiness without changing endpoint names.**
- [ ] **Step 4: Add Linux window focus through bounded `wmctrl`/`xdotool` subprocess calls; retain existing Windows activation logic.**
- [ ] **Step 5: Return explicit portability metadata from program validation and health.**
- [ ] **Step 6: Copy the primary server to the install path and verify byte identity.**
- [ ] **Step 7: Run the full Windows bridge helper suite.**

### Task 2: ATR-Owned Local Bridge Supervisor

**Files:**
- Create: `utils/local_pyautogui_bridge.py`
- Create: `tests/unit/test_local_pyautogui_bridge.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `LocalPyAutoGUIBridgeSupervisor(repo_root: Path, python_executable: Path | None = None)`.
- Produces: `status() -> dict[str, Any]`, `start() -> dict[str, Any]`, `stop() -> dict[str, Any]`, and `ensure_candidate(bridge: WindowsPyAutoGUIBridge, *, select: bool) -> dict[str, Any]`.
- Persists: `memory/local_pyautogui_bridge.token` and `runs/local_pyautogui_bridge/local_bridge.pid`.

- [ ] **Step 1: Write failing tests for token persistence, idempotent start, owned-process status, stop ownership, and local candidate registration.**
- [ ] **Step 2: Run focused tests and verify the supervisor is missing.**
- [ ] **Step 3: Implement token generation with mode `0600`, command construction, detached process launch, readiness polling, and log paths.**
- [ ] **Step 4: Implement PID ownership checks using the expected script path, port, and process command before termination.**
- [ ] **Step 5: Implement explicit `local_development` candidate registration with platform `linux` and scope `localhost`.**
- [ ] **Step 6: Run focused supervisor tests.**

### Task 3: Existing Bridge Client Candidate Metadata

**Files:**
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Test: `tests/unit/test_equipment_pyautogui_bridge.py`

**Interfaces:**
- Consumes: candidate payload fields `platform` and `scope`.
- Produces: connection status candidates preserving `platform`, `scope`, and `managed_local`.

- [ ] **Step 1: Write failing tests that save/select both local and Windows candidates without fallback.**
- [ ] **Step 2: Run focused tests and verify candidate metadata is currently dropped.**
- [ ] **Step 3: Preserve redacted platform/scope metadata in connection memory and status responses.**
- [ ] **Step 4: Run the complete equipment bridge unit suite.**

### Task 4: FastAPI Supervisor Endpoints And Proxy Selection

**Files:**
- Modify: `app/main.py`
- Test: `tests/unit/test_local_pyautogui_bridge.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Produces: `GET /api/equipment/windows/local-bridge/status`.
- Produces: `POST /api/equipment/windows/local-bridge/start`.
- Produces: `POST /api/equipment/windows/local-bridge/stop`.
- Produces: `POST /api/equipment/windows/local-bridge/select`.
- Reuses: `/equipment/windows/console` and `/equipment/windows/bridge-ui/*` against the explicitly selected candidate.

- [ ] **Step 1: Write failing API contract tests for status/start/stop/select.**
- [ ] **Step 2: Run tests and verify endpoints are absent.**
- [ ] **Step 3: Add one cached supervisor instance and the four bounded endpoints.**
- [ ] **Step 4: Ensure start registers but does not silently select the local candidate; select is explicit.**
- [ ] **Step 5: Verify the proxy uses the selected local URL and token from existing connection memory.**
- [ ] **Step 6: Run focused API and bridge tests.**

### Task 5: Equipment Workspace Local Bridge Controls

**Files:**
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/styles.css`
- Modify: `tests/ui/windows_equipment_browser_audit.py`

**Interfaces:**
- Consumes: the four `/api/equipment/windows/local-bridge/*` endpoints.
- Produces: a persistent `Local Development Bridge` card with Start, Stop, Health, Select, status, PID, platform, and localhost URL.

- [ ] **Step 1: Add failing browser assertions for local card controls, readable layout, and status rendering.**
- [ ] **Step 2: Run the browser audit and verify the local bridge controls are absent.**
- [ ] **Step 3: Add the compact card near Saved Connection without duplicating the Program Manager or UTM controls.**
- [ ] **Step 4: Add busy-state handling so each action stays disabled until its callback completes.**
- [ ] **Step 5: Refresh local and selected-candidate state together and keep Windows candidates unchanged.**
- [ ] **Step 6: Run 1920x1080 and 1366x768 Selenium audits and inspect screenshots.**

### Task 6: Installation And Operation Documentation

**Files:**
- Modify: `requirements.txt`
- Modify: `INSTALL/README.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/runtime/closed_loop_and_pages_reference.md`

**Interfaces:**
- Documents: Ubuntu packages `scrot`, `wmctrl`, `xdotool`, and Python packages `PyAutoGUI`, `python3-xlib`.
- Documents: local development workflow and Windows recalibration boundary.

- [ ] **Step 1: Add Python dependencies without changing existing pinned ML packages.**
- [ ] **Step 2: Add apt installation commands and X11/Wayland limitation.**
- [ ] **Step 3: Document Start -> Select -> Health -> program1 -> Program Manager -> Windows export workflow.**
- [ ] **Step 4: Document token, artifact, locator, program, PID, and log locations.**
- [ ] **Step 5: Run documentation link/path checks used by the repository.**

### Task 7: End-To-End Local Desktop Verification

**Files:**
- Test: `tests/ui/windows_bridge_gui_browser_audit.py`
- Output: `artifacts/ui/local_pyautogui_bridge/`
- Output: `runs/local_pyautogui_bridge/`

**Interfaces:**
- Consumes: completed supervisor, API, GUI, and shared bridge.
- Produces: browser screenshots, health response, program1 completion response, request audit, and process-stop evidence.

- [ ] **Step 1: Install required Ubuntu and Python dependencies.**
- [ ] **Step 2: Start ATR if required and start the local bridge through the Equipment API.**
- [ ] **Step 3: Select `local_development` and verify proxied Health reports Linux/X11 readiness.**
- [ ] **Step 4: Execute `program1` through the Equipment Workspace API and confirm bounded mouse movement plus `program1 completed`.**
- [ ] **Step 5: Use the proxied Program Manager to validate/register/run/delete one custom macro.**
- [ ] **Step 6: Stop the local bridge through the API and verify port 8766 closes while ATR stays running.**
- [ ] **Step 7: Run all touched unit, integration, and browser tests; run `git diff --check`; report residual Windows-only validation requirements.**
