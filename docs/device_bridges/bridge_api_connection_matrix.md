<!-- atr-doc
doc_type: reference
subtype: system
status: active
authority: descriptive
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - integrator
scope:
  - device_bridges
  - api
  - connections
  - effects
  - recovery
summary: Cross-bridge matrix of ATR entry points, protocols, modes, external effects, evidence, and recovery rules.
source_of_truth:
  - device_bridges
  - mcp_tools
  - app/bootstrap.py
  - app/main.py
  - app/analysis_fem_routes.py
  - app/cae_fields_routes.py
  - utils/equipment_runtime_service.py
  - utils/plc_bridge_service.py
  - configs/devices.yaml
  - configs/lerobot.yaml
  - graphs/configs/atr_closed_loop.yaml
last_verified: 2026-09-11
verified_against: cf8cb9f
related_docs:
  - docs/device_bridges/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/paper/appendix_a_interfaces.md
supersedes: []
-->

# Device Bridge API and Connection Matrix

## Summary

This Reference compares AX4LAB's eight core device-integration capabilities,
with the Controller-owned PLC service listed separately. It groups routes by
function rather than replacing `/openapi.json`; individual references own
payload and lifecycle detail with their own verification dates.

## Scope

The matrix covers manager/provider routing, registered tools, runtime
sidecars, external computation, and deterministic substitutes at baseline
`cf8cb9f` (2026-09-11). `physical_possible` means an allowed path can reach motion; it
does not say that the checked-in default performs that motion.

The refresh includes Equipment Runtime/Flow/Skill records, explicit worker
selection, LeRobot replay and ActiveCam, staged CAE preparation, independent
Analysis FEM jobs, and saved-field APIs. No device or solver was executed.

## Source of Truth

- `device_bridges/` implementations;
- `mcp_tools/*_tools.py` and `app/bootstrap.py` registration;
- route declarations in `app/main.py`, `app/analysis_fem_routes.py` and `app/cae_fields_routes.py`;
- `utils/equipment_runtime_service.py` and `utils/plc_bridge_service.py`;
- `configs/devices.yaml` and `configs/lerobot.yaml`;
- `graphs/configs/atr_closed_loop.yaml` bridge projection.

## Boundary and Entry Matrix

| Boundary | Classification | Primary agent | Tool/resource entry | Operator API family |
|---|---|---|---|---|
| Printer Fleet | tool/API manager | Specimen, Guardian | `printer.prepare`, `device.health` | `/api/printer/fleet`, `/connection`, `/profile`, `/status` |
| Bambu X2D | provider + artifact transformer | Specimen | selected by Printer Fleet | Bambu slice/patch/probe/start/bed-clear/video under `/api/printer/*` |
| Prusa MK4S | graph-projected provider | Specimen | `printer.prepare` selected provider | shared `/api/printer/*`, autoejection test/status |
| LeRobot | graph/tool/API runtime | Manipulation, Vision | `lerobot.bridge`, `lerobot.*` | `/api/lerobot/*` |
| Windows PyAutoGUI | graph/tool/API runtime with durable execution service | Equipment | `equipment.pyautogui.*`; read-only `equipment.runtime.current/list/get`; resource `equipment_runtime` | `/api/equipment/windows/*`, `/api/equipment/runtime/*`, shared Skill/Profile surfaces |
| UTM Vision | graph/API sidecar | Vision, Equipment | camera/UTM tools plus runtime singletons | `/api/equipment/utm-runtime/*`, specimen-pose and camera routes |
| CAE Computation | graph/tool/API computation | Analysis | `cae.prepare_static_analysis`, `cae.run_static_analysis`, health; `calculix.*`, `pinn.*` and their resources | `/api/cae/config`, `/api/cae/run`, `/api/cae/fields*`; Analysis-owned `/api/analysis/fem/jobs` |
| Base and Simulators | test-only substitutes | test-mode agents | mock tools or direct test fixtures | no dedicated owned API |

The graph also exposes `plc_bridge` and `/api/plc/*`. This is a Controller-owned
supervisory service, not an LLM-callable agent stage; its graph `tools` list is
empty. See the [PLC operator guide](plc_safety_bridge.md) for its bounded
transport contract and physical-validation limits.

## Decision and Execution Ownership

