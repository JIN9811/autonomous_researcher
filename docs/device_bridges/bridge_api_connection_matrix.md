---
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
  - configs/devices.yaml
  - configs/lerobot.yaml
  - graphs/configs/atr_closed_loop.yaml
last_verified: 2026-08-09
verified_against: 188a1d6
related_docs:
  - docs/device_bridges/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/paper/appendix_a_interfaces.md
supersedes: []
---

# Device Bridge API and Connection Matrix

## Summary

This Reference compares the eight canonical device-bridge boundaries. It
groups routes by function rather than replacing `/openapi.json`; individual
References own payload, lifecycle, state, and recovery detail.

## Scope

The matrix covers manager/provider routing, registered tools, runtime
sidecars, external computation, and deterministic substitutes at baseline
`188a1d6`. `physical_possible` means an allowed live path can reach motion; it
does not say that the checked-in default performs that motion.

## Source of Truth

- `device_bridges/` implementations;
- `mcp_tools/*_tools.py` and `app/bootstrap.py` registration;
- `app/main.py` imported routes;
- `configs/devices.yaml` and `configs/lerobot.yaml`;
- `graphs/configs/atr_closed_loop.yaml` bridge projection.

## Boundary and Entry Matrix

| Boundary | Classification | Primary agent | Tool/resource entry | Operator API family |
|---|---|---|---|---|
| Printer Fleet | tool/API manager | Specimen, Guardian | `printer.prepare`, `device.health` | `/api/printer/fleet`, `/connection`, `/profile`, `/status` |
| Bambu X2D | provider + artifact transformer | Specimen | selected by Printer Fleet | Bambu slice/patch/probe/start/bed-clear/video under `/api/printer/*` |
| Prusa MK4S | graph-projected provider | Specimen | `printer.prepare` selected provider | shared `/api/printer/*`, autoejection test/status |
| LeRobot | graph/tool/API runtime | Manipulation, Vision | `lerobot.bridge`, `lerobot.*` | `/api/lerobot/*` |
| Windows PyAutoGUI | graph/tool/API runtime | Equipment | `equipment.pyautogui.*` | `/api/equipment/windows/*` |
| UTM Vision | graph/API sidecar | Vision, Equipment | camera/UTM tools plus runtime singletons | `/api/equipment/utm-runtime/*`, specimen-pose and camera routes |
| CAE Computation | graph/tool/API computation | Analysis | `cae.*`, `calculix.*`, `pinn.*`; resources for CalculiX/PINN | `/api/cae/config`, `/api/cae/run` |
| Base and Simulators | test-only substitutes | test-mode agents | mock tools or direct test fixtures | no dedicated owned API |

## Connection Matrix

| Boundary | Local layer | Protocol/process | External target | Return path |
|---|---|---|---|---|
| Printer Fleet | profile selector and memory | in-process provider dispatch | selected Bambu or Prusa provider | normalized selection, health, workflow result |
| Bambu X2D | slicer, MQTT/video/FTPS clients | subprocess, MQTT TLS, FTPS, LAN video, HTTP artifact URL | Bambu Studio and printer | report telemetry, probe result, hashes, video/status, bed-clear proof |
| Prusa MK4S | slicer, client, workflow | subprocess and PrusaLink HTTP auth | PrusaSlicer and MK4S | status/job/storage, upload/start result, G-code/ejection evidence |
| LeRobot | profile/session/process manager | subprocess, serial, camera, local HTTP sidecars/files | robot, leader/follower ports, policy/train/Isaac processes | session status/logs, telemetry, datasets, checkpoints, render/Mimic artifacts |
| Windows PyAutoGUI | connection/program/locator client | token-gated HTTP | Windows bridge server and desktop application | health, screenshot, step trace, request log, proof package |
| UTM Vision | ROS process/stream/pose managers | ROS 2 topics, subprocess, camera/USB, MJPEG | UTM workspace, YOLO/camera, D455F | graph/status, frames, calibration, pose/evidence artifacts |
| CAE Computation | facade/job/model adapters | filesystem and guarded subprocess | Gmsh/CalculiX/postprocessor, optional PINN environment | decks, FRD/VTU/logs, metrics, dataset/model registry |
| Base and Simulators | `BaseBridge` and deterministic fixtures | in-process only | no required external target | schema-shaped simulated responses |

## Configuration and Secret Matrix

| Boundary | Checked-in configuration | Mutable memory/artifacts | Secret or credential names |
|---|---|---|---|
| Printer Fleet | `configs/devices.yaml` printer profiles | `memory/printer_fleet.json` | provider-specific; values never documented |
| Bambu X2D | `devices.printer.bambu`, `autoejection` | Bambu connection/autoejection/bed-clear memory; sliced artifacts | printer access code/serial through memory; executable env name only |
| Prusa MK4S | `devices.printer.live/slicer/ejection` | Prusa connection/profile and G-code artifacts | `PRUSA_USERNAME`, `PRUSA_PASSWORD`, `PRUSA_API_KEY` |
| LeRobot | `configs/lerobot.yaml` | port/session/profile/calibration, datasets, outputs, logs | `HF_TOKEN` or token file; no token value in docs |
| Windows PyAutoGUI | `devices.equipment.windows_pyautogui` | connection, UTM profile, locator, equipment artifacts | `WINDOWS_PYAUTOGUI_BRIDGE_URL`, `WINDOWS_PYAUTOGUI_BRIDGE_TOKEN` |
| UTM Vision | `devices.utm_vision_runtime`, pose tracker | camera profile/calibration, runtime/pose artifacts | device paths and ROS environment; no shared secret in current bridge |
| CAE Computation | `devices.cae` and adapter defaults | CAE/CalculiX/PINN artifact roots and registry | executable paths; no network credential in current adapters |
| Base and Simulators | simulator/default sections | deterministic fake artifacts where applicable | none |

