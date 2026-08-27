# PLC Safety Bridge Design

## Status

Proposed design. This document defines the PLC bridge, safety handshake, GUI
projection, and verification contracts only. It does not authorize physical
equipment actuation or implementation.

## Objective

Add a Mitsubishi MC Protocol PLC bridge to ATR so that a physical emergency
stop and its physical Resume/Reset decision are reflected in the same runtime
control plane used by Live GUI.

The bridge must:

- read `D100` and `D101` from `192.168.50.90:4999` through
  `pymcprotocol.Type3E`;
- treat `D101=1` as a latched physical emergency-stop state;
- interpret `D100=1` as Resume and `D100=2` as Reset only while the emergency
  stop is latched;
- write only `D102` as the PC-to-PLC release handshake during operator
  recovery;
- allow the PC to set `D101=1` when a running loop ends in a qualifying
  terminal error;
- give the physical PLC path priority over GUI recovery controls;
- operate as an optional priority layer: when no PLC connection is available,
  preserve the existing GUI/Controller control behavior;
- preserve the existing Guardian, Controller, LangGraph, agent, and device
  execution contracts instead of creating a parallel run controller;
- provide a dedicated Device Workspace and a compact Live GUI safety
  projection;
- support deterministic virtual-PLC tests before physical validation.

## Selected Architecture

The selected architecture is a **single-owner PLC transport with a
Controller-owned safety state machine**.

```text
PB2 / PLC ladder
  -> D101 emergency latch
  -> PLC Device Bridge poller
  -> MainController.emergency_stop(source="plc")
  -> current runtime cancellation and Live GUI E-STOP projection

PB1 short/long decision after E-STOP
  -> D100=1 Resume or D100=2 Reset
  -> PLC Device Bridge command observation
  -> Controller safety/readiness validation
  -> PC writes D102=1
  -> PLC clears D100/D101 and ladder interlocks
  -> PC observes D100=0 and D101=0
  -> PC writes D102=0
  -> Controller resumes the saved checkpoint or resets to fresh state
```

The PLC bridge owns MC Protocol I/O. `MainController` owns runtime lifecycle
state. Live GUI and Device Workspace render server-authoritative state and do
not implement a second safety state machine in JavaScript.

## Scope

### Included

- One Mitsubishi Type 3E PLC connection.
- Atomic two-word polling of `D100` and `D101`.
- Whitelisted writes to `D101=1` and `D102 in {0,1}`.
- PLC-originated E-STOP.
- GUI-originated and terminal-error-originated E-STOP synchronization to the
  PLC latch when communication is available.
- Physical Resume/Reset requests through `D100`.
- Source-aware GUI locking and operator guidance.
- Connection health, stale detection, reconnect, audit records, and runtime
  events.
- A virtual PLC transport that implements the same register and handshake
  contract.
- Configuration persistence without storing runtime state in tracked source
  files.

### Excluded

- `D103` loop-running lamp output.
- PLC heartbeat/watchdog registers.
- Arbitrary PLC device read/write access.
- PLC ladder generation or upload.
- Replacing hardwired safety circuits with software.
- Direct device homing, printer control, robot motion, or UTM actuation from
  the PLC workspace.
- Changing Guardian Agent decision policy.
- Mapping planned test completion or an ordinary safe stop to PLC E-STOP.
- Automatically resuming motion merely because `D101` returned to zero.
- Treating an ordinary PLC disconnect from a previously normal snapshot as an
  emergency by itself.

## Existing Contracts Preserved

The implementation must preserve these current responsibilities:

| Existing component | Preserved authority |
|---|---|
| `agents/guardian_agent.py` | Graph-wide risk, failure, health, and continue/recover/retry/stop decisions |
| `policies/guardian_gate.py` | Pre/action/post/exception normalization, tool shielding, incidents, and approvals |
| `app/controller.py` | E-STOP state, immediate runtime cancellation, resume context, Resume, and Reset lifecycle |
| `orchestrator/langgraph_runtime.py` | Configured stage execution, retries, transitions, and runtime events |
| Existing device bridges | Device-specific commands, acknowledgements, and physical state |
| Live GUI | Operator-facing projection and bounded control requests |
| Runtime IDE | Graph/runtime observability; no independent PLC execution route |

