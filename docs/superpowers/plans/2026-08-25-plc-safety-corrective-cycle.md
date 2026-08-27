# PLC Safety Corrective Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Close the remaining fail-open PLC recovery paths and prove that the dedicated PLC Device Workspace is present in the runtime actually serving the GUI.

**Architecture:** Keep `PLCBridgeService` as the sole owner of D100-D102 and make every recovery request converge through that service before the Controller can resume/reset. Treat device `result_status` as authoritative physical-effect evidence, preserve one recovery transaction across re-E-STOP, and reject preflight during a handshake. The PLC Workspace remains `/plc`; deployment verification must distinguish the isolated worktree from the existing dirty checkout instead of overwriting user changes.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pytest/pytest-asyncio, JavaScript, Selenium.

**Spec:** `docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`

## Global Constraints

- The PC never writes `D100` and never writes `D101=0`.
- Allowed writes remain exact non-boolean integers: `D101=1`, `D102=0`, and `D102=1` only.
- Physical PLC input has priority over GUI controls.
- Resume/Reset cannot reach the Controller until service handshake completion verifies fresh `(D100,D101,D102) == (0,0,0)`.
- A second E-STOP cannot replace or orphan an acknowledged recovery transaction.
- `/api/plc/preflight` is read-only and rejects an active handshake.
- Live mode never silently selects virtual PLC transport.
- Existing changes in `/home/jin/autonomous_researcher` must not be overwritten or reverted.

---

### Task 1: Close Controller and PLC Recovery Authority Gaps

**Files:**
- Modify: `app/controller.py`
- Modify: `utils/plc_bridge_service.py`
- Modify: `tests/unit/test_controller_plc_safety.py`
- Modify: `tests/unit/test_plc_bridge_service.py`

**Interfaces:**
- Consumes: `tool_call_record.v1` fields `status`, `result_status`, and `failure_code`; `PLCBridgeService.status()` safety sources and handshake state.
- Produces: fail-closed readiness that rejects active `result_status`; idempotent E-STOP synchronization that preserves an active recovery transaction; service-owned recovery completion.

- [x] **Step 1: Add failing readiness tests**

Add a test proving `plc_recovery_readiness()` rejects an action-shielded record with `status="completed"` and `result_status` in `started`, `running`, `active`, `executing`, `in_progress`, or `modified`.

- [x] **Step 2: Run the readiness tests and verify RED**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/unit/test_controller_plc_safety.py -k 'result_status or physical_command_active'`

Expected: the new `result_status` case fails because only `status` is inspected.

- [x] **Step 3: Add failing transaction-preservation tests**

Add tests proving `sync_estop()` during an acknowledged transaction does not replace its transaction ID/phase, does not strand `D102=1`, and records the new source without losing timeout/completion handling.

- [x] **Step 4: Run the service tests and verify RED**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/unit/test_plc_bridge_service.py -k 'reestop or acknowledged or transaction_preserved'`

Expected: the new re-E-STOP test fails because `sync_estop()` replaces `self._transaction`.

- [x] **Step 5: Implement minimal fail-closed behavior**

Normalize both `status` and `result_status` into physical-effect evidence. Preserve the active recovery transaction when synchronizing another E-STOP, merge the new source/details into bounded evidence, and ensure the handshake either completes with a fresh all-zero readback or terminally relatches both service and Controller.

- [x] **Step 6: Run focused and full PLC unit tests**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/unit/test_controller_plc_safety.py tests/unit/test_plc_bridge_service.py`

- [x] **Step 7: Commit**

```bash
git add app/controller.py utils/plc_bridge_service.py tests/unit/test_controller_plc_safety.py tests/unit/test_plc_bridge_service.py
git commit -m "fix: preserve fail-closed PLC recovery authority"
```

### Task 2: Route GUI Recovery and Preflight Through the PLC Gate

**Files:**
- Modify: `app/main.py`
- Modify: `utils/plc_bridge_service.py`
- Modify: `tests/integration/test_plc_bridge_api.py`
- Modify: `tests/integration/test_plc_safety_e2e.py`

**Interfaces:**
- Consumes: service recovery transaction and Controller callbacks.
- Produces: GUI recovery routes that cannot bypass PLC authority; degraded E-STOP synchronization evidence; preflight handshake rejection.

- [x] **Step 1: Add failing API tests**

Cover all three GUI route families. Prove mouse `gui_estop` stays Controller-local, does not write D101, and remains recoverable through GUI Resume/Reset. Prove `plc_pb2` and incomplete PLC handshakes still return a bounded conflict.

- [x] **Step 2: Add failing preflight test**

Prove `/api/plc/preflight` returns HTTP 409 with `PLC_PREFLIGHT_HANDSHAKE_ACTIVE` and performs no reconciliation/read/write while a handshake is active.

- [x] **Step 3: Run new integration tests and verify RED**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/integration/test_plc_bridge_api.py tests/integration/test_plc_safety_e2e.py -k 'recovery_route or degraded_sync or preflight_handshake'`