| Layer | Owns | Does not imply |
|---|---|---|
| Agent decision | Task suitability, offered action choice and result assessment | Arbitrary device commands or direct register writes |
| Tool / shared runtime | Payload dispatch, session/job tracking and evidence collection | Every local agent JSON action is a registered tool |
| Manager / provider / worker | Selected transport and device-specific execution | A successful command response completes the scientific task |
| Operator API | Workspace requests and status views | API ownership equals a separate bridge implementation |

For example, Equipment's `execute_stacked_workflow` is an agent-local choice;
`equipment.pyautogui.run` is a registered execution tool; `equipment_runtime`
is a shared resource; `/api/equipment/runtime/current` is a status endpoint.
These interfaces have different authorities and must not be counted as four
independent implementations of the same operation.

## Connection Matrix

| Boundary | Local layer | Protocol/process | External target | Return path |
|---|---|---|---|---|
| Printer Fleet | profile selector and memory | in-process provider dispatch | selected Bambu or Prusa provider | normalized selection, health, workflow result |
| Bambu X2D | slicer, MQTT/video/FTPS clients | subprocess, MQTT TLS, FTPS, LAN video, HTTP artifact URL | Bambu Studio and printer | report telemetry, probe result, hashes, video/status, bed-clear proof |
| Prusa MK4S | slicer, client, workflow | subprocess and PrusaLink HTTP auth | PrusaSlicer and MK4S | status/job/storage, upload/start result, G-code/ejection evidence |
| LeRobot | profile/session/process manager | subprocess, serial, camera, local HTTP sidecars/files | rollout/replay/teleoperation, robot ports, cameras and optional training/Isaac processes | session status/logs, continuous telemetry, camera evidence, datasets and model artifacts |
| Windows PyAutoGUI | connection/program/locator client and Equipment Runtime | token-gated HTTP; durable local execution records | selected Windows or Local worker and desktop application | health, screenshot, step trace, request log, acquired-file metadata and execution projection |
| UTM Vision | ROS process/stream/pose managers | ROS 2 topics, subprocess, camera/USB, MJPEG | UTM workspace, YOLO/camera, D455F | graph/status, frames, calibration, pose/evidence artifacts |
| CAE Computation | facade, Analysis-owned job store, field/model adapters | filesystem and guarded subprocess | Gmsh/CalculiX/postprocessor, optional PINN environment | preparation receipts, decks, mesh checks, reaction curves, saved fields/logs and registry |
| Base and Simulators | `BaseBridge` and deterministic fixtures | in-process only | no required external target | schema-shaped simulated responses |

## Configuration and Secret Matrix

| Boundary | Checked-in configuration | Mutable memory/artifacts | Secret or credential names |
|---|---|---|---|
| Printer Fleet | `configs/devices.yaml` printer profiles | `memory/printer_fleet.json` | provider-specific; values never documented |
| Bambu X2D | `devices.printer.bambu`, `autoejection` | Bambu connection/autoejection/bed-clear memory; sliced artifacts | printer access code/serial through memory; executable env name only |
| Prusa MK4S | `devices.printer.live/slicer/ejection` | Prusa connection/profile and G-code artifacts | `PRUSA_USERNAME`, `PRUSA_PASSWORD`, `PRUSA_API_KEY` |
| LeRobot | `configs/lerobot.yaml` | port/session/profile/calibration, datasets, outputs, logs | `HF_TOKEN` or token file; no token value in docs |
| Windows PyAutoGUI | `devices.equipment.windows_pyautogui` | selected connection/worker, Profile/Flow/Skill versions, locators, `memory/equipment_runtime`, acquired artifacts | `WINDOWS_PYAUTOGUI_BRIDGE_URL`, `WINDOWS_PYAUTOGUI_BRIDGE_TOKEN`; pairing/worker credentials remain private |
| UTM Vision | `devices.utm_vision_runtime`, pose tracker | camera profile/calibration, runtime/pose artifacts | device paths and ROS environment; no shared secret in current bridge |
| CAE Computation | `devices.cae` and adapter defaults | CAE/CalculiX/PINN artifacts; frozen run/loop/specimen FEM job records and field outputs | executable paths; no network credential in current adapters |
| Base and Simulators | simulator/default sections | deterministic fake artifacts where applicable | none |

## Mode and Fallback Matrix

