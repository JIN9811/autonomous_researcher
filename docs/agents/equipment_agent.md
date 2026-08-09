---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, operator, developer, maintainer]
scope: [agents, equipment, pyautogui, utm, device_bridges]
summary: Current contract for resolving validated equipment profiles and skills, executing bounded protocols, and handing evidence to Analysis.
source_of_truth:
  - agents/equipment_agent.py
  - graphs/modules/equipment/module.yaml
  - utils/equipment_skill_runtime.py
  - device_bridges/windows_pyautogui_bridge.py
  - device_bridges/utm_runtime_bridge.py
  - app/main.py
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/manipulation_agent.md
  - docs/agents/analysis_agent.md
  - docs/hardware/windows_pyautogui_equipment_agent_guideline.md
  - docs/hardware/utm_ros_vision_runtime_bridge.md
supersedes: []
---

# Lab Equipment Agent Reference

## Summary

`LabEquipmentAgent` resolves an exact equipment profile or recorded skill,
validates its bridge contract, executes deterministic program segments through
registered tools, bounds exception recovery through Guardian, and validates the
measurement/evidence handoff to Analysis.

## Scope

Included are Windows/PyAutoGUI workers, recorded skills, equipment profiles,
UTM protocol/runtime, locators/screenshots, preflight, proof, and completion
audit. The agent does not generate arbitrary desktop commands or interpret the
scientific result.

## Source of Truth

Equipment agent/module, equipment skill runtime, Windows/PyAutoGUI and UTM
bridges, API routes, and hardware/runtime Guides.

## Actual Role

| Does | Does not |
|---|---|
| Resolve exact profile/skill/version | Accept approximate or arbitrary program identity |
| Validate bridge and skill contract | Give an LLM unrestricted desktop/shell access |
| Execute allowlisted deterministic segments | Bypass Guardian/operator/live preflight |
| Capture request, screenshot, protocol and proof evidence | Treat request acceptance as completed measurement |
| Handoff identifiable artifacts to Analysis | Compute the final scientific objective |

## Closed-Loop Position and Handoffs

![Equipment closed-loop position and handoffs](assets/figures/equipment_01_closed_loop_handoffs.svg)

**Figure Equipment-1.** Fresh placement evidence and an exact enabled
profile/skill/protocol become bounded desktop and instrument segments; only a
complete measurement/proof package reaches Analysis. This is an
`inspection`-backed projection of baseline `0b7627b`, not evidence that a live
protocol completed safely or correctly.

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Vision/Manipulation | verified specimen/fixture state | permit protocol | fresh placement evidence |
| In | Orchestrator/Guardian | action, approval, mode, constraints | governed execution | policy/approval/budget |
| In | Profile/skill registry | exact configuration/version | deterministic action | validation/deployment/enabled state |
| Out | Analysis | equipment artifact/handoff | parse and evaluate measurement | file identity/evidence completeness |
| Out | Guardian/Knowledge | tool/proof/failure records | safety/provenance | persisted result |

## Inputs and Outputs

Input is `OrchestratorState` plus equipment profile, skill/program version,
validated parameters, bridge target, placement evidence, approvals, and mode.
Output merged into state includes equipment result/report/handoff, program and
segment state, request log, screenshots/locators, UTM/runtime data, proof and
completion audit, decisions, metrics, errors, and artifact references.

## Internal Execution

| Step ID | Work | Boundary/output |
|---|---|---|
| `01_resolve_equipment_profile` | exact profile/skill/version | unresolved identity blocks |
| `02_validate_bridge_contract` | bridge/capability/skill schema | invalid/unavailable blocks |
| `03_execute_registered_protocol` | deterministic segments | bounded tool result |
| `04_exception_recovery_gate` | classify/recover through Guardian | no unrestricted recovery |
| `05_validate_evidence_handoff` | artifact/proof completeness | Analysis handoff or review |

