# PLC Safety Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, automatically reconnecting Mitsubishi PLC safety layer that maps D101 to E-STOP, D100 values to physical Resume/Reset decisions, and D102 to the PC acknowledgement handshake without replacing existing GUI/Controller behavior when the PLC is offline.

**Architecture:** A singleton `PLCBridgeService` owns one `pymcprotocol.Type3E` connection and polls D100-D102 every 200 ms in a worker thread. A pure state machine decodes snapshots and drives source-aware Controller emergency methods; APIs and GUIs consume cached server state rather than opening PLC connections. Physical PLC connectivity is optional, but an already observed PLC E-STOP remains latched across disconnect.

**Tech Stack:** Python 3.10+, FastAPI, asyncio/threading, pymcprotocol Type3E, Pydantic, vanilla HTML/CSS/JavaScript, pytest, Selenium browser audits.

**Spec:** `docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`

## Global Constraints

- Default PLC endpoint is `192.168.50.90:4999`.
- Poll D100-D102 as one contiguous three-word snapshot every `0.2 s`.
- D100 is PLC-owned: `0=none`, `1=Resume`, `2=Reset`.
- D101 is shared set-only from PC: PLC or PC may set one; PC never writes zero.
- D102 is PC-owned acknowledgement: only zero or one may be written.
- PLC physical input has priority over GUI recovery controls.
- PLC offline from a normal snapshot preserves existing GUI/Controller behavior.
- A previously observed PLC E-STOP remains latched across disconnect.
- Live mode never switches to virtual PLC automatically.
- Guardian policy and closed-loop stage order remain unchanged.
- Do not create generic PLC register read/write APIs.
- Do not modify unrelated dirty-worktree files or commit unrelated changes.

---

## File Structure

| Path | Responsibility |
|---|---|
| `configs/plc.yaml` | Tracked non-secret defaults and register map |
| `device_bridges/plc_bridge.py` | Production/virtual transports, snapshot type, and bounded bridge operations |
| `utils/plc_safety_state.py` | Pure register decoder and recovery-handshake state machine |
| `utils/plc_bridge_service.py` | Singleton poll/reconnect worker, cached status, Controller callbacks, persistence |
| `app/controller.py` | Source-aware E-STOP/Resume/Reset methods and terminal-error notification hook |
| `app/main.py` | Service lifecycle, bounded PLC APIs, workspace route |
| `web/templates/plc.html` | Dedicated PLC Device Workspace |
| `web/static/plc.js` | PLC workspace rendering and test-mode actions |
| `web/static/plc.css` | PLC workspace-specific layout |
| `web/templates/index.html`, `web/static/app.js` | Main Device Workspace card/status |
| `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css` | Live GUI PLC status and source-aware recovery controls |
| `graphs/configs/atr_closed_loop.yaml` | Non-stage PLC device-bridge metadata for Runtime IDE |
| `tests/unit/test_plc_safety_state.py` | Pure state-machine coverage |
| `tests/unit/test_plc_bridge.py` | Transport and write-allowlist coverage |
| `tests/integration/test_plc_bridge_api.py` | API/lifecycle/Controller integration coverage |
| `tests/integration/test_live_gui_runtime_layout.py` | Static Live GUI contract assertions |
| `tests/ui/plc_workspace_browser_audit.py` | Browser layout and interaction audit |
| `docs/device_bridges/plc_safety_bridge.md` | Operator-facing setup, behavior, and troubleshooting |
| `requirements.txt`, `pyproject.toml`, `REQUIREMENTS.md` | `pymcprotocol` and PLC environment prerequisites |

### Task 1: Pure PLC Register State Machine

**Files:**
- Create: `utils/plc_safety_state.py`
- Create: `tests/unit/test_plc_safety_state.py`

**Interfaces:**
- Produces: `PLCRegisterSnapshot`, `PLCSafetyState`, `PLCCommand`, `decode_snapshot(previous, current) -> PLCTransition`.
- Consumes: no network or Controller dependencies.

- [ ] **Step 1: Write failing register-decoding tests**

