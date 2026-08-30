# Windows Worker Remote Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Saved Worker 카드에서 Windows 브릿지 버전 확인, 검증된 업데이트, 자동 rollback을 수행한다.

**Architecture:** Linux가 release manifest를 소유하고 paired Worker의 인증된 update API로 bounded package를 전송한다. Windows는 staging만 담당하고 별도 Python updater가 process replacement, health verification, rollback을 수행한다.

**Tech Stack:** Python 3, FastAPI, stdlib HTTP server, SHA-256, subprocess, HTML/CSS/JavaScript

**Spec:** `docs/superpowers/specs/2026-08-28-windows-worker-remote-update-design.md`

## Global Constraints

- 공개키 전자서명 없이 pairing `internal_key` 인증과 SHA-256을 사용한다.
- 업데이트 가능한 상대경로는 release manifest와 Windows allowlist의 교집합으로 제한한다.
- 사용자 데이터는 업데이트 대상에 포함하지 않는다.
- apply 후 health 실패 시 자동 rollback한다.

---

### Task 1: Release Package Contract

**Files:**
- Create: `Pyautogui_server_for_window/release_manifest.json`
- Create: `utils/windows_bridge_release.py`
- Test: `tests/unit/test_windows_bridge_release.py`

**Interfaces:**
- Produces: `load_release_manifest() -> dict`, `build_release_package() -> dict`

- [x] Write tests for allowlisted files, digest generation, and path rejection.
- [x] Run tests and verify missing implementation failures.
- [x] Implement manifest loading and bounded package generation.
- [x] Run tests and verify pass.

### Task 2: Windows Staging And Updater

**Files:**
- Create: `Pyautogui_server_for_window/scripts/bridge_self_updater.py`
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Produces: authenticated `/update/status`, `/update/stage`, `/update/apply`, `/update/rollback`

- [x] Write failing tests for authentication scope, staging validation, recording gate, and updater backup/restore.
- [x] Implement bounded staging and status persistence.
- [x] Implement detached updater process with restart health check and rollback.
- [x] Run Windows helper tests.

### Task 3: Linux Worker Update Client And API

**Files:**
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_equipment_pyautogui_bridge.py`
- Test: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Produces: `worker_update_status`, `update_worker`, `rollback_worker` and Saved Worker HTTP API routes.

- [x] Write failing bridge and FastAPI tests with exact candidate selection and no fallback.
- [x] Implement release package transfer through existing internal-key headers.
- [x] Implement status/update/rollback routes.
- [x] Run bridge and API tests.

### Task 4: Saved Worker Controls

**Files:**
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/styles.css`
- Test: `tests/integration/test_live_gui_runtime_layout.py`
- Test: `tests/ui/windows_equipment_browser_audit.py`

**Interfaces:**
- Consumes: Worker update APIs from Task 3.
- Produces: per-worker Check Update, Update, Rollback controls and status.

- [x] Write failing DOM and endpoint contract tests.
- [x] Render per-worker version state and action buttons.
- [x] Disable only the active worker card during requests and refresh its version state after completion.
- [x] Run layout and Selenium audits.

### Task 5: Packaging And Documentation

**Files:**
- Modify: `Pyautogui_server_for_window/scripts/build_portable_release.py`
- Modify: `Pyautogui_server_for_window/README.md`
- Modify: `docs/device_bridges/windows_pyautogui_bridge.md`
- Test: `tests/unit/test_install_packaging.py`

**Interfaces:**
- Ensures the updater and release manifest ship with standard and portable packages.

- [x] Add packaging assertions for updater and manifest.
- [x] Synchronize the install server copy.
- [x] Document version check, update, rollback, and recovery behavior.
- [x] Run all affected Python, JavaScript, and browser tests.