The PLC bridge is a low-level safety transport. It must not call agents,
select workflow stages, or modify LangGraph transitions directly.

## Register Contract

### Address map

| Register | Writer | Reader | Allowed values | Meaning |
|---|---|---|---|---|
| `D100` | PLC ladder | PC | `0`, `1`, `2` | `0=none`, `1=Resume request`, `2=Reset request` |
| `D101` | PLC ladder and PC set-only path | PC and PLC | `0`, `1` | Shared latched E-STOP state |
| `D102` | PC | PLC ladder and PC | `0`, `1` | PC accepted the pending recovery request and permits ladder release |

### Ownership rules

- PLC and PC may both set `D101=1`.
- PC must never write `D101=0`.
- Only the PLC ladder clears `D101` after a valid D100/D102 handshake.
- PC may write only `D102=0` or `D102=1`.
- PC must never write D100.
- Any D100 value outside `0`, `1`, and `2` is a protocol fault and must not be
  acknowledged.
- `D100!=0` while `D101=0` is an invalid command state and must not trigger
  Resume or Reset.
- A repeated unchanged D100 value is one pending request, not repeated
  requests.

### Ladder assumptions

The ladder is authoritative for physical button interpretation:

- PB2 sets and latches `D101=1`.
- After E-STOP, a short PB1 operation produces `D100=1`.
- After E-STOP, PB1 held for at least three seconds produces `D100=2`.
- Short and long PB1 outcomes are mutually interlocked.
- Once one recovery request is active, additional PB1 operations do not change
  the request.
- `D102=1` with `D100 in {1,2}` causes the ladder to clear D100, D101, and its
  recovery interlocks.

The PC does not duplicate debounce, press duration, or one-shot logic already
implemented in the ladder.

## Runtime State Machine

### States

| State | Register observation | Runtime meaning |
|---|---|---|
| `DISCONNECTED` | no fresh sample | PLC layer unavailable; existing GUI/Controller controls remain active unless a prior PLC E-STOP is latched |
| `NORMAL` | `D100=0,D101=0,D102=0` | No PLC emergency latch |
| `ESTOP_LATCHED` | `D100=0,D101=1,D102=0` | Runtime must remain emergency-stopped |
| `RESUME_REQUESTED` | `D100=1,D101=1,D102=0` | Physical operator requested checkpoint Resume |
| `RESET_REQUESTED` | `D100=2,D101=1,D102=0` | Physical operator requested fresh-state Reset |
| `HANDSHAKE_ASSERTED` | `D102=1` | PC accepted one request and is waiting for ladder clear |
| `RELEASE_OBSERVED` | `D100=0,D101=0,D102=1` | Ladder clear observed; PC must lower D102 |
| `PROTOCOL_FAULT` | invalid combination/value | Recovery is blocked pending diagnosis |

### E-STOP transition

On a fresh `D101: 0 -> 1` observation:

1. Record the PLC sample, monotonic timestamp, wall-clock timestamp, and active
   run/session identity.
2. Add `plc_pb2` to the set of active E-STOP sources unless a pending PC write
   proves that the same transition was PC-originated.
3. Invoke the existing immediate Controller emergency-stop path.
4. Cancel active runtime/planning work through the existing Controller logic.
5. Block all new physical device commands through the existing emergency state.
6. Emit PLC and runtime control events.
7. Keep the latch active after `D101` returns to zero until the complete
   handshake and Controller transition have succeeded.

An already-latched D101 sample must not repeatedly invoke emergency-stop.

### Resume transition

Resume is valid only in `RESUME_REQUESTED`.

1. Confirm the runtime is already emergency-stopped.
2. If active work was interrupted, confirm a saved resume context exists. If no
   work was running, allow latch-only Resume without starting a new run.
3. Confirm there is no active physical command or unresolved uncertain-effect
   device state.