## Mode and Fallback Matrix

| Boundary | Test behavior | Live behavior | Fallback rule |
|---|---|---|---|
| Printer Fleet | routes to selected virtual/test provider | routes only to selected configured profile | automatic provider fallback is disabled by default |
| Bambu X2D | synthetic/probe-safe responses and file transformation | network/publish paths require connection and explicit gates | no silent fallback to Prusa |
| Prusa MK4S | virtual PrusaLink and dry-run workflow | real network allowed only by mode and live flags | test-to-real promotion must be deliberate |
| LeRobot | fake profiles/sessions/artifacts | profile safety limits and operator confirmation gate processes | profile substitution is explicit, not automatic |
| Windows PyAutoGUI | simulator or virtual promotion | token, candidate health, `allow_live_execute`, preflight | local candidate selection is explicit |
| UTM Vision | virtual bridge/pose allowed where configured | ROS workspace, process, topic, camera readiness required | virtual evidence must remain labeled test |
| CAE Computation | deterministic facade; guarded/unavailable adapters | solver execution requires executable and runtime gate | missing solver/PINN returns unavailable, not fabricated live output |
| Base and Simulators | always deterministic test path | not a live path | never promoted implicitly |

## Effect, Gate, and Recovery Matrix

| Boundary | Highest possible effect | Required gates before effect | Stop/status owner | Unknown-effect rule |
|---|---|---|---|---|
| Printer Fleet | physical printer action | explicit provider, mode, capability, start/ejection proof gates | provider/API/operator/Guardian | inspect selected provider and printer state before replay |
| Bambu X2D | upload/start/control or ejection motion | live connection, artifact identity, prestart/start gate, configured proof | MQTT/report API, operator/Guardian | do not republish after timeout until telemetry and artifact/job identity are reconciled |
| Prusa MK4S | upload/start/ejection motion | live allow flags, G-code validation, status/storage, calibration and vision conditions | PrusaLink/operator/Guardian | query job/status/file before upload or start retry |
| LeRobot | robot/teleop motion; subprocess effects | valid profile/ports/policy, live enable, operator confirmation, Guardian/Vision context | rollout/teleop status and stop APIs | inspect process, telemetry, scene, and session evidence before motion restart |
| Windows PyAutoGUI | desktop actions and instrument initiation | token, healthy selected candidate, allowlist/limits, live gate, preflight/proof | bridge stop/recovery macro, operator/Guardian | inspect desktop, request log, exported file, and proof before repeating steps |
| UTM Vision | observation; runtime process and calibration side effects | config/process/camera probe; freshness for downstream use | runtime/calibration stop APIs | stale/missing frame blocks handoff; process state is queried before restart |
| CAE Computation | local/external subprocess and filesystem | input schema, executable health, runtime solver/PINN gate | bounded process/job handler | retain deck/log/partial artifacts; never label an incomplete solve as measurement |
| Base and Simulators | local deterministic state/files only | test-mode selection | caller/test harness | simulated success cannot resolve live unknown state |

## Evidence Matrix

| Boundary | Primary evidence |
|---|---|
| Printer Fleet | selected profile, selection reason, normalized workflow result, health |
| Bambu X2D | source/patched hashes, slicer output, probe/report telemetry, publish draft/result, pre/post eject and bed-clear proof |
| Prusa MK4S | source/G-code identity, validation, upload/start response, job/status snapshots, ejection calibration/evidence |
| LeRobot | session records, commands, logs, port baseline, camera artifacts, datasets/checkpoints, rollout and Isaac summaries |
| Windows PyAutoGUI | screenshots, locator identity, step trace, request log, CSV/artifact metadata, proof package/completion audit |
| UTM Vision | process graph/status, topic/frame timestamps, camera profile/calibration, pose snapshot and release record |
| CAE Computation | input deck/hash, solver health/log, FRD/VTU/result metrics, PINN dataset/model registry |
| Base and Simulators | labeled synthetic response and fixture artifacts |

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
private helper. Bambu is the current configured printer default while graph
metadata exposes a Prusa-named bridge. CalculiX and PINN are registered tools
inside the CAE capability but are not separate `/api/bridges` entries. Live
device/protocol combinations were not exhaustively exercised.

## Verification

Verified on 2026-08-09 by inspecting the primary graph, bootstrap and tool
registration, bridge implementations, current configuration, API handlers,
hardware Guides, and focused tests at baseline `188a1d6`.

## Related Documents

- [Device Bridge Reference Index](README.md)
- [Agent API and Connection Matrix](../agents/agent_api_connection_matrix.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Current Code Snapshot](../runtime/current_code_snapshot.md)