![Equipment internal execution and effect boundary](assets/figures/equipment_02_execution_effect_boundary.svg)

**Figure Equipment-2.** Five internal entries and four registered tools keep
identity resolution, bridge/capability validation, deterministic segments,
bounded recovery, and evidence handoff distinct. Desktop and instrument effects
occur only after placement, preflight, policy, and approval gates. This
`inspection` figure does not claim independently scheduled steps.

### Execution trace details

| Phase | State read | Gate/transformation | Evidence written | Recovery boundary |
|---|---|---|---|---|
| Resolve | equipment/profile/skill/program/version IDs | exact registry lookup and enabled-state check | resolved immutable identities | ambiguous or missing identity blocks |
| Validate | bridge health, capability schema, placement, mode and approval | live preflight and allowlisted parameter validation | readiness snapshot and blockers | model formatting cannot create commands |
| Execute | validated deterministic segment plan | invoke registered worker/UTM segment | request, segment transitions and command result | no unregistered recovery segment |
| Observe | desktop screenshot/locator or instrument/runtime state | compare expected postcondition | image/status/measurement references | timeout with unknown effect requires inspection |
| Recover | classified failure, current proof and safety state | continue bounded recovery, stop, or escalate | corrective action and Guardian result | retry only after known no-effect or resolved state |
| Handoff | measurement identity and complete proof | validate Analysis package | artifact hash, report and completion audit | partial output remains evidence, not a complete result |

## API Surface

| Class | Method | Path/family | Effect | Notes |
|---|---|---|---|---|
| shared | GET/POST | `/api/bridges`, `/api/bridges/{bridge_id}/actions` | read_only/local_state | normalized registry and descriptors |
| connected | GET/POST | `/api/equipment/utm-runtime/status`, `/start`, `/stop`, `/probe`, `/graph`, `/frame`, `/frame-stream.mjpeg` | external_service/read_only | ROS/runtime lifecycle and evidence |
| operator | GET/POST | `/api/equipment/utm-runtime/camera-*` | read_only/local_state/external_service | devices, probe, apply, calibrate |
| operator | POST | `/api/equipment/windows/live-preflight`, `/live-validation` | read_only/local_state | live gates/evidence |
| operator | GET/POST/DELETE | `/api/equipment/skills*` | local_state | draft, annotate, compile, validate, deploy, enable, test, delete |
| operator | GET/POST | `/api/equipment/profiles*` | read_only/local_state/physical_possible | state, preflight, test |
| operator | GET/POST | `/api/equipment/windows/config`, `/readiness`, `/discover`, `/connect`, `/select`, `/delete`, `/test` | read_only/local_state/external_service | worker lifecycle |
| operator | GET/POST | `/api/equipment/windows/local-bridge/*` | local_state/external_service | managed local bridge |
| connected | POST | `/api/equipment/windows/run-program` | physical_possible | executes allowlisted program |
| connected | GET/POST | `/api/equipment/windows/locators`, `/screenshot`, `/capture-locator` | read_only/local_state | visual automation evidence |
| operator | GET/POST | `/api/equipment/windows/proof-package`, `/proof-package/verify`, `/evidence-audit`, `/completion-audit`, `/vision-proof-draft` | read_only/local_state | proof/release review |

## Tools and Connections

| Tool/service | Boundary | Effect | Evidence |
|---|---|---|---|
| `equipment.pyautogui.health` | Windows bridge | read_only | health snapshot |
| `equipment.pyautogui.list_programs` | worker registry | read_only | program/version list |
| `equipment.pyautogui.run` | allowlisted worker program | physical_possible | request/segments/screenshots/result |
| `utm.run_protocol` | UTM bridge/runtime | physical_possible | protocol/measurement/proof |
| LLM `tool_formatting` | selected model | model | bounded formatting only |
| Equipment skill runtime | versioned local packages | local_state/physical_possible | manifest/validation/deployment |
| UTM ROS runtime | local/remote ROS and camera | external_service/physical_possible | graph/frame/status |