```python
def test_d101_latches_estop_and_d100_decodes_only_inside_estop():
    normal = PLCRegisterSnapshot(d100=0, d101=0, d102=0, sequence=1, received_monotonic=1.0)
    estop = PLCRegisterSnapshot(d100=0, d101=1, d102=0, sequence=2, received_monotonic=1.2)
    resume = PLCRegisterSnapshot(d100=1, d101=1, d102=0, sequence=3, received_monotonic=1.4)
    assert decode_snapshot(normal, estop).event == "estop_latched"
    assert decode_snapshot(estop, resume).command is PLCCommand.RESUME

def test_command_without_estop_is_protocol_fault():
    snapshot = PLCRegisterSnapshot(d100=1, d101=0, d102=0, sequence=1, received_monotonic=1.0)
    assert classify_snapshot(snapshot).failure_code == "PLC_COMMAND_WITHOUT_ESTOP"
```

- [ ] **Step 2: Run tests and confirm they fail because the module does not exist**

Run: `pytest -q tests/unit/test_plc_safety_state.py`

Expected: collection fails with `ModuleNotFoundError: utils.plc_safety_state`.

- [ ] **Step 3: Implement immutable state types and decoder**

Implement exact enums and dataclasses:

```python
class PLCCommand(str, Enum):
    NONE = "none"
    RESUME = "resume"
    RESET = "reset"

class PLCSafetyState(str, Enum):
    DISCONNECTED = "disconnected"
    NORMAL = "normal"
    ESTOP_LATCHED = "estop_latched"
    RESUME_REQUESTED = "resume_requested"
    RESET_REQUESTED = "reset_requested"
    HANDSHAKE_ASSERTED = "handshake_asserted"
    RELEASE_OBSERVED = "release_observed"
    PROTOCOL_FAULT = "protocol_fault"
```

Reject values outside the spec, deduplicate unchanged D100 requests, and keep decoding free of I/O.

- [ ] **Step 4: Run the focused tests**

Run: `pytest -q tests/unit/test_plc_safety_state.py`

Expected: all tests pass.

- [ ] **Step 5: Commit only this task's files**

```bash
git add utils/plc_safety_state.py tests/unit/test_plc_safety_state.py
git commit -m "feat: define PLC safety register state machine"
```

### Task 2: Bounded Production And Virtual PLC Bridge

**Files:**
- Create: `configs/plc.yaml`
- Create: `device_bridges/plc_bridge.py`
- Create: `tests/unit/test_plc_bridge.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `REQUIREMENTS.md`

**Interfaces:**
- Consumes: state types from Task 1.
- Produces: `PLCTransport`, `PymcProtocolTransport`, `VirtualPLCTransport`, and `PLCBridge(BaseBridge)`.

- [ ] **Step 1: Write failing tests for atomic reads and the write allowlist**

```python
def test_bridge_reads_three_words_atomically(fake_transport):
    fake_transport.words = [2, 1, 0]
    snapshot = PLCBridge(fake_transport).read_snapshot()
    assert (snapshot.d100, snapshot.d101, snapshot.d102) == (2, 1, 0)
    assert fake_transport.read_calls == [("D100", 3)]

@pytest.mark.parametrize("device,value", [("D100", 1), ("D101", 0), ("D102", 2), ("D200", 1)])
def test_bridge_rejects_unapproved_writes(fake_transport, device, value):
    with pytest.raises(PLCWriteRejected):
        PLCBridge(fake_transport).write_register(device, value)
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/unit/test_plc_bridge.py`

Expected: module import fails.

- [ ] **Step 3: Implement transport and bridge boundaries**

Use `batchread_wordunits(headdevice="D100", readsize=3)` and
`batchwrite_wordunits(headdevice=device, values=[value])`. Permit only
`("D101", 1)`, `("D102", 0)`, and `("D102", 1)`.

The virtual transport must emulate ladder release:

```python
if device == "D102" and value == 1 and self.words["D101"] == 1 and self.words["D100"] in {1, 2}:
    self.words["D100"] = 0
    self.words["D101"] = 0
