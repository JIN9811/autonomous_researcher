# Recorded Equipment Skill And Exception Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned, recordable Equipment Skills that execute through the existing PyAutoGUI program boundary and use the selected ATR model only for annotation or bounded exception recovery.

**Architecture:** Linux remains authoritative for Skill packages, versions, execution state, and model provenance. The Windows bridge records operator demonstrations and executes compiled `atr.pyautogui_program.v1` segments; `EquipmentAgent.run()` remains the only agent entry and `equipment.pyautogui.run` remains the only actuation tool. Program Manager gains RECORD and SKILLS work areas backed by the same HTTP contracts used by CUI callers.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, existing ToolRegistry/WindowsPyAutoGUIBridge, stdlib HTTP server, optional `pynput`, vanilla HTML/CSS/JavaScript, pytest.

## Global Constraints

- Preserve the closed-loop stage order and do not add a top-level agent or LangGraph stage.
- Preserve `atr.pyautogui_program.v1` and its 100-action segment limit.
- Keep normal Skill execution deterministic and free of LLM calls.
- Snapshot the active provider and exact model for annotation and recovery; never silently fall back.
- Keep Windows free of API keys and model selection controls.
- Do not integrate Graphify in this implementation.
- Do not restart running ATR, vLLM, printer, robot, camera, or Windows bridge processes during unit verification.
- Leave all implementation changes uncommitted for operator review.

---

### Task 1: Skill Contracts And Authoritative Registry

**Files:**
- Create: `utils/equipment_skill_runtime.py`
- Create: `tests/unit/test_equipment_skill_runtime.py`

**Interfaces:**
- Produces: `EquipmentSkillRegistry(root: Path)`, `validate_skill_package(payload)`, `compile_recording_actions(events)`, `split_program_segments(actions, limit=100)`, `build_exception_packet(...)`.
- Persists: `memory/equipment_skills/<skill_id>/<version>/manifest.json`, `workflow.json`, `annotations.json`, `programs/*.json`, and atomic runtime state files.

- [ ] Write failing tests for schema validation, safe IDs/versions, exact hash verification, atomic version persistence, 100-action segmentation, recovery allowlist, and idempotent execution sequence IDs.
- [ ] Run `pytest -q tests/unit/test_equipment_skill_runtime.py` and confirm missing-module failures.
- [ ] Implement immutable package records, canonical SHA-256 hashing, atomic JSON writes, deterministic event compilation, and state transition validation.
- [ ] Re-run the unit test and confirm all contract tests pass.

### Task 2: Windows Demonstration Recorder

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Produces bridge routes: `POST /recordings/start`, `POST /recordings/checkpoint`, `POST /recordings/stop`, `POST /recordings/{id}/save`, `GET /recordings`, `GET /recordings/{id}`.
- Recording object: `atr.equipment_recording.v1` with `recording_id`, target window, monotonic event timestamps, checkpoints, status, and content hash.

- [ ] Add failing helper tests for single-active-session enforcement, redacted key events, checkpoint screenshots, stop idempotency, and persisted reload.
- [ ] Run the focused helper tests and confirm failures.
- [ ] Implement a lock-protected recorder with lazy optional `pynput` listeners, test event injection, screenshot checkpoints, and atomic JSON persistence under the configured recording root.
- [ ] Mirror the standalone Windows server into `install/` and verify the two files are byte-identical.
- [ ] Re-run the focused helper tests and syntax checks.

### Task 3: Draft Creation, Annotation, Compilation, And Validation

