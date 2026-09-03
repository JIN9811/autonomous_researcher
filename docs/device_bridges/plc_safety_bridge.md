---
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience:
  - operator
  - developer
  - integrator
scope:
  - plc_safety_bridge
  - emergency_stop
  - physical_recovery
summary: Installation, operation, recovery, diagnostics, and pending physical-validation procedure for the Mitsubishi PLC safety bridge.
source_of_truth:
  - configs/plc.yaml
  - device_bridges/plc_bridge.py
  - utils/plc_safety_state.py
  - utils/plc_bridge_service.py
  - app/controller.py
  - app/main.py
  - web/templates/plc.html
  - web/static/plc.js
last_verified: 2026-09-03
verified_against: working-tree
related_docs:
  - docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md
  - docs/superpowers/plans/2026-08-24-plc-safety-bridge.md
  - docs/device_bridges/README.md
supersedes: []
---

# PLC Safety Bridge Operator Guide

## Purpose And Safety Boundary

The bridge connects the ATR Controller safety state to a Mitsubishi PLC through
MC Protocol Type 3E. One backend service owns the connection, reads D100-D102 as
one snapshot, projects physical PB2/PB1 decisions into the Controller, and
exposes cached status to the PLC workspace and Live GUI.

This bridge is a supervisory software integration. It does not replace a
hardwired E-STOP circuit, safety-rated PLC logic, contactors, or a PLC-side
watchdog. Total PC power, kernel, or network failure cannot guarantee a D101
write. Physical validation must begin with printer, robot, UTM, and all other
downstream motion disabled.

## Register Contract And Ownership

| Register | Values | Owner | PC behavior |
|---|---|---|---|
| D100 | `0` none, `1` PB1 short Resume, `2` PB1 long Reset | PLC ladder | Read only. The PC never writes D100. |
| D101 | `0` normal, `1` E-STOP latched | PLC ladder for PB2; PC may also set | Read every snapshot. The PC may write only `D101=1`; it never writes `D101=0`. |
| D102 | `0` idle, `1` recovery acknowledged | PC handshake | The PC may write `0` or `1`; shutdown lowers D102 best effort. |

There is no public route that accepts a device/register name. The only public
test input is a named `estop`, `resume`, or `reset` action and it is rejected
unless the service was explicitly constructed with `VirtualPLCTransport`.

## Ladder Assumptions

The PLC program remains authoritative for pushbutton debounce, press duration,
one-shot behavior, and safety interlocks. The software contract assumes:

1. PB2 latches D101 to `1`.
2. PB1 short sets D100 to `1` only while D101 is latched.
3. PB1 long sets D100 to `2` only while D101 is latched.
4. D100, D101, and D102 can be read as one contiguous three-word snapshot.
5. When the PC writes `D102=1` for a valid request, the ladder clears D100,
   D101, and its recovery interlocks.
6. The PC accepts either the normal `(0,0,1)` release observation followed by
   its own D102 clear, or an immediate `(0,0,0)` readback from a ladder that
   clears all three words before the first readback. Controller recovery is
   invoked only after a verified `(0,0,0)` snapshot. A new D100 command or D101
   reassertion fails recovery.

Any unsupported value or command without D101 is a protocol fault. Do not
change ladder semantics without updating the decoder, virtual transport, E2E
test, and this guide together.

## Installation And Diagnostic Environment

Install the ATR server dependency in the normal project environment:

```bash
pip install -r requirements.txt
```

`requirements.txt` and `pyproject.toml` declare
`pymcprotocol>=0.3.0,<0.4.0`. The ATR server imports this package in-process; it
does not launch Conda for each poll.

The validated Linux diagnostic environment name is lowercase `plc`. Verify the
installed diagnostic package without connecting to a PLC:

```bash
conda run -n plc python -c 'import importlib.metadata as m, pymcprotocol; print(m.version("pymcprotocol")); print(pymcprotocol.__file__)'
```

The validated result is `pymcprotocol 0.3.0`. A successful import proves only
the client installation, not network reachability, ladder correctness, or the
physical D100-D102 contract.

## Connection Setup

Tracked defaults are in `configs/plc.yaml`:

```yaml
transport: pymcprotocol_type3e
host: 192.168.50.90
port: 4999
poll_interval_s: 0.2
stale_after_s: 1.0
handshake_timeout_s: 5.0
runtime_environment: plc
```

Use this sequence:

1. Confirm downstream motion and physical process starts are disabled.
2. Open `/plc` and confirm the transport is `pymcprotocol_type3e`, never
   `virtual`, for physical operation.
