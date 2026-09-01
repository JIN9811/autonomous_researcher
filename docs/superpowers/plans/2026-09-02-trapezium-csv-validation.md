# TRAPEZIUM CSV Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse TRAPEZIUM raw CSV exports consistently and validate the exact artifact emitted by the Save block.

**Architecture:** A shared Linux parser owns encoding, header discovery, canonical mapping, and signal checks. The standalone Windows worker mirrors that contract and is protected by parity tests. The validation Skill consumes the preceding save path rather than a legacy fixed export directory.

**Tech Stack:** Python 3.12, standard-library `csv`, pytest, FastAPI equipment Skill registry, Windows PyAutoGUI worker.

**Spec:** `docs/superpowers/specs/2026-09-02-trapezium-csv-validation-design.md`

## Global Constraints

- Preserve vendor CSV bytes exactly.
- Keep canonical UTF-8 CSV compatibility.
- Do not restart the main server or LeRobot training.
- Do not stage or modify the reference MP4.

---

### Task 1: Shared TRAPEZIUM parser

**Files:**
- Create: `utils/utm_csv.py`
- Modify: `mcp_tools/utm_tools.py`
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Modify: `agents/equipment_agent.py`
- Test: `tests/unit/test_utm_csv.py`

**Interfaces:**
- Produces: `probe_utm_csv_bytes(data: bytes) -> dict[str, Any]` and `probe_utm_csv(path: Path) -> dict[str, Any]`.

- [ ] Write a failing test using a literal CP949 TRAPEZIUM three-row header fixture.
- [ ] Run the test and confirm it fails because the shared parser does not exist.
- [ ] Implement decoding, header discovery, role mapping, numeric parsing, and quality checks.
- [ ] Replace Linux parser copies with the shared function.
- [ ] Run parser and affected component tests.

### Task 2: Windows worker parser parity

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Consumes: the same byte-level CSV contract as `utils.utm_csv.probe_utm_csv_bytes`.
- Produces: matching canonical probe metadata from the standalone worker.

- [ ] Write a failing worker test with the same CP949 fixture and literal expected mappings.
- [ ] Run it and confirm the legacy first-row parser fails.
- [ ] Implement the standalone equivalent and synchronize both worker copies.
- [ ] Run worker tests and an explicit Linux/worker parity assertion.

### Task 3: Exact-path validation Skill

**Files:**
- Modify: `utils/equipment_utm_skills.py`
- Modify: `graphs/modules/equipment/equipment_skill_flows.json`
- Test: `tests/unit/test_equipment_utm_skills.py`
- Test: `tests/unit/test_equipment_agentic_task.py`

**Interfaces:**
- Consumes: `raw_csv_path`, SHA-256, row count, and canonical probe metadata from Save.
- Produces: a non-actuating validation result bound to the exact artifact.

- [ ] Write failing tests proving the legacy `C:/ATR/utm_exports` glob is rejected and the exact save path is used.
- [ ] Implement and publish the new validation Skill version.
- [ ] Deploy it, rebind the flow, remove the old version, and verify hashes.
- [ ] Run the new Skill against the previously saved TRAPEZIUM CSV and verify completion evidence.

### Task 4: Regression and handoff

**Files:**
- Verify all files above.

- [ ] Run focused unit and integration suites.
- [ ] Run `git diff --check` and worker-copy byte comparison.
- [ ] Verify main and LeRobot process identities are unchanged.
- [ ] Commit only intended files and report the deployed version and artifact evidence.