4. Run existing readiness checks without changing Guardian policy.
5. If validation fails, leave D102 at zero, remain latched, and surface the
   failure in Device Workspace, Live GUI, and Operator Attention.
6. If validation passes, persist the transaction and write `D102=1`.
7. Wait for a fresh atomic release sample. Accept `(0,0,1)` or the ladder's
   immediate all-zero `(0,0,0)` response.
8. If D102 remains one, write `D102=0`; always verify a full `(0,0,0)` sample.
9. Invoke the existing Controller emergency-resume path.
10. If post-handshake Resume fails, set D101 back to one when transport is
    available and retain the local emergency latch.

Resume continues from the Controller's saved checkpoint when active work was
interrupted. In idle state it only clears the latch; it must not create a new
run or silently restart from Design.

### Reset transition

Reset is valid only in `RESET_REQUESTED`.

1. Confirm the runtime is emergency-stopped and no device command remains
   active.
2. Persist the transaction and write `D102=1`.
3. Wait for a fresh sample with `D100=0` and `D101=0`.
4. Write `D102=0` and verify it reads back as zero.
5. Invoke the existing Controller emergency-reset path.
6. Return the runtime to the same initial state as a fresh server start.
7. Do not automatically start a run or actuate a device.

If reset cleanup fails after PLC release, the PC must attempt to set D101=1
again and expose a terminal control-plane error.

## E-STOP Sources And Priority

The runtime tracks a set of sources rather than a single Boolean:

- `plc_pb2`
- `gui_estop`
- `runtime_terminal_error`

Priority is:

```text
PLC physical E-STOP
  > physical D100 Resume/Reset decision
  > Controller safety/readiness validation
  > GUI controls
  > agent automation
```

Rules:

- A PLC-originated E-STOP disables GUI Resume and Reset controls.
- Live GUI displays the PB1 short/long recovery instruction instead.
- Mouse GUI E-STOP invokes only the existing Controller `gui_estop` path and
  does not write D101. Existing GUI Resume and Reset remain available.
- A GUI request can never clear a PLC-originated latch.
- Simultaneous or ambiguous sources are treated as PLC-priority.
- Clearing one software source does not clear the runtime while another source
  remains active.

## Terminal Error Escalation

Guardian remains unchanged. The Controller/runtime terminal transition decides
whether a loop-ending error qualifies for PLC E-STOP synchronization.

### Set D101 to one

- Agent exception after configured retries are exhausted.
- Critical device or hardware failure.
- Device state becomes unknown after a physical command.
- Safety interlock violation.
- Unexpected termination of a physical execution process.
- An unhandled exception that ends an active run abnormally.

### Do not set D101

- Planned test-cycle completion.
- Guardian stop caused by the configured test loop cap.
- Normal `COMPLETE`.
- Operator-input waiting states.
- Expected `BLOCKED` state with no physical uncertainty.
- A retry that remains inside its configured retry budget.
- LLM timeout that is recovered without ending the run.
- Ordinary safe stop requested by the operator.

When a qualifying error occurs:

1. Latch Controller E-STOP locally first.
2. Attempt `D101=1` through the PLC bridge.
3. If the write fails, keep the local latch and report
   `PLC_ESTOP_SYNC_FAILED`; never continue because PLC synchronization failed.

PC power loss, kernel failure, or total network loss cannot be guaranteed to
set D101. This design does not replace a hardware safety circuit or PLC-side
watchdog.

## PLC Bridge Components

### `PLCBridge`

A new `BaseBridge` implementation owns typed operations:

- `connect`
- `disconnect`
- `status`
- `read_snapshot`
- `start_monitoring`
- `stop_monitoring`
- `set_estop`
- `set_recovery_ack`
- `clear_recovery_ack`
- `reconcile`

`execute(command, payload)` may dispatch these operations, but callers must not
receive a generic arbitrary-device write command.

### Transport interface

Production and virtual transports implement one internal interface:

```text
connect(host, port)
close()
read_words(head="D100", count=3)
write_word(device, value)
```