```

- [ ] **Step 4: Declare defaults and dependency**

Create `configs/plc.yaml` with the exact values from the spec and add a pinned-compatible `pymcprotocol` requirement. Document that Conda environment `plc` is the validated diagnostic environment while the ATR server imports the package in-process.

- [ ] **Step 5: Run unit tests and import probe**

Run:

```bash
pytest -q tests/unit/test_plc_bridge.py tests/unit/test_plc_safety_state.py
python -c 'import pymcprotocol; from device_bridges.plc_bridge import PLCBridge'
```

Expected: tests pass and import exits zero.

- [ ] **Step 6: Commit task files only**

```bash
git add configs/plc.yaml device_bridges/plc_bridge.py tests/unit/test_plc_bridge.py requirements.txt pyproject.toml REQUIREMENTS.md
git commit -m "feat: add bounded Mitsubishi PLC bridge"
```

### Task 3: Singleton Polling, Reconnect, And Transaction Service

**Files:**
- Create: `utils/plc_bridge_service.py`
- Create: `tests/unit/test_plc_bridge_service.py`

**Interfaces:**
- Consumes: `PLCBridge`, `PLCRegisterSnapshot`, Controller callback protocol.
- Produces: `PLCBridgeService.start()`, `.shutdown()`, `.status()`, `.preflight()`, `.set_terminal_estop()`, and virtual input helpers.

- [ ] **Step 1: Write failing service tests**

Cover one poll owner, change-only event emission, normal disconnect fallback, latched-E-STOP disconnect preservation, reconnect reconciliation, and D102 handshake timeout.

```python
async def test_normal_disconnect_preserves_legacy_controls(service, controller_probe):
    await service.accept_snapshot(words=(0, 0, 0))
    await service.mark_disconnected("socket closed")
    assert service.status()["plc_layer_active"] is False
    assert controller_probe.emergency_stop_calls == []

async def test_disconnect_after_d101_keeps_local_latch(service, controller_probe):
    await service.accept_snapshot(words=(0, 1, 0))
    await service.mark_disconnected("socket closed")
    assert service.status()["safety_state"] == "estop_latched"
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/unit/test_plc_bridge_service.py`

- [ ] **Step 3: Implement one worker and cached status**

Run synchronous bridge calls through `asyncio.to_thread`, serialize writes with one lock, poll at 0.2 seconds, and reconnect with bounded backoff. Store transaction JSON under `memory/plc_bridge_state.json` using temporary-file replace.

- [ ] **Step 4: Implement Resume/Reset handshake**

Resume sequence: validate callback, persist, D102=1, observe D100/D101 zero, D102=0, invoke resume callback. Reset uses the same handshake and then invokes reset callback. Never auto-acknowledge a D100 command after reconnect without matching recoverable Controller context.

- [ ] **Step 5: Run service tests including leak guard**

Run: `pytest -q tests/unit/test_plc_bridge_service.py`

Expected: all pass; a 100-poll test has one worker and bounded event history.

- [ ] **Step 6: Commit task files only**

```bash
git add utils/plc_bridge_service.py tests/unit/test_plc_bridge_service.py
git commit -m "feat: supervise PLC polling and safety handshake"
```

### Task 4: Source-Aware Controller Integration

**Files:**
- Modify: `app/controller.py`
- Modify: `orchestrator/state.py` only if a typed source field is necessary; otherwise persist sources in `run_metadata`
- Create: `tests/unit/test_controller_plc_safety.py`

**Interfaces:**
- Consumes: callbacks from `PLCBridgeService`.
- Produces: `emergency_stop(source, details)`, `emergency_resume(source, transaction_id)`, `emergency_reset(source, transaction_id)`, `plc_recovery_readiness(command)`.

- [ ] **Step 1: Write failing source-priority tests**

```python
async def test_gui_cannot_resume_plc_originated_estop(controller):
    await controller.emergency_stop(source="plc_pb2")
    result = await controller.emergency_resume(source="gui")
    assert result["ok"] is False
    assert result["failure_code"] == "PLC_PHYSICAL_RECOVERY_REQUIRED"

async def test_plc_resume_uses_saved_checkpoint(controller):
    await controller.emergency_stop(source="plc_pb2")
    result = await controller.emergency_resume(source="plc", transaction_id="plc-tx-1")
    assert result["ok"] is True
    assert result["resume"]["started"] is True