![Equipment API and connection architecture](assets/figures/equipment_03_api_connection_architecture.svg)

**Figure Equipment-3.** Registry, skill/profile, Windows worker, and UTM
runtime/camera surfaces reach desktop and instrument effects only through exact
identity, bridge, placement, Guardian, and operator gates; health, screenshots,
frames, measurements, and audits return as evidence. This `inspection` figure
is not live protocol validation.

### Connection lifecycle

| Connection | Resolve/preflight | Invoke/observe | Persist/recover |
|---|---|---|---|
| Skill runtime | draft/compile/validate/deploy/enable exact version | select registered program and parameters | retain manifest, validation and deployment identity |
| Equipment profile | profile, capability and state/readiness | preflight or bounded test | explicit provider/profile selection; no silent fallback |
| Windows worker | discover/connect/readiness/local bridge | run allowlisted program and inspect locators/screenshots | request log, segment state and proof package |
| UTM ROS runtime | status/probe/graph/camera mapping | start/stop/frame/stream and protocol connection | graph/frame/status plus measurement identity |
| Desktop/instrument | current precondition and stop procedure | bounded physical/desktop action | inspect postcondition before retry after uncertainty |
| Audit/release | proof, evidence and completion packages | verify without rewriting source evidence | incomplete audit blocks Analysis completion claim |

Neither the workspace, a model response, nor a module UI descriptor grants a
bypass around the registered tool, worker/bridge, and Guardian/operator path.

## State, Events, Artifacts, and Storage

Profiles and worker connections are local configuration state. Skills are
versioned packages with draft/annotation/compiled/validated/deployed/enabled
states. Runs store action parameters, segment transitions, screenshots,
locators, measurement files, tool records, Guardian results, proof packages,
and completion audits. External desktop/instrument state is separate and must
be observed.

## Modes and Fallbacks

Test uses virtual/fake bridges or validation-only execution. Replay consumes
recorded evidence. Browser controls services but is not physical proof. Live
requires exact worker/profile/skill, readiness, placement evidence, Guardian,
operator scope, and stop procedure. Local bridge selection is explicit;
fallback messages/events remain recorded.

## Safety, Approval, and Effect Boundary

Both desktop and instrument actions are `physical_possible`. Live requires
preflight, validated enabled skill/profile, allowlisted parameters, current
Vision/placement state, Guardian/operator approval where configured, bounded
segments, and a stop path. LLM output cannot create arbitrary commands.

## Errors and Recovery

Unknown profile/skill or invalid bridge blocks before action. Locator/capture
failure can use only compiled bounded recovery. Timeout with unknown desktop or
instrument effect requires screenshot/status/instrument inspection and
Guardian/operator review before repeating. Partial measurement files remain
evidence and are not silently treated as complete.

## Operator and GUI Surfaces

Windows Equipment workspace manages worker discovery, connection, readiness,
profiles, skills, locators, screenshots, program execution, and proof. Vision
UTM workspace manages ROS graph/camera/runtime. Live GUI reports equipment
state, handoff, errors, and evidence.

## Current Verification

Verified against all five internal IDs, four tools, 57 equipment/bridge prefix
routes, skill/profile runtime, Windows bridge, and UTM runtime at baseline
`0b7627b`. No new physical protocol was executed.

## Limitations and Known Gaps

No paper-scoped evidence establishes general desktop robustness, UTM accuracy,
protocol completion, locator recovery, or live stop latency. Vendor software,
ROS, cameras, and workers are optional/environment-specific.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Manipulation](manipulation_agent.md)
- [Analysis](analysis_agent.md)
- [Windows Equipment Guide](../hardware/windows_pyautogui_equipment_agent_guideline.md)
- [UTM ROS Vision Guide](../hardware/utm_ros_vision_runtime_bridge.md)
- [Completion Audit](../hardware/evidence/lab_equipment_utm_visual_control_completion_audit.md)