**A TEST label is not a no-hardware guarantee.** Runtime mode, selected
transport, per-agent control settings and explicit promotion/execute gates
jointly determine the effect. Workspace actions also have their own contracts.

| Boundary | Test behavior | Live behavior | Fallback rule |
|---|---|---|---|
| Printer Fleet | selected virtual provider or explicitly configured real-printer promotion | routes to selected configured profile | automatic provider fallback is disabled by default |
| Bambu X2D | file/simulated paths or real transport under explicit test-promotion settings | connection and execution gates govern network/publish actions | skipped deposition is not proof that no ejection or other motion occurs |
| Prusa MK4S | virtual PrusaLink/dry-run or configured test promotion | real network governed by mode/transport and live flags | legacy promotion can fall back to virtual after failed connectivity; explicit installed-printer path returns a communication failure |
| LeRobot | fake profiles/sessions/artifacts | profile safety limits and operator confirmation gate processes | profile substitution is explicit, not automatic |
| Windows PyAutoGUI | simulator by ordinary test path; configured real test promotion or explicit worker requests may reach a real host | selected worker, token, execute gate, payload validation and applicable preflight | worker selection is explicit; TEST does not remove desktop effects |
| UTM Vision | virtual bridge/pose allowed where configured | ROS workspace, process, topic, camera readiness required | virtual evidence must remain labeled test |
| CAE Computation | deterministic facade; guarded/unavailable adapters | solver execution requires executable and runtime gate | missing solver/PINN returns unavailable, not fabricated live output |
| Base and Simulators | always deterministic test path | not a live path | never promoted implicitly |

`device.health` currently supplies the selected printer's health but includes
placeholder readiness strings for camera, robot and equipment. It is not an
independent live probe of all devices; use the owning readiness/status path.

## Effect, Gate, and Recovery Matrix

| Boundary | Highest possible effect | Required gates before effect | Stop/status owner | Unknown-effect rule |
|---|---|---|---|---|
| Printer Fleet | physical printer action | explicit provider, mode, capability, start/ejection proof gates | provider/API/operator/Guardian | inspect selected provider and printer state before replay |
| Bambu X2D | upload/start/control or ejection motion | live connection, artifact identity, prestart/start gate, configured proof | MQTT/report API, operator/Guardian | do not republish after timeout until telemetry and artifact/job identity are reconciled |
| Prusa MK4S | upload/start/ejection motion | live allow flags, G-code validation, status/storage, calibration and vision conditions | PrusaLink/operator/Guardian | query job/status/file before upload or start retry |
| LeRobot | rollout/replay/teleop and ActiveCam motion; subprocess effects | applicable profile/ports/policy checks, execution permissions and agent context | session-specific rollout/replay/teleop status and stop APIs | reconcile process termination and fresh visual evidence before motion restart |
| Windows PyAutoGUI | desktop actions and instrument initiation | selected candidate, token, execute gate, validated exact workflow and agent preflight | worker/runtime status and existing stop path; agent evaluates recovery | inspect execution ID, completed blocks, screenshot, logs and exported files; never repeat completed or unknown-effect work |
| UTM Vision | observation; runtime process and calibration side effects | config/process/camera probe; freshness for downstream use | runtime/calibration stop APIs | stale/missing frame blocks handoff; process state is queried before restart |
| CAE Computation | local/external subprocess and filesystem | input schema, executable availability, preparation receipt and applicable solver/PINN gate | process handler; scoped Analysis job cancel request | retain deck/log/partial artifacts; optional FEM failure does not replace or invalidate accepted measured data |
| Base and Simulators | local deterministic state/files only | test-mode selection | caller/test harness | simulated success cannot resolve live unknown state |

## Evidence Matrix

| Boundary | Primary evidence |
|---|---|
| Printer Fleet | selected profile, selection reason, normalized workflow result, health |
| Bambu X2D | source/patched hashes, slicer output, probe/report telemetry, publish draft/result, pre/post eject and bed-clear proof |
| Prusa MK4S | source/G-code identity, validation, upload/start response, job/status snapshots, ejection calibration/evidence |
| LeRobot | session/task identities, termination state, commands/logs, measured telemetry, ActiveCam/camera evidence, datasets/checkpoints and optional Isaac summaries |
| Windows PyAutoGUI | durable execution ID/projection, exact Flow/Skill versions, completed-block records, screenshot identity, step/request logs, CSV/artifact metadata and readiness checks |
| UTM Vision | process graph/status, topic/frame timestamps, camera profile/calibration, pose snapshot and release record |
| CAE Computation | frozen source hashes, preparation receipt and mesh quality, solver logs/curve/fields, run/loop/specimen job evidence and optional PINN registry |
| Base and Simulators | labeled synthetic response and fixture artifacts |