```

- [ ] **Step 2: Verify focused tests fail**

Run: `pytest -q tests/unit/test_controller_plc_safety.py`

- [ ] **Step 3: Extend existing methods without duplicating lifecycle logic**

Keep the current cancellation, resume-context, decision-layer reset, and fresh-state reset code. Add source metadata and reject GUI Resume/Reset while `plc_pb2` remains active. Existing callers without a source default to `gui` for compatibility.

- [ ] **Step 4: Add terminal-error classification hook**

After retry exhaustion or unhandled active-run exception, call the service's terminal E-STOP callback. Explicitly exclude planned completion, loop-cap safe stop, waiting, expected blocked, and retry-in-budget events. Do not change `GuardianAgent`.

- [ ] **Step 5: Run controller regression tests**

Run:

```bash
pytest -q tests/unit/test_controller_plc_safety.py tests/integration/test_controller_run.py tests/unit/test_controller_planning.py
```

Expected: new and existing emergency lifecycle tests pass.

- [ ] **Step 6: Commit task files only**

```bash
git add app/controller.py orchestrator/state.py tests/unit/test_controller_plc_safety.py
git commit -m "feat: connect physical PLC priority to runtime safety"
```

### Task 5: FastAPI Lifecycle And Bounded PLC APIs

**Files:**
- Modify: `app/main.py`
- Create: `tests/integration/test_plc_bridge_api.py`

**Interfaces:**
- Consumes: singleton `PLCBridgeService` and source-aware Controller methods.
- Produces: `/plc` and `/api/plc/*` routes from the spec.

- [ ] **Step 1: Write failing API tests**

Test status while offline, automatic service start, config validation, virtual input rejection in live transport, and absence of a generic write endpoint.

```python
def test_status_offline_preserves_legacy_control(client):
    payload = client.get("/api/plc/status").json()
    assert payload["connection_state"] == "offline"
    assert payload["legacy_controls_available"] is True

def test_no_generic_write_route(client):
    assert client.post("/api/plc/write", json={"device": "D200", "value": 1}).status_code == 404
```

- [ ] **Step 2: Verify API tests fail**

Run: `pytest -q tests/integration/test_plc_bridge_api.py`

- [ ] **Step 3: Add service lifecycle**

Create one lazy singleton, start auto-connect monitoring during FastAPI startup without blocking GUI startup, and await service shutdown before process exit. A failed PLC connection must not fail server startup.

- [ ] **Step 4: Add typed request models and bounded routes**

Implement config/status/connect/disconnect/preflight/events and virtual-input routes. Keep D101/D102 writes internal.

- [ ] **Step 5: Run API and startup/shutdown tests**

Run: `pytest -q tests/integration/test_plc_bridge_api.py tests/integration/test_controller_run.py`

- [ ] **Step 6: Commit task files only**

```bash
git add app/main.py tests/integration/test_plc_bridge_api.py
git commit -m "feat: expose bounded PLC workspace APIs"
```

### Task 6: PLC Device Workspace And Main GUI Card

**Files:**
- Create: `web/templates/plc.html`
- Create: `web/static/plc.js`
- Create: `web/static/plc.css`
- Modify: `web/templates/index.html`
- Modify: `web/static/app.js`
- Create: `tests/ui/plc_workspace_browser_audit.py`

**Interfaces:**
- Consumes: `/api/plc/config`, status, preflight, connect/disconnect, events, and virtual input APIs.
- Produces: operator setup/diagnostic view and Main GUI PLC card.

- [ ] **Step 1: Write static/browser audit assertions**

Assert the workspace contains Connection, Register State, Safety State, Transport Health, Event History, and virtual controls; assert no arbitrary write fields exist.

- [ ] **Step 2: Verify browser/static tests fail**

Run: `pytest -q tests/ui/plc_workspace_browser_audit.py`

- [ ] **Step 3: Build the workspace using existing Device Workspace visual language**

Render raw and decoded D100-D102 values, source set, transaction phase, latency, freshness, and bounded events. Disable config editing while connected. Show virtual controls only when transport is virtual.

- [ ] **Step 4: Add Main GUI card and cached status refresh**

The card links to `/plc`, displays `ONLINE`, `OFFLINE`, `E-STOP`, or `FAULT`, and treats OFFLINE as optional rather than a global application error.

- [ ] **Step 5: Run browser audit at 1920x1080**

Run: `python tests/ui/plc_workspace_browser_audit.py`

Expected: no overlap, clipping, console errors, or missing controls.

- [ ] **Step 6: Commit task files only**

```bash
git add web/templates/plc.html web/static/plc.js web/static/plc.css web/templates/index.html web/static/app.js tests/ui/plc_workspace_browser_audit.py
git commit -m "feat: add PLC device workspace"
```

### Task 7: Live GUI And Runtime IDE Projection

**Files:**
- Modify: `web/templates/planning.html`
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `graphs/configs/atr_closed_loop.yaml`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/ui/live_runtime_ide_browser_audit.py`

**Interfaces:**
- Consumes: PLC status embedded in planning state or fetched from `/api/plc/status` at a bounded interval.
- Produces: physical-source lock, PB1 guidance, status projection, and non-stage Runtime IDE bridge node.

- [ ] **Step 1: Add failing Live GUI contract tests**

Assert PLC-originated E-STOP hides/disables GUI Resume/Reset, displays PB1 instructions, and ordinary PLC OFFLINE leaves existing controls available.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/integration/test_live_gui_runtime_layout.py tests/ui/live_runtime_ide_browser_audit.py`

- [ ] **Step 3: Implement source-aware Live GUI controls**

Extend `updateLiveEmergencyStopControls()` to read the server source set. Do not infer source from colors or D101 in the browser. Continue using existing E-STOP endpoints for GUI-originated control.

- [ ] **Step 4: Add PLC bridge metadata to Runtime IDE**

Add `plc_bridge` under `metadata.device_bridges` with workspace `/plc`, no normal agent-stage edge, config `configs/plc.yaml`, and boundary text describing D100-D102 safety transport.

- [ ] **Step 5: Run layout and browser verification**

Run:

```bash
pytest -q tests/integration/test_live_gui_runtime_layout.py
python tests/ui/live_runtime_ide_browser_audit.py
```

Expected: existing E-STOP layout remains intact and PLC is rendered as a Device Bridge, not an agent.

- [ ] **Step 6: Commit task files only**

```bash
git add web/templates/planning.html web/static/planning.js web/static/styles.css graphs/configs/atr_closed_loop.yaml tests/integration/test_live_gui_runtime_layout.py tests/ui/live_runtime_ide_browser_audit.py
git commit -m "feat: project PLC safety state into live runtime"
```

### Task 8: End-To-End Verification And Documentation

**Files:**
- Create: `docs/device_bridges/plc_safety_bridge.md`
- Modify: `docs/README.md`
- Modify: `docs/document_manifest.yaml`
- Modify: `REQUIREMENTS.md`
- Create: `tests/integration/test_plc_safety_e2e.py`

**Interfaces:**
- Consumes: complete bridge, Controller, APIs, and GUI projection.
- Produces: reproducible virtual/full-path proof and operator guide.

- [ ] **Step 1: Write the virtual end-to-end test**

Drive the public API/controller path through NORMAL, PB2, PB1 Resume, PB2,
PB1 Reset, terminal error, normal disconnect, and latched disconnect. Assert
register snapshots and Controller state after every transition.

- [ ] **Step 2: Run the end-to-end test**

Run: `pytest -q tests/integration/test_plc_safety_e2e.py`

Expected: pass without physical PLC access.

- [ ] **Step 3: Write operator documentation**

Document register ownership, ladder assumptions, connection setup, GUI use,
recovery sequence, offline legacy behavior, source priority, failure codes,
Conda `plc` diagnostic command, and physical validation checklist.

- [ ] **Step 4: Run the focused regression suite**

Run:

```bash
pytest -q \
  tests/unit/test_plc_safety_state.py \
  tests/unit/test_plc_bridge.py \
  tests/unit/test_plc_bridge_service.py \
  tests/unit/test_controller_plc_safety.py \
  tests/integration/test_plc_bridge_api.py \
  tests/integration/test_plc_safety_e2e.py \
  tests/integration/test_live_gui_runtime_layout.py
```

Expected: all pass.

- [ ] **Step 5: Run repository validation and diff checks**

Run:

```bash
python -m py_compile device_bridges/plc_bridge.py utils/plc_safety_state.py utils/plc_bridge_service.py app/controller.py app/main.py
git diff --check
```

Expected: exit zero.

- [ ] **Step 6: Perform operator-approved physical PLC validation**

With downstream robot/printer/UTM motion disabled, run the eight physical
checks in the design spec and preserve the status/event output as evidence.
Do not perform physical motion unless separately authorized.

- [ ] **Step 7: Commit documentation and E2E proof**

```bash
git add docs/device_bridges/plc_safety_bridge.md docs/README.md docs/document_manifest.yaml REQUIREMENTS.md tests/integration/test_plc_safety_e2e.py
git commit -m "docs: validate PLC safety bridge workflow"
```

## Final Review Gate

- Confirm `git status --short` contains no accidental unrelated additions.
- Confirm no code path writes D100 or D101 zero.
- Confirm no public endpoint accepts a register/device name.
- Confirm PLC OFFLINE from NORMAL preserves existing behavior.
- Confirm PLC disconnect after observed D101 retains the local latch.
- Confirm GUI recovery cannot bypass a PLC source.
- Confirm planned test completion does not set D101.
- Confirm runtime events are change-driven and bounded.
- Confirm the actual physical PLC test is explicitly separated from downstream device motion.