3. While the monitor is STOPPED and transport status is OFFLINE, enter host,
   port, polling, stale, and timeout values and save. Configuration changes are
   rejected while a run, handshake, or reconnecting/running monitor is active.
4. Select **Preflight** to connect and read D100-D102 without acknowledging a
   recovery input.
5. Confirm ONLINE, current raw values, latency, sample age, and no failure code.
6. Select **Connect** to keep the singleton monitor running. Repeated Connect
   requests do not create another polling owner.

Preflight never invokes Resume or Reset. Startup reconciliation may acknowledge
an already asserted `D100=1` only after a fresh Controller readiness check proves
that no runtime was interrupted; `D100=2`, an interrupted runtime without a
valid checkpoint, and orphan `(0,0,1)` states remain recovery-required. A
verified legacy D102 write whose immediate readback was `(0,0,0)` is completed
without another physical write.

## API And GUI Surfaces

| Method | Route | Operator purpose |
|---|---|---|
| `GET` | `/api/plc/config` | Read non-secret editable settings and fixed register mapping. |
| `POST` | `/api/plc/config` | Validate and save settings while offline. |
| `GET` | `/api/plc/status` | Read cached connection, snapshot, latch, transaction, timing, and failure state. |
| `POST` | `/api/plc/connect` | Start the single monitor. |
| `POST` | `/api/plc/disconnect` | Stop monitoring and close transport. |
| `POST` | `/api/plc/preflight` | Connect, read, and validate the bounded register contract. |
| `GET` | `/api/plc/events` | Read bounded, change-driven bridge events. |
| `POST` | `/api/plc/virtual/input` | Apply a named virtual PB2/PB1 action in explicit test transport only. |

The `/plc` workspace shows connection controls, raw registers, decoded safety
state, transaction phase, latency/freshness, reconnect status, and bounded
event history. Virtual buttons are test-only. The Live GUI projects the same
backend state in the top-level E-STOP area. It disables GUI Resume and Reset
while `plc_pb2` is active and instructs the operator to use physical PB1.
Every mouse-triggered GUI E-STOP route latches only the Controller as
`gui_estop`; it does not write `D101`. Its existing GUI Resume and Reset controls
remain available whether the PLC is online or offline. Only a D101-observed
`plc_pb2` source replaces those controls with the physical PB1 guidance.

Never interpret a frontend color or button state as independent safety proof.
Confirm the backend status, raw snapshot, Controller source set, and transaction
phase agree.

## Normal And Recovery Sequences

### Normal

Expected snapshot: `(D100,D101,D102)=(0,0,0)`. Safety state is `NORMAL`, the
Controller emergency latch is false, and no PLC source is active.

### PB2 E-STOP

Expected snapshot: `(0,1,0)`. The service records `plc_pb2`, invokes the
Controller emergency-stop path once, cancels active runtime/planning work, and
keeps the local latch even if the connection is later lost.

The connected service also runs a dedicated 50 ms D101 monitor thread. It uses
the same MC Protocol connection and serializes every read/write with the normal
state-machine I/O lock. On the first D101 assertion it calls the registered
`lerobot.rollout.stop` tool and requests thread-safe cancellation of the active
run and planning-handoff tasks. This fast path remains active when the main
asyncio loop is busy. It does not perform Resume/Reset, change PLC latch rules,
or replace the normal polling path; normal polling remains responsible for
state projection, persistence, recovery, and audit events.

### PB1 Short Resume

1. Start from PB2-latched `(0,1,0)`. An interrupted runtime requires a valid
   saved Controller checkpoint; an idle runtime does not.
2. PB1 short produces `(1,1,0)`.
3. Controller readiness must prove no active physical command, no critical or
   unknown device health, and no unresolved uncertain command effect. If work
   was interrupted, it must also prove a valid Resume checkpoint. The PC then
   persists a transaction and writes `D102=1`.
4. The ladder clears D100/D101, producing `(0,0,1)`, or immediately clears all
   three words to `(0,0,0)`.
5. The PC verifies `(0,0,0)` and resumes from the saved checkpoint when one
   exists. Idle recovery only clears the latch and does not start work.

### PB1 Long Reset

1. Start from PB2-latched `(0,1,0)`.
2. PB1 long produces `(2,1,0)`.
3. After readiness, D102 assertion, ladder clear, and D102 readback complete,
   the Controller returns to fresh-start state.
4. Reset does not start a run or actuate a device.

