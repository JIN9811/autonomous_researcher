# Lab Equipment Agent Consolidation Implementation Plan

> **Required execution skill:** Use `superpowers:executing-plans` and verify every task before moving on.

**Goal:** Consolidate Lab Equipment execution, recording-to-Skill authoring, evidence, and status projection around one Linux-owned Equipment Runtime while preserving the validated bounded PyAutoGUI execution path.

**Architecture:** `LabEquipmentAgent` remains the high-level workflow owner. A Linux `EquipmentRuntimeService` becomes the single middle-level lifecycle and execution-record owner. Existing local/Windows PyAutoGUI bridges remain low-level deterministic workers. UTM remains the first Equipment Profile, not an agent-wide hardcoded execution path.

**Tech Stack:** Python 3.12, FastAPI, existing bridge HTTP contracts, JSON artifacts, vanilla HTML/CSS/JavaScript, pytest, Playwright/Selenium browser audit where available.

**Source specification:** `docs/strategy/2026-08-27-windows-lab-equipment-consolidation-report.md`

## Global Constraints

- Baseline is commit `a5e82b9`; it has already been pushed to `origin/agent/windows-bridge-delete-proxy`.
- Do not commit implementation changes after this baseline unless the user explicitly approves them.
- Do not add a second PyAutoGUI executor or silent direct-UTM fallback.
- Preserve existing program, Skill, Guardian, Test/Live, CUI, Live GUI, and Runtime IDE contracts.
- Windows must not run an LLM or own workflow completion decisions.
- Physical equipment is not actuated during automated verification unless explicitly authorized.

### Task 1: Freeze Existing Success Contracts

**Files:**
- Modify: `tests/unit/test_equipment_agent.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`
- Modify: `tests/integration/test_equipment_skill_api.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Steps:**
1. Add regression tests proving closed-loop Equipment execution remains owned by `LabEquipmentAgent` and resolves to one bounded PyAutoGUI worker path.
2. Add tests proving legacy registered programs and versioned Skills both resolve without an implicit direct-UTM fallback.
3. Add tests defining one canonical execution-state schema and status projection contract.
4. Run the focused tests and confirm the new assertions fail for the missing consolidation behavior.

### Task 2: Add The Canonical Equipment Runtime Service

**Files:**
- Create: `utils/equipment_runtime_service.py`
- Create: `tests/unit/test_equipment_runtime_service.py`
- Modify: `utils/equipment_skill_runtime.py`

**Steps:**
1. Implement an atomic JSON execution store keyed by `execution_id` with experiment, specimen, profile, Skill/program, worker, mode, lifecycle, evidence, completion, recovery, and handoff fields.
2. Implement strict lifecycle transitions for resolve, preflight, execute, verify, recover, complete, block, abort, and escalate.
3. Implement one execution snapshot projection consumed by Agent, API, GUI, CUI, and Runtime IDE.
4. Make `EquipmentSkillRegistry.begin_execution` and transitions delegate or synchronize through the canonical service without changing public Skill responses.
5. Run unit tests.

### Task 3: Route Existing Agent And APIs Through The Runtime

**Files:**
- Modify: `agents/equipment_agent.py`
- Modify: `app/main.py`
- Modify: `app/bootstrap.py`
- Modify: `app/controller.py`
- Modify: `mcp_tools/equipment_tools.py`
- Modify: `tests/unit/test_equipment_agent.py`
- Modify: `tests/integration/test_equipment_skill_api.py`

**Steps:**
1. Resolve the exact Equipment Profile, Skill/program version, mode, and worker once at stage entry.
2. Execute through the existing bounded `equipment.pyautogui.run` bridge contract only.
3. Persist raw worker results and evidence, then perform completion interpretation exactly once in the runtime service.
4. Project the canonical result into the existing `AgentResult`, equipment report, Analysis handoff, and controller events.
5. Add read-only status/list APIs for current and historical executions.
6. Verify legacy program and Skill execution tests.

### Task 4: Add Bounded Time-Series Recording Evidence

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify: `tests/unit/test_install_packaging.py`

**Steps:**
1. Add a bounded rolling frame buffer with configurable 2-5 FPS capture and 20-30 second retention.
2. Store low-cost frame metadata continuously during recording while retaining only bounded image bytes.
3. On input events and exceptions, persist synchronized keyframes plus the relevant pre/post error window.
4. Keep successful normal execution free of continuous LLM or network calls.
5. Emit a versioned recording manifest that references event data, keyframes, and bounded visual windows.
6. Keep portable and install server copies in verified parity.
7. Run focused recording and packaging tests.

### Task 5: Complete Recording-To-Skill Transfer And Deployment

**Files:**
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Modify: `app/main.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`
- Modify: `tests/integration/test_equipment_skill_api.py`

**Steps:**
1. Accept the versioned time-series recording package while preserving v1/v2 compatibility.
2. Snapshot the selected Live GUI inference backend for annotation without storing secrets or allowing fallback.
3. Compile deterministic bounded actions and checkpoints from the recording package.
4. Validate deployment hashes and transfer only validated Skill programs to the selected worker.
5. Persist deployment identity in the canonical execution record.
6. Verify create, annotate, compile, validate, deploy, test, and execute lifecycle tests.

### Task 6: Generalize Equipment Profiles And Optional Vision Link

**Files:**
- Modify: `utils/equipment_profiles.py`
- Modify: `configs/devices.yaml`
- Modify: `agents/equipment_agent.py`
- Modify: `tests/unit/test_equipment_agent.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Steps:**
1. Keep UTM-specific names, windows, save procedures, and completion rules in `utm_windows_v1` profile data.
2. Make the agent consume generic profile fields and declare UTM-specific behavior only through the selected profile/Skill.
3. Add an explicit optional Vision Link contract with request identity, freshness, result, and evidence references.
4. Verify Vision-disabled profiles execute without a hidden dependency and Vision-enabled profiles fail explicitly when required evidence is absent.

### Task 7: Project One Runtime Into Live GUI, Workspace, CUI, And IDE

**Files:**
- Modify: `app/templates/windows_equipment.html`
- Modify: `app/static/windows_equipment.js`
- Modify: `app/static/windows_equipment.css`
- Modify: `app/static/planning.js`
- Modify: `app/templates/runtime_ide.html`
- Modify: `app/static/runtime_ide.js`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/ui/windows_bridge_gui_browser_audit.py`

**Steps:**
1. Render Agentic Progress stages from the canonical execution snapshot rather than independent frontend state.
2. Show recording transfer, annotation, validation, deployment, execution, checkpoint, recovery, and handoff states without duplicating decisions.
3. Keep the Windows console lightweight: Bridge status, Program Manager, Record Skill, and local settings only.
4. Expose the same execution identity and lifecycle in Live GUI, Equipment Workspace, CUI output, and Runtime IDE.
5. Run static integration tests and browser audit at 1920x1080.

### Task 8: Full Verification And Documentation Reconciliation

**Files:**
- Modify: `docs/agents/equipment_agent.md`
- Modify: `docs/device_bridges/windows_pyautogui_bridge.md`
- Modify: `docs/guides/` relevant Equipment guide files
- Modify: `REQUIREMENTS.md` if dependencies change

**Steps:**
1. Run focused unit and integration suites after each task.
2. Run the broader repository suite and compare failures with the recorded 11 baseline failures.
3. Run local/simulated Equipment end-to-end flow without physical actuation.
4. Run browser layout and interaction audit.
5. Reconcile system documentation with the final code and report any unverified physical-device behavior explicitly.
6. Leave all implementation changes uncommitted for user review.