**Files:**
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`

**Interfaces:**
- Produces registry methods: `create_draft(recording, target_profile, model_snapshot)`, `annotate(skill_id, version, annotations)`, `compile(skill_id, version)`, `validate(skill_id, version)`, `set_lifecycle(...)`.
- Compiled segments use exact `atr.pyautogui_program.v1` payloads and stable IDs `<skill_id>_<version>_segment_<n>`.

- [ ] Add failing tests that Program 1 recording becomes a Draft Skill, uncertain annotations require review, compile emits bounded segments, and validation rejects hash or profile mismatches.
- [ ] Implement deterministic annotation defaults, operator-editable confidence/review fields, compilation, validation, lifecycle guards, and audit entries.
- [ ] Run the full Skill runtime unit suite.

### Task 4: Linux Skill API And Shared Model Snapshot

**Files:**
- Modify: `app/main.py`
- Create: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Adds `/api/equipment/skills` list/detail/draft/annotate/compile/validate/deploy/test/disable/delete routes and recording intake routes.
- Uses `controller._deps.agent_context` to snapshot `provider`, `model`, endpoint profile, and capability without exposing secrets.
- Direct annotation calls only the snapshotted backend/model and does not invoke configured fallback attempts.

- [ ] Add failing TestClient coverage for complete lifecycle, refresh persistence, exact-version operations, no secret exposure, and explicit selected-model-unavailable errors.
- [ ] Implement request models, registry dependency, public projections, and a no-fallback annotation helper.
- [ ] Run API and existing local bridge integration tests.

### Task 5: Existing Bridge Deployment And Deterministic Execution

**Files:**
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Modify: `mcp_tools/equipment_tools.py`
- Modify: `agents/equipment_agent.py`
- Modify: `graphs/modules/equipment/module.yaml`
- Test: `tests/unit/test_equipment_pyautogui_bridge.py`
- Test: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Adds non-actuating bridge helpers for exact program registration/deletion and Skill status.
- Equipment Agent resolves an exact validated Skill to segment IDs and invokes only `equipment.pyautogui.run` for each segment.
- Successful deterministic execution never calls `ctx.complete`.

- [ ] Add failing bridge tests for exact-version deployment and hash mismatch rejection.
- [ ] Add failing agent tests proving segment order, no LLM call on success, no duplicate actuation after retry/reconnect, and no route fallback.
- [ ] Implement deployment helpers and the Skill branch inside the existing Equipment Agent path.
- [ ] Run bridge, Equipment Agent, and LangGraph runtime tests.

### Task 6: Bounded Exception Recovery

**Files:**
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `agents/equipment_agent.py`
- Modify: `policies/guardian_gate.py`
- Test: `tests/unit/test_equipment_skill_runtime.py`
- Test: `tests/unit/test_equipment_agent.py`
- Test: `tests/unit/test_guardian_gate.py`

**Interfaces:**
- Exception packet schema: `atr.equipment_skill_exception.v1`.
- Recovery response schema: `atr.equipment_skill_recovery.v1` with allowlisted tool/action, expected verification, confidence, and bounded attempts.
- States: `RUNNING`, `CHECKPOINT_VERIFY`, `EXCEPTION`, `RECOVERING`, `RECOVERY_VERIFY`, `RESUMED`, `COMPLETED`, `ESCALATED`, `ABORTED`.

- [ ] Add failing tests for focus loss, missing locator evidence, one no-fallback model decision, Guardian rejection, successful verification/resume, and attempts exhausted escalation.
- [ ] Implement exception evidence, no-fallback selected-model call, recovery allowlist, Guardian decision input, verification, candidate persistence, and Operator Attention projection.
- [ ] Run focused recovery and Guardian tests.

### Task 7: Program Manager RECORD/SKILLS UI And Cross-Surface Projection

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `graphs/modules/equipment/ui.yaml`
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Test: `tests/ui/windows_bridge_gui_browser_audit.py`
- Test: `tests/ui/windows_equipment_browser_audit.py`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Program Manager tabs: `PROGRAMS`, `RECORD`, `SKILLS`.
- Skill cards show exact version, lifecycle, target profile, model provenance, deployment state, and last test only; editor shows steps, locators, checkpoints, confidence, and actions.
- GUI actions call the same backend routes used by CUI.

- [ ] Add failing DOM/source tests for tabs, recording controls, draft cards, lifecycle actions, refresh persistence, and no API key/model endpoint in Windows UI.
- [ ] Implement compact tabs, recording status, Skill registry cards/editor, lifecycle controls, and Equipment Workspace/Live GUI runtime state projection.
- [ ] Mirror the Windows server file, run JavaScript syntax checks, and run browser audit tests at 1920x1080 without starting physical equipment.

### Task 8: Documentation And Verification

**Files:**
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`
- Modify: `docs/runtime/current_code_snapshot.md`
- Modify: `docs/tutorials/user_manual.ko.md`
- Modify: `REQUIREMENTS.md`

**Interfaces:**
- Documents GUI/CUI parity, Windows optional recorder dependency, storage, model snapshot semantics, recovery limits, failure codes, and Program 1 smoke procedure.

- [ ] Update operator documentation with exact routes, commands, lifecycle, paths, and troubleshooting.
- [ ] Run `python -m py_compile` on changed Python files and `node --check` on changed JavaScript files.
- [ ] Run focused unit/integration/UI tests plus `git diff --check`.
- [ ] Confirm `git status` contains only uncommitted Skill implementation changes and report them without committing.