If any validation, write, ladder-clear, full readback, or Controller transition
fails or returns `ok=false`, atomically restore Controller and service source
latches, best-effort reassert `D101=1`, persist the failed phase, and never mark
the transaction completed. Never clear D101 from the PC to force recovery.

## Source Priority And Offline Behavior

Priority is:

```text
PLC physical E-STOP
> physical D100 Resume/Reset decision
> Controller safety/readiness validation
> GUI controls
> agent automation
```

The Controller tracks sources as a set. `plc_pb2` cannot be cleared by GUI
Resume/Reset. A qualifying terminal error adds `runtime_terminal_error`,
latches locally first, and then attempts `D101=1`. Physical recovery may clear
the paired PLC and terminal sources only after the complete handshake. Any
other active source keeps the latch.

The service records a pending PC D101 origin (`runtime_terminal_error`) before
attempting the write and retains that
attribution until a fresh D101=0 sample. A subsequent D101=1 sample is therefore
not mislabeled `plc_pb2`. The Controller start path also checks the service latch
so loss of Controller-local state cannot open a new run.

If connection is lost from a fresh NORMAL snapshot, PLC status becomes OFFLINE
and the pre-existing GUI/Controller controls remain available. The service does
not switch to virtual transport. If D101 was observed first, status becomes
OFFLINE while the local PLC source and Controller E-STOP remain latched; GUI
recovery remains blocked until reconnect and valid physical recovery.
While the monitor remains active but cannot reconnect, status is RECONNECTING,
not stopped/offline. A connected sample older than `stale_after_s` becomes
STALE with `PLC_STATE_STALE`; one valid fresh sample clears stale/protocol
failure details. Reconnect closes the prior transport before opening another.

## Terminal Errors

The following abnormal terminal conditions latch the Controller first and then
attempt `D101=1` when connected:

- agent exception after the configured retry budget is exhausted;
- critical device or hardware failure;
- unknown physical device state after a command;
- safety interlock violation;
- unexpected physical execution process exit;
- unhandled exception that abnormally ends an active run.

Planned test completion, the configured test-loop cap, normal COMPLETE,
operator waiting, expected BLOCKED without physical uncertainty, in-budget
retry, recovered LLM timeout, and ordinary operator safe stop do not set D101.

## Failure Codes And Operator Action

| Failure family | Codes | Action |
|---|---|---|
| Connection/config | `PLC_CONNECT_FAILED`, `PLC_STATE_STALE`, `PLC_CONFIG_REQUIRES_DISCONNECT`, `PLC_CONFIG_MONITOR_RUNNING`, `PLC_CONFIG_ACTIVE_RUN`, `PLC_CONFIG_HANDSHAKE_ACTIVE`, `PLC_DISCONNECT_ACTIVE_RUN`, `PLC_DISCONNECT_HANDSHAKE_ACTIVE`, `PLC_CONFIG_VALIDATION_FAILED` | Stop active work safely; stop the monitor; verify host, port, package, network, freshness, and bounds; retry read-only preflight. |
| Register/protocol | `PLC_INVALID_REGISTER_VALUE`, `PLC_INVALID_COMMAND_VALUE`, `PLC_COMMAND_WITHOUT_ESTOP`, `PLC_RECONCILIATION_REQUIRED` | Keep motion disabled; inspect ladder values and prior transaction; do not acknowledge stale D100. |
| Recovery readiness | `PLC_INVALID_RECOVERY_COMMAND`, `PLC_ESTOP_NOT_ACTIVE`, `PLC_PHYSICAL_RECOVERY_NOT_ACTIVE`, `PLC_RUNTIME_STILL_ACTIVE`, `PLC_PHYSICAL_COMMAND_ACTIVE`, `PLC_DEVICE_HEALTH_UNSAFE`, `PLC_DEVICE_EFFECT_UNRESOLVED`, `PLC_RESUME_CONTEXT_UNAVAILABLE`, `PLC_RESUME_READINESS_FAILED`, `PLC_TRANSACTION_REQUIRED`, `PLC_SERVICE_SAFETY_LATCH_ACTIVE` | Retain latch; resolve Controller source, runtime, physical command/device evidence, checkpoint, and service-latch conditions before another PB1 decision. |
| Physical recovery required | `PLC_PHYSICAL_RECOVERY_REQUIRED` | Do not use GUI Resume or Reset. Keep motion disabled, restore PLC connectivity if needed, and complete the physical PB1/D102 recovery handshake. |
| Other source remains | `ACTIVE_SAFETY_SOURCE_REMAINS` | Keep the E-STOP latched, inspect the Controller active-source set, and resolve every independent GUI, terminal, or physical source before retrying recovery. |
| Handshake/write | `PLC_WRITE_FAILED`, `PLC_HANDSHAKE_TIMEOUT`, `PLC_HANDSHAKE_CLEAR_NOT_OBSERVED`, `PLC_D102_CLEAR_FAILED`, `PLC_RUNTIME_RESUME_FAILED`, `PLC_RUNTIME_RESET_FAILED` | Retain both latches; inspect transaction phase, full D100-D102 readback, relatch evidence, transport, and event history. Never force D101 low. |
| Terminal synchronization | `PLC_ESTOP_SYNC_FAILED` | Treat local Controller E-STOP as active; restore PLC connectivity and reconcile without continuing the run. |
| Virtual/API gate | `PLC_VIRTUAL_INPUT_UNAVAILABLE`, `PLC_VIRTUAL_INPUT_VALIDATION_FAILED` | Use named virtual actions only in an explicitly constructed test transport; never select virtual as live fallback. |

