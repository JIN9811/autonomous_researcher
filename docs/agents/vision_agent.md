---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, operator, developer, maintainer]
scope: [agents, vision, perception, verification]
summary: Current contract for freshness-bounded visual observations, specimen pose, event signals, evidence, and verified rollout stopping.
source_of_truth:
  - agents/vision_agent.py
  - graphs/modules/vision/module.yaml
  - device_bridges/utm_runtime_bridge.py
  - device_bridges/lerobot_bridge.py
  - app/main.py
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/specimen_agent.md
  - docs/agents/manipulation_agent.md
  - docs/agents/equipment_agent.md
  - docs/agents/vision_pickup_observation_runtime_guideline.txt
supersedes: []
---

# Vision Agent Reference

## Summary

`VisionAgent` observes laboratory state and emits freshness-bounded evidence and
signals. It resolves observation tasks/zones, captures scenes, estimates state,
detects temporal events, arbitrates signals, and packages `vision_report.v1`
and `vision_signal.v1`. It may stop an active robot rollout after verified UTM
placement; it cannot start robot motion or command printer, UTM, or PyAutoGUI
actions.

## Scope

Included are specimen pose, pickup/transfer readiness, active robot-camera
ejection checks, UTM placement verification, capture/runtime connections, and
evidence freshness. General computer-vision accuracy is not established.

## Source of Truth

Vision agent/module files, UTM and LeRobot bridge implementations, specimen-pose
tracker routes, and current camera/UTM Guides.

## Actual Role

| Does | Does not |
|---|---|
| Capture and interpret bounded observation tasks | Plan the experiment or choose robot policy |
| Emit pose, readiness, event, and freshness state | Convert stale signals into current truth |
| Confirm autoejection/placement where configured | Start printer, robot, UTM, or desktop action |
| Request/perform verified rollout stop | Treat an image alone as scientific measurement |
| Package visual evidence and uncertainty | Override Guardian or equipment proof contracts |

## Closed-Loop Position and Handoffs

![Vision closed-loop position and handoffs](assets/figures/vision_01_closed_loop_handoffs.svg)

**Figure Vision-1.** Specimen, manipulation, equipment, and camera context
becomes a freshness-bounded signal for downstream consumers; stale, conflicting,
or low-quality observations are rejected, while only a matching verified task
can stop an active rollout. This is an `inspection`-backed projection of
baseline `0b7627b`, not perception-quality or live-safety evidence.

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Specimen | specimen/fabrication/ejection context | observation target | specimen identity |
| In | Manipulation | rollout/session/post-place state | verify transfer | camera/session freshness |
| In | Camera/UTM runtime | frames/pose/runtime graph | scene evidence | availability/quality |
| Out | Manipulation | pickup/transfer readiness | enable bounded policy | unexpired signal |
| Out | Equipment | placement/fixture evidence | enable protocol | verified UTM state |
| Out | Specimen | autoejection confirmation | complete fabrication handoff | active-camera evidence |
| Out | Guardian/Knowledge | reports/decisions/evidence refs | safety/provenance | schema/timestamps |

## Inputs and Outputs

Input is `OrchestratorState` with observation task, specimen result, latest
camera/zone state, manipulation session, and mode. Preserved fields include
`observation.pose_estimate`, `pickup_target`, and `transfer_readiness`.
Outputs include `vision_report.v1`, `vision_signal.v1`, decisions, metrics,
evidence refs, `active_cam_ejection_check.v1`,
`spc_autoejection_confirmation.v1`, and where applicable
`vision_manipulation_completion.v1`. Consumers reject `expires_at` in the past.

## Internal Execution

| Step ID | Work | Boundary/output |
|---|---|---|
| `01_observation_task_resolve` | select bounded task | unsupported task blocks |
| `02_zone_registry_load` | load calibrated zones | missing/stale zone degrades/blocks |
| `03_capture_scene` | acquire frame | capture metadata/evidence |
| `03_active_robot_cam_ejection_check` | active-camera tool check | ejection confirmation schemas |
| `04_perception_backend` | select perception/simulator degrade | environment labeled |
| `05_estimate_scene_state` | pose/presence/readiness | estimate + uncertainty |
| `06_detect_temporal_events` | change/event detection | timestamped event |
| `07_arbitrate_agent_signals` | resolve conflicts/freshness | accepted/blocked signal |
| `08_package_visual_evidence` | attach frames/metadata | evidence refs |
| `09_handoff_signal_bus` | emit `vision_signal.v1` | expiry enforced downstream |
| `10_stop_verified_rollout` | stop after verified UTM placement | completion record or stop error |

![Vision internal execution and effect boundary](assets/figures/vision_02_execution_effect_boundary.svg)

**Figure Vision-2.** Eleven manifest entries—including both `03_*` entries—
separate task/zone resolution, capture, perception, temporal events,
arbitration, evidence, signal handoff, and verified rollout stop. This
`inspection` figure groups internal contract steps and grants no robot,
printer, UTM, or desktop start authority.

### Execution trace details

| Phase | Required identity/state | Decision/transformation | Evidence/output | Reject or recovery condition |
|---|---|---|---|---|
| Resolve | task, specimen, zone and calibration IDs | choose bounded observation contract | selected task/zone metadata | unsupported task or stale zone blocks/degrades |
| Capture | camera source and current timestamp | acquire frame and active-camera check | raw frame, source, timestamp | capture failure does not invent pose |
| Perception | labeled environment/backend | estimate pose, presence, readiness, uncertainty | estimate and quality fields | unavailable backend remains degraded |
| Temporal events | prior compatible observation | detect change/ejection/placement event | timestamped event | mismatched identity is not compared |
| Arbitration | confidence, expiry, conflicts, task policy | accept, degrade, or reject signal | `vision_report.v1` and `vision_signal.v1` | expired/conflicting signal blocks downstream use |
| Evidence packaging | accepted frame and metadata | bind raw/annotated artifact to run/session/specimen | evidence references | stream display alone is not durable evidence |
| Verified stop | matching rollout session and UTM placement | request stop and observe result | stop result/completion record | failed or unknown stop stays error/review |

