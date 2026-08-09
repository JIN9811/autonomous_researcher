---
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - maintainer
scope:
  - device_bridges
  - providers
  - runtime_sidecars
  - api_connections
summary: Canonical entry point for ATR device-bridge roles, APIs, protocols, effects, evidence, and recovery boundaries.
related_docs:
  - docs/device_bridges/bridge_api_connection_matrix.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/paper/02_system_architecture.md
  - docs/paper/appendix_a_interfaces.md
  - docs/standards/documentation_standard.md
supersedes: []
---

# Device Bridge Reference Index

## Summary

This index is the canonical entry point for the eight operator-visible device
bridge boundaries in ATR. A boundary may be a manager, provider, runtime
sidecar, external-computation adapter, or deterministic test substitute. The
classification is explicit because `/api/bridges`, the Tool Registry, API
workspaces, and Python subclasses do not expose identical inventories.

The implementation baseline is `188a1d6`. Later commits in this documentation
series change documents, figures, validation, and tests—not bridge runtime
behavior.

## 한국어 안내

각 Reference는 실제 역할, API와 도구, 외부 연결, 설정·비밀정보 경계, 실행
모드, 물리·데스크톱 효과, 증거, 실패 후 재시도 조건을 코드 기준으로
정리합니다. 빠르게 확인하려면 `Actual Role`, `Connections and Protocols`,
`Safety, Approval, and Effect Boundary`, `Errors, Timeouts, and Recovery`
순서로 읽으십시오.

## Scope and Classification

The canonical unit is an operational capability, not one source file. Labels
used below mean:

| Label | Meaning |
|---|---|
| `graph_projected` | represented in `graph.metadata.device_bridges` and `/api/bridges` |
| `tool_registered` | callable through the runtime Tool Registry |
| `api_exposed` | has an operator-facing FastAPI family |
| `provider` | selected behind a manager or shared tool contract |
| `runtime_sidecar` | manages a process, stream, observer, or evidence service |
| `artifact_transformer` | changes files but cannot itself command a device |
| `test_only` | deterministic substitute; does not establish live compatibility |

## Canonical Inventory and Figure Navigation

| Boundary | Classification | Primary consumers | Canonical Reference | Figures |
|---|---|---|---|---|
| Printer Fleet | `tool_registered`, `api_exposed` | Specimen, Guardian, operator | [Printer Fleet](printer_fleet_bridge.md) | [Flow](assets/figures/printer_fleet_01_system_handoffs.svg) · [Execution](assets/figures/printer_fleet_02_execution_effect_boundary.svg) · [Connections](assets/figures/printer_fleet_03_api_connection_architecture.svg) |
| Bambu Lab X2D | `provider`, `api_exposed`, `artifact_transformer` | Printer Fleet, Specimen, operator | [Bambu X2D](bambu_x2d_bridge.md) | [Flow](assets/figures/bambu_x2d_01_system_handoffs.svg) · [Execution](assets/figures/bambu_x2d_02_execution_effect_boundary.svg) · [Connections](assets/figures/bambu_x2d_03_api_connection_architecture.svg) |
| Prusa MK4S | `graph_projected`, `provider`, `tool_registered`, `api_exposed` | Printer Fleet, Specimen, operator | [Prusa MK4S](prusa_mk4s_bridge.md) | [Flow](assets/figures/prusa_mk4s_01_system_handoffs.svg) · [Execution](assets/figures/prusa_mk4s_02_execution_effect_boundary.svg) · [Connections](assets/figures/prusa_mk4s_03_api_connection_architecture.svg) |
| LeRobot | `graph_projected`, `tool_registered`, `api_exposed`, `runtime_sidecar` | Manipulation, Vision, Guardian, operator | [LeRobot](lerobot_bridge.md) | [Flow](assets/figures/lerobot_01_system_handoffs.svg) · [Execution](assets/figures/lerobot_02_execution_effect_boundary.svg) · [Connections](assets/figures/lerobot_03_api_connection_architecture.svg) |
| Windows PyAutoGUI | `graph_projected`, `tool_registered`, `api_exposed`, `runtime_sidecar` | Equipment, Vision, Analysis, Guardian, operator | [Windows PyAutoGUI](windows_pyautogui_bridge.md) | [Flow](assets/figures/windows_pyautogui_01_system_handoffs.svg) · [Execution](assets/figures/windows_pyautogui_02_execution_effect_boundary.svg) · [Connections](assets/figures/windows_pyautogui_03_api_connection_architecture.svg) |
| UTM Vision | `graph_projected`, `api_exposed`, `runtime_sidecar` | Vision, Equipment, Manipulation, operator | [UTM Vision](utm_vision_bridge.md) | [Flow](assets/figures/utm_vision_01_system_handoffs.svg) · [Execution](assets/figures/utm_vision_02_execution_effect_boundary.svg) · [Connections](assets/figures/utm_vision_03_api_connection_architecture.svg) |
| CAE Computation | `graph_projected`, `tool_registered`, `api_exposed`, `runtime_sidecar` | Analysis, Guardian, operator | [CAE Computation](cae_computation_bridges.md) | [Flow](assets/figures/cae_computation_01_system_handoffs.svg) · [Execution](assets/figures/cae_computation_02_execution_effect_boundary.svg) · [Connections](assets/figures/cae_computation_03_api_connection_architecture.svg) |
| Base and Simulators | `test_only` | Tool fixtures and test-mode agents | [Base and Simulators](base_simulator_bridges.md) | [Flow](assets/figures/base_simulator_01_system_handoffs.svg) · [Execution](assets/figures/base_simulator_02_execution_effect_boundary.svg) · [Connections](assets/figures/base_simulator_03_api_connection_architecture.svg) |