## Runtime and Evidence APIs

These are selected current interfaces, not instructions to execute live tests.

| Surface | Purpose | Ownership / effect |
|---|---|---|
| `GET /api/equipment/runtime/current` | Latest execution, optionally scoped by run/profile/execution | Read durable Equipment Runtime state |
| `GET /api/equipment/runtime/executions` and `GET /api/equipment/runtime/executions/{execution_id}` | List records or inspect one execution | Read-only; does not replay a Flow |
| `/api/equipment/skills/*` and `/api/equipment/profiles/*` | Versioned workflow/profile lifecycle and tests | Operator actions may deploy or execute; inspect the individual method/contract |
| `POST /api/equipment/windows/pair` and `/select` | Pair or select the worker under that prefix | Connection state, not scientific completion |
| `POST /api/lerobot/replay/start`, `/status`, `/stop` | Configured replay session lifecycle | Start may move a robot; status and stop are separate requests |
| `GET /api/analysis/fem/jobs` | Read matching run/loop/specimen FEM jobs | Analysis-owned; does not start/resume computation |
| `POST /api/analysis/fem/jobs/{job_id}/cancel` | Request cancellation of a job within the supplied run | Computation only; acknowledgement is not proof of termination |
| `GET /api/cae/fields` and its `/metadata`, `/section`, `/render` routes | Read saved fields and perform local postprocessing | No solver invocation or physical device action |

Equipment's bounded LLM selection/review stays in the
[Equipment Agent](../agents/equipment_agent.md), outside the middle of a stored
Flow. Eligible recovery requires current evidence and the existing no-repeat
gates. Analysis owns optional FEM scheduling and review; the CAE adapter owns
preparation/solving. Valid measured observations can reach Knowledge/BO without
waiting for optional FEM, while simulation-only paths still await their solver.

## Supporting Controller Transport

| Service | Entry / protocol | Effect and evidence | Reference |
|---|---|---|---|
| PLC safety transport | `/api/plc/*`, graph `plc_bridge`; MC Protocol Type 3E | Bounded register handshake and Controller state projection; cached snapshots/events; no arbitrary agent register-write tool | [PLC operator guide](plc_safety_bridge.md) |

PLC integration is separate from task-agent tool selection and does not replace
hardware safety controls. Its guide owns configuration, procedure and evidence.

## Compatibility and Ownership Rules

- `/api/bridges` is a graph-metadata projection, not the complete executable
  provider registry.
- An API workspace does not own every action it displays; ownership follows the
  handler, registered tool/resource, manager, and provider.
- UI descriptors and model output do not grant bridge authority.
- Provider substitution creates a different evaluated configuration.
- A pure artifact transformation is not a physical action, but publishing its
  output can cross a physical effect boundary.
- Test and virtual-live results remain labeled and cannot establish hardware
  compatibility.

## Limitations and Known Gaps

The matrix curates functional families rather than every payload field and
private helper. Bambu is the checked-in printer default while graph
metadata exposes a Prusa-named bridge. CalculiX and PINN are registered tools
inside the CAE capability but are not separate `/api/bridges` entries. Live
device/protocol combinations were not exhaustively exercised. Legacy graph
labels, including a named robot policy, do not enumerate current saved profiles.

## Verification

Updated on 2026-09-11 by static inspection at `cf8cb9f`: graph metadata,
bootstrap/tool/resource registration, owning implementations, Equipment Runtime,
route declarations and Analysis job/field routers. Documentation checks cover
the edited files; this update does not import/start the application, probe
devices, execute workflows, launch a robot, or run a solver.

Existing references and guides retain their individually dated validation
records. The live `/openapi.json` is the authoritative schema for a deployed
instance; source inspection is not a new end-to-end hardware validation.

## Related Documents

- [Device Bridge Reference Index](README.md)
- [Agent API and Connection Matrix](../agents/agent_api_connection_matrix.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