## API Surface

| Class | Method | Path/family | Service | Effect | Notes |
|---|---|---|---|---|---|
| owned | GET | `/api/vision/specimen-pose/status` | pose tracker | read_only | current tracking state |
| owned | POST | `/api/vision/specimen-pose/snapshot` | pose tracker | local_state | captures bounded snapshot |
| owned | POST | `/api/vision/specimen-pose/release` | pose tracker | local_state | releases current tracking lock/state |
| connected | GET | `/api/lerobot/active-robot-cam/specimen-pose` | LeRobot camera | read_only | active robot-camera pose |
| connected | POST | `/api/lerobot/camera/test` | LeRobot bridge | read_only/local_state | camera probe |
| connected | GET/POST | `/api/equipment/utm-runtime/status`, `/start`, `/stop`, `/probe`, `/graph`, `/frame`, `/frame-stream.mjpeg` | UTM runtime | read_only/local_state/external_service | runtime and evidence capture |
| operator | GET/POST | `/api/equipment/utm-runtime/camera-*` | UTM camera service | read_only/local_state | device selection/probe/calibration |

## Tools and Connections

| Tool/service | Boundary | Effect | Evidence |
|---|---|---|---|
| `camera.capture` | selected camera bridge | read_only | frame/meta |
| `lerobot.camera.test` | LeRobot bridge | read_only | probe result |
| `lerobot.active_robot_cam.capture` | robot camera | read_only | ejection frame/confirmation |
| `lerobot.rollout.status` | robot session | read_only | rollout state |
| `lerobot.rollout.stop` | robot process | physical_possible | stop result/session |
| `vision.utm_runtime.start` | UTM ROS/runtime process | external_service | graph/health |
| `vision.utm_specimen_presence.capture` | UTM camera | read_only | annotated/raw frame |
| LLM `vision_observation` | selected model | model | bounded observation rationale |

![Vision API and connection architecture](assets/figures/vision_03_api_connection_architecture.svg)

**Figure Vision-3.** Specimen-pose, LeRobot camera, and UTM runtime/camera
surfaces feed pose tracking and signal arbitration; only a fresh task- and
session-matched branch reaches the rollout-stop service. This `inspection`
figure distinguishes observation from process stop and is not live validation.

### Connection lifecycle

| Connection | Resolve/preflight | Invoke/observe | Persist/recover |
|---|---|---|---|
| Pose tracker | specimen and tracker identity | status, bounded snapshot, release | retain snapshot metadata; release does not erase prior evidence |
| LeRobot camera | active robot/session and camera probe | capture active pose/ejection evidence | reject session mismatch or stale camera result |
| UTM runtime | runtime status, graph and camera mapping | start/probe/frame/stream as configured | capture referenced frame; unavailable graph remains explicit |
| UTM calibration | device list and current configuration | probe, apply, calibrate with status | bind calibration identity; do not reuse stale zones silently |
| Rollout stop | matching session plus verified placement | stop request followed by status/result | unknown result requires operator/Guardian inspection |

The workspace or model can request observation, but neither grants an
unregistered camera source nor a start path to robot, printer, UTM, or
PyAutoGUI execution.

## State, Events, Artifacts, and Storage

Vision stores reports/signals in run metadata and emits node/tool/evidence
events. Frame paths, timestamps, camera/zone/calibration identifiers, confidence,
expiry, run/session/specimen identity, and annotated/raw artifacts support the
handoff. Stream frames are external observations, not durable evidence until
captured and referenced.

## Modes and Fallbacks

Test may use virtual frames/signals; simulation degrade is labeled. Replay uses
recorded images/events. Browser displays and requests observations but does not
make them Live evidence. Live depends on current camera/runtime mapping and
calibration. A fallback source creates a different evidence environment.

## Safety, Approval, and Effect Boundary

Observation is read-only. The exceptional effect is stopping a verified active
rollout; it requires matching session and UTM placement evidence. Vision never
starts motion. Stale signals block downstream physical handoff. Camera
availability is not proof of safe equipment state.

## Errors and Recovery

Capture failure or missing calibration triggers retry/degrade/review without
inventing pose. Conflicting or expired signals are rejected. Unknown robot
state requires rollout status and operator/Guardian review. Failed stop remains
an explicit error; do not claim the robot stopped from a request alone.

## Operator and GUI Surfaces

Vision/UTM workspace exposes runtime graph, frame, stream, device mapping,
probe, apply, and calibration. LeRobot workspace exposes camera tests and active
pose. Live GUI displays report/signal/evidence and freshness state.

## Current Verification

Verified against all 11 manifest entries (including both `03_*` IDs), seven
tools, five direct Vision/LeRobot-camera routes, connected UTM runtime/camera
families, and bridge implementations at baseline `0b7627b`.

## Limitations and Known Gaps

No paper-scoped benchmark establishes detection accuracy, calibration drift,
lighting robustness, latency, or safety effectiveness. Camera/provider support
is environment-dependent.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Specimen](specimen_agent.md)
- [Manipulation](manipulation_agent.md)
- [Equipment](equipment_agent.md)
- [Legacy Vision Guideline](vision_pickup_observation_runtime_guideline.txt)
- [Vision Camera Bridge Guide](../tutorials/device_workspace_vision_camera_bridge_usage.ko.md)