`camera_utm_bridge` is the graph-projected identifier for the UTM/visual
evidence capability. CAE's graph entry names the facade, while CalculiX and
PINN are separately registered implementations within the computation
boundary. Bambu is the configured default printer provider but is not a
separate graph bridge entry at this baseline.

## Recommended Reading Paths

| Reader | Start here | Then read |
|---|---|---|
| Paper reviewer | [Matrix](bridge_api_connection_matrix.md) | figures, known gaps, paper interfaces appendix |
| Operator | device-specific Reference | configuration, effect gate, recovery, linked hardware Guide |
| Agent developer | agent Reference | bridge Reference tools/API sections and matrix |
| Integrator | connection figure | protocol, authentication, modes, status/evidence contract |
| Maintainer | source-of-truth and verification sections | validator rules and update checklist |

## Authority and Conflict Resolution

Use this order for current behavior:

```text
executable code and checked-in configuration
-> active Documentation Standard
-> active device-bridge Reference and matrix
-> active hardware/runtime Guide
-> approved Design and implementation Plan
-> time-bounded Evidence or legacy guideline
```

A Reference describes observed implementation. It does not certify a device,
protocol, safety control, or scientific result. When code conflicts with a
Reference, code is current and the document has drift.

## Legacy and Procedural Detail

| Existing Guide | Canonical Reference | Continued use |
|---|---|---|
| `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md` | [Bambu X2D](bambu_x2d_bridge.md) | Bambu setup, artifact and supervised validation detail |
| `docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt` | [Prusa MK4S](prusa_mk4s_bridge.md) | Phase-one Prusa workflow context |
| `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md` | [LeRobot](lerobot_bridge.md) | ROBOTIS/LeRobot operating detail |
| `docs/hardware/windows_pyautogui_equipment_agent_guideline.md` | [Windows PyAutoGUI](windows_pyautogui_bridge.md) | equipment console, proof, and live-operation detail |
| `docs/hardware/windows_pyautogui_bridge_windows_setup.md` | [Windows PyAutoGUI](windows_pyautogui_bridge.md) | Windows installation procedure |
| `docs/hardware/utm_ros_vision_runtime_bridge.md` | [UTM Vision](utm_vision_bridge.md) | ROS/camera installation and operation |
| `docs/hardware/isaac_sim_robotis_omx_mirror_mode.md` | [LeRobot](lerobot_bridge.md) | Isaac mirror-mode procedure |

## Verification Method

- graph classification: `graphs/configs/atr_closed_loop.yaml`;
- tool/resource registration: `app/bootstrap.py` and `mcp_tools/*_tools.py`;
- runtime behavior: owning `device_bridges/*.py` implementations;
- API families: imported FastAPI routes and handlers in `app/main.py`;
- configuration: `configs/devices.yaml` and `configs/lerobot.yaml`;
- operator behavior: linked Guides and focused bridge/API tests.

The figures are explanatory `inspection` projections. Dashed paths are
conditional, optional, compatibility, or test paths; they are not evidence of
successful live execution.

## Update Checklist

When a bridge contract changes:

1. update the owning implementation/configuration and tests;
2. update its Reference and three `.dot` sources;
3. re-render the matching SVG files;
4. update the matrix for entry, protocol, effect, evidence, or recovery drift;
5. update graph/tool classification when registration changes;
6. update root and index navigation if a canonical boundary changes;
7. run documentation, paper, figure-freshness, and focused bridge validation.

## Limitations and Known Gaps

The inventory is capability-oriented and therefore not a class-by-class API
catalog. The graph projection currently under-represents the Bambu default and
the separately registered CalculiX/PINN paths. Optional device, solver, camera,
ROS, serial, and Windows combinations were not all exercised by this
documentation inspection.

## Index Verification

Verified on 2026-08-09 against implementation baseline `188a1d6`, the primary
graph metadata, runtime bootstrap registrations, bridge implementations,
configuration, API handlers, and focused test inventory.

## Related Documents

- [Bridge API and Connection Matrix](bridge_api_connection_matrix.md)
- [Agent Reference Index](../agents/README.md)
- [System Architecture](../paper/02_system_architecture.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Documentation Standard](../standards/documentation_standard.md)