Bridge events are bounded in memory and in the atomic JSON runtime journal.
Unchanged poll samples do not append snapshot events. The current transaction
persists run/session identity when available, source set, readiness evidence,
pre/post-write snapshots, final phase, and final failure. Event/transaction
payloads are depth/size bounded and secret-like keys are redacted. Use
`/api/plc/events` to correlate connection, stale, snapshot, latch, rejection,
handshake, completion, reconciliation, and protocol-fault changes.

## Software-Only Verification

This command uses only the in-memory virtual transport. It does not access a
physical PLC, ROS, cameras, printers, robots, or UTM:

```bash
pytest -q tests/integration/test_plc_safety_e2e.py
```

The proof covers NORMAL, PB2, PB1 Resume, PB2, PB1 Reset, planned completion,
qualifying terminal error, normal disconnect, and latched disconnect through
the public API/Controller paths, with register and Controller-source assertions.

## Runtime Checkout Diagnosis

Confirm the checkout used by a running server before diagnosing a missing
workspace route. This read-only command reports the process working directory:

```bash
readlink /proc/<pid>/cwd
```

For example, a server whose working directory is
`/home/jin/autonomous_researcher` imports and serves that checkout. It cannot
expose a `/plc` route that exists only in
`/home/jin/.worktrees/autonomous_researcher/plc-safety-bridge` until the
reviewed commits are integrated into the serving checkout or the reviewed
worktree is explicitly started through the normal deployment procedure.

Do not overwrite, reset, or force-checkout the serving checkout, especially if
it is dirty. Preserve its changes, review and integrate the required commits,
or use an explicitly reviewed runtime checkout. This diagnosis and remediation
are software-only; they do not require a PLC connection or physical actuation.

## Physical PLC Validation Checklist

**Evidence status: PENDING OPERATOR-APPROVED PHYSICAL VALIDATION.** Task 8 did
not connect to or write the physical PLC and did not start downstream motion.
Record timestamps, raw D100-D102 snapshots, transaction phases, Controller
source state, latency, and `/api/plc/events` output for every performed check.

Preparation: obtain separate operator approval, use the configured PLC at
`192.168.50.90:4999`, and physically disable printer, robot, UTM, and all other
downstream motion. PLC validation does not authorize downstream motion.

1. **PENDING:** Read-only preflight confirms D100-D102 and polling latency.
2. **PENDING:** PB2 confirms D101 and Live GUI E-STOP within the
   polling/processing budget.
3. **PENDING:** PB1 short confirms `D100=1`, D102 handshake, ladder clear, and
   Controller Resume state.
4. **PENDING:** PB2 then PB1 long confirms `D100=2`, D102 handshake, ladder
   clear, and Controller Reset state.
5. **PENDING:** A controlled terminal-error injection confirms PC D101
   set-only behavior; no check may command `D101=0` from the PC.
6. **PENDING:** PLC network interruption from NORMAL confirms legacy control
   continuity and automatic reconnect; interruption after D101 confirms local
   latch preservation.
7. **PENDING:** Only after checks 1-6 pass, run a bounded virtual-device closed
   loop with no physical downstream motion.
8. **PENDING, SEPARATE AUTHORIZATION REQUIRED:** Physical printer, robot, or
   UTM motion requires another operator-approved validation run and is not part
   of PLC D100-D102 validation.

Do not replace any pending item with inferred or virtual evidence. Preserve the
actual status/event output as evidence when the controller authorizes the
external physical-validation activity.