The production implementation uses `pymcprotocol.Type3E`. The virtual
implementation stores D100-D102 in memory and emulates ladder clear behavior
when D102 is asserted.

### Connection owner

- Exactly one backend PLC bridge instance owns the MC Protocol connection.
- Live GUI, Device Workspace, Controller, and tests consume the bridge service;
  they must not create independent PLC connections.
- The synchronous MC Protocol client runs outside the async event loop in a
  dedicated worker thread.
- Writes and reads are serialized through one lock/command queue.
- Shutdown performs a best-effort `D102=0` before closing, but never writes
  `D101=0`.

### Polling

- Default period: `0.2 s`.
- Read `D100`, `D101`, and `D102` as one contiguous snapshot when supported.
- Store monotonic receive time and round-trip latency.
- Publish state changes immediately.
- Publish a lower-frequency heartbeat/status snapshot without flooding SSE or
  run logs.
- Polling interval is configurable but bounded to a safe range in the GUI.

### Reconnect

- Idle connection failures use bounded exponential backoff.
- If the last fresh snapshot was normal and no PLC E-STOP source is latched,
  connection loss disables only the optional PLC layer; the existing
  GUI/Controller control path continues unchanged.
- If `D101=1` was observed before connection loss, the local PLC E-STOP source
  remains latched until reconnection and a valid physical recovery handshake.
- A reconnect does not replay D100 automatically.
- Reconciliation reads all three registers before accepting any command.
- Automatic reconnect is enabled while the ATR server is running.
- A physical-PLC disconnect may fall back only to the pre-existing
  GUI/Controller behavior. It must never switch to the virtual PLC in Live
  mode.

## Configuration And Persistence

Tracked defaults contain no runtime history:

```yaml
schema: plc_bridge_config.v1
transport: pymcprotocol_type3e
host: 192.168.50.90
port: 4999
poll_interval_s: 0.2
stale_after_s: 1.0
handshake_timeout_s: 5.0
runtime_environment: plc
registers:
  command: D100
  estop: D101
  recovery_ack: D102
```

Runtime configuration and transaction state are persisted under `memory/` and
excluded from Git where appropriate. The persisted transaction includes:

- transaction ID;
- command value and decoded action;
- Controller run/session ID;
- source set;
- phase;
- register snapshot before and after each write;
- timestamps and timeouts;
- validation result;
- final outcome or failure code.

The existing Conda environment named `PLC` is the validated diagnostic
environment. Implementation must declare `pymcprotocol` in installation
requirements and ensure the ATR server runtime can import the same supported
version; it must not run a new Conda process for every poll.

## API Contract