- [x] **Step 4: Implement one recovery gateway**

Add a bounded service method used by every GUI Resume/Reset route. It rejects physical `plc_pb2` latches and incomplete handshakes, while forwarding a Controller-local `gui_estop` recovery when no physical latch exists. Mouse GUI E-STOP must not synchronize D101.

- [x] **Step 5: Run integration and E2E tests**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/integration/test_plc_bridge_api.py tests/integration/test_plc_safety_e2e.py`

- [x] **Step 6: Commit**

```bash
git add app/main.py utils/plc_bridge_service.py tests/integration/test_plc_bridge_api.py tests/integration/test_plc_safety_e2e.py
git commit -m "fix: gate GUI recovery through PLC handshake"
```

### Task 3: Prove PLC Workspace Runtime Exposure

**Files:**
- Modify: `tests/integration/test_plc_bridge_api.py`
- Modify: `tests/ui/plc_workspace_browser_audit.py`
- Modify: `docs/device_bridges/plc_safety_bridge.md`

**Interfaces:**
- Consumes: `/plc`, `/api/plc/status`, `web/templates/index.html`, and the serving checkout path.
- Produces: route/card/browser proof plus operator guidance that the server must run from the branch containing the PLC implementation.

- [x] **Step 1: Add route and dashboard exposure assertions**

Assert `/plc` returns the workspace shell, `/` contains `btn-open-plc`, and the OpenAPI contract contains bounded `/api/plc/*` routes but no generic write route.

- [x] **Step 2: Add browser navigation audit**

Open the dashboard at 1920x1080, click `Open PLC Workspace`, verify the new page contains Connection, Register State, Safety State, Transport Health, and Event History, and verify no horizontal overflow or browser errors.

- [x] **Step 3: Run UI tests**

Run: `/home/jin/autonomous_researcher/.venv/bin/python -m pytest -q tests/integration/test_plc_bridge_api.py tests/ui/plc_workspace_browser_audit.py`

- [x] **Step 4: Document runtime checkout diagnosis**

Record that a server whose `/proc/<pid>/cwd` is `/home/jin/autonomous_researcher` will not expose worktree-only routes until the reviewed commits are integrated or that worktree is started explicitly. Do not instruct operators to overwrite a dirty checkout.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_plc_bridge_api.py tests/ui/plc_workspace_browser_audit.py docs/device_bridges/plc_safety_bridge.md
git commit -m "test: verify PLC workspace runtime exposure"
```

### Task 4: Final Software Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-08-25-plc-safety-corrective-cycle.md`

- [x] **Step 1: Run focused PLC regression**

Run all PLC unit, API, E2E, Live GUI, and browser audit tests.

- [x] **Step 2: Run static validation**

Run `py_compile`, `node --check`, documentation validation, and `git diff --check`.

- [x] **Step 3: Request whole-cycle review**

Review every Global Constraint and reject physical validation if any Critical/Important finding remains.

- [x] **Step 4: Preserve the isolated branch pending integration**

Do not merge into `/home/jin/autonomous_researcher`, restart its server, or operate physical PLC registers without explicit approval after review passes.

## Completion Evidence

- Corrective branch HEAD: `a6b6d29`
- PLC/Controller/API/E2E/Live GUI/browser regression: `236 passed`
- Documentation validation: passed
- Python `py_compile`: passed
- JavaScript `node --check`: passed
- `git diff --check`: passed
- Independent final review: no Critical, Important, or Minor findings; approved for software-only integration
- Physical PLC validation: not performed and remains separately pending
- Serving checkout `/home/jin/autonomous_researcher`: intentionally not modified or restarted because it contains unrelated user changes