Suggested bounded APIs:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/plc/config` | Return editable non-secret config |
| `POST` | `/api/plc/config` | Validate and persist config while disconnected |
| `GET` | `/api/plc/status` | Return connection, register, latch, transaction, and latency state |
| `POST` | `/api/plc/connect` | Start the single monitoring connection |
| `POST` | `/api/plc/disconnect` | Stop monitoring when no active run requires it |
| `POST` | `/api/plc/preflight` | Connect/read/validate register contract without actuation |
| `GET` | `/api/plc/events` | Return bounded recent PLC event history |
| `POST` | `/api/plc/virtual/input` | Test-only PB2/PB1 simulation; unavailable in Live transport |

There is no public generic write endpoint. D101 and D102 writes are internal
Controller-to-bridge operations only.

All mutating responses include:

- `ok`
- `status`
- `failure_code`
- `message`
- `transaction_id`
- `register_snapshot`
- `connection_state`
- `step_trace`

## Runtime Events

The bridge emits bounded server-side events such as:

- `plc.bridge.connected`
- `plc.bridge.disconnected`
- `plc.bridge.stale`
- `plc.snapshot.changed`
- `plc.estop.latched`
- `plc.estop.sync_failed`
- `plc.resume.requested`
- `plc.reset.requested`
- `plc.request.rejected`
- `plc.handshake.asserted`
- `plc.handshake.release_observed`
- `plc.handshake.completed`
- `plc.protocol_fault`

Events are persisted with run identity when a run is active. Repeated polling
samples with no state change do not create unbounded chat messages or runtime
events.

## Device Workspace

Add one `PLC Bridge` card to Main GUI Device Workspaces and one dedicated PLC
workspace route.

The workspace contains:

1. **Connection**: host, port, environment, Connect, Disconnect, Preflight.
2. **Register State**: D100 decoded command, D101 E-STOP latch, D102 PC
   handshake, and raw values.
3. **Safety State**: Controller latch, source set, pending action, validation,
   and current transaction phase.
4. **Transport Health**: latency, last fresh sample, stale threshold, reconnect
   attempt, and last error.
5. **Event History**: bounded state-change and handshake events.
6. **Virtual Test Controls**: PB2 E-STOP, PB1 Short Resume, PB1 Long Reset, and
   terminal-error injection, visible only for the virtual transport.

The workspace must not expose arbitrary register writes, direct device
actuation, or a GUI button that clears D101.

## Live GUI Projection

Live GUI reuses the existing top-level E-STOP area and adds compact PLC status:

- `PLC ONLINE/OFFLINE/STALE`
- raw `D100/D101/D102`
- `E-STOP ACTIVE`
- `WAITING FOR PHYSICAL DECISION`
- `RESUME REQUESTED`
- `RESET REQUESTED`
- `PLC HANDSHAKE`
- `RESUMING`
- `RESET COMPLETE`
- protocol or synchronization failure

When `plc_pb2` is an active source:

- GUI Resume and Reset controls are disabled;
- the panel instructs the operator to use PB1 short or long input;
- E-STOP remains visually latched even if D101 briefly reads zero before the
  Controller transition is complete;
- no frontend timer or optimistic state may clear the latch.

The current E-STOP control remains available. Triggering it locally invokes the
Controller as `gui_estop` without D101 synchronization, so its existing GUI
Resume/Reset path remains independent of PLC connection state.

## Runtime IDE Projection

Runtime IDE represents the existing control path, not a new agent:

```text
PLC Bridge -> Controller Safety Control -> Runtime Cancel/Resume/Reset
```

The PLC appears as a Device Bridge node with evidence edges to Controller and
Live Runtime. It must not appear as an agent or a normal closed-loop stage.

Node inspection shows connection state, latest snapshot, active source set,
pending transaction, and recent event references without exposing generic
write controls.

## Failure Codes

At minimum:

- `PLC_CONNECT_FAILED`
- `PLC_READ_FAILED`
- `PLC_WRITE_FAILED`
- `PLC_STATE_STALE`
- `PLC_INVALID_COMMAND_VALUE`
- `PLC_COMMAND_WITHOUT_ESTOP`
- `PLC_HANDSHAKE_TIMEOUT`
- `PLC_HANDSHAKE_CLEAR_NOT_OBSERVED`
- `PLC_D102_CLEAR_FAILED`
- `PLC_ESTOP_SYNC_FAILED`
- `PLC_RESUME_CONTEXT_MISSING`
- `PLC_RESUME_READINESS_FAILED`
- `PLC_RUNTIME_RESUME_FAILED`
- `PLC_RUNTIME_RESET_FAILED`
- `PLC_RECONCILIATION_REQUIRED`

Failures never produce an automatic virtual fallback in Live mode.

## Startup And Crash Reconciliation

On server startup or PLC reconnect:

1. Read D100-D102 before registering control actions.
2. Load the last persisted PLC transaction if present.
3. Never resume from a register value alone. A reconnecting `D100=1` may proceed
   only after fresh Controller readiness proves no interrupted runtime, or a
   valid saved checkpoint proves bounded continuation.
4. If `D101=1`, restore local E-STOP projection.
5. If D100 is nonzero, display the pending physical request. A pending Resume
   may be acknowledged after the readiness rule above; Reset remains
   reconciliation-required.
6. If `D102=1` and D100/D101 are zero, clear D102 to zero and mark the prior
   transaction `release_observed_recovery_required`; do not resume motion.
7. If `D102=1` and D100/D101 remain active past the handshake timeout, lower
   D102, retain E-STOP, and raise a protocol fault.

This conservative behavior prevents a server restart from replaying an old
Resume request.

## Test Strategy

### Unit tests

- Register decoding for all valid and invalid combinations.
- D101 source latching and idempotent repeated samples.
- D100 request de-duplication.
- Resume and Reset state transitions.
- D102 assert/observe/clear sequence.
- Timeout and failed-write handling.
- Reconnect reconciliation.
- Terminal error classification that excludes planned completion and expected
  waiting states.
- GUI control lock rules for PLC-originated E-STOP.

### Integration tests with virtual PLC

1. Connect and observe NORMAL.
2. Simulate PB2 and verify Controller E-STOP plus GUI projection.
3. Simulate PB1 short and verify D102 handshake plus checkpoint Resume.
4. Simulate PB2 followed by PB1 long and verify fresh-state Reset.
5. Inject a qualifying terminal error and verify PC sets virtual D101.
6. Inject planned test completion and verify D101 remains zero.
7. Disconnect from a normal snapshot and verify the existing GUI/Controller
   path continues while PLC status becomes OFFLINE.
8. Disconnect after observing D101=1 and verify the local PLC E-STOP source
   remains latched.
9. Restart during each handshake phase and verify conservative reconciliation.

### Physical PLC validation

Physical validation uses the configured PLC at `192.168.50.90:4999` and starts
with no downstream device motion.

1. Read-only preflight confirms D100-D102 and polling latency.
2. PB2 confirms D101 and Live GUI E-STOP within the polling/processing budget.
3. PB1 short confirms D100=1, D102 handshake, ladder clear, and Resume state.
4. PB2 then PB1 long confirms D100=2, D102 handshake, ladder clear, and Reset.
5. A controlled terminal-error injection confirms PC D101 set-only behavior.
6. PLC network interruption from NORMAL confirms legacy control continuity and
   automatic reconnect; interruption after D101 confirms latch preservation.
7. Only after these pass may a bounded virtual-device closed loop be used.
8. Physical printer, robot, or UTM motion requires a separate operator-approved
   validation run.

## Acceptance Criteria

- One backend connection owns PLC communication.
- D100/D101 are read atomically at the configured interval.
- D101 from PB2 immediately invokes the existing Controller E-STOP path.
- D100=1 and D100=2 are accepted only while D101 is latched.
- PC writes only D101=1 and D102 in `{0,1}`.
- PC never writes D101=0 or D100.
- PLC-originated Resume and Reset require a complete D102 handshake and fresh
  ladder-clear observation; mouse GUI recovery does not use that handshake.
- A PLC-originated latch cannot be cleared from Live GUI.
- Qualifying terminal errors set local E-STOP and attempt D101 synchronization.
- Planned completion, waiting, and ordinary safe stop do not set D101.
- Live mode never falls back to virtual PLC.
- A normal PLC disconnect does not stop or reset an existing run and does not
  disable the pre-existing GUI/Controller controls.
- An E-STOP already observed from PLC remains latched across disconnect.
- Device Workspace, Live GUI, Runtime IDE, API, and logs project one backend
  state rather than maintaining independent copies.
- Polling does not flood chat, SSE, run logs, CPU, or memory.
- Restart/reconnect acknowledges Resume only after fresh Controller readiness;
  it never bypasses interrupted-runtime checkpoint validation.
- Existing Guardian decisions and normal closed-loop stage order remain
  unchanged.

## Planned Implementation Surface

The implementation plan may touch these focused areas after this design is
approved:

- new PLC bridge and virtual transport under `device_bridges/`;
- focused PLC configuration/runtime utilities under `utils/`;
- Controller source-aware emergency integration;
- bounded PLC API routes in `app/main.py`;
- Main Device Workspace card and a dedicated PLC workspace template/static
  assets;
- Live GUI and Runtime IDE state projection using existing event/state paths;
- tests and requirement/install documentation.

Unrelated Guardian policy, agent logic, closed-loop routing, printer behavior,
robot behavior, UTM behavior, and existing workspace layouts are out of scope.
