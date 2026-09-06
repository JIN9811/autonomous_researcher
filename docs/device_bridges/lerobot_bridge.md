---
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - researcher
  - operator
  - developer
  - integrator
scope:
  - lerobot
  - robot_runtime
  - isaac_sidecars
summary: Current LeRobot bridge contract for profiles, devices, cameras, teleoperation, recording, training, rollout, visualization, and Isaac sidecars.
source_of_truth:
  - device_bridges/lerobot_bridge.py
  - device_bridges/isaac_lab_synthetic.py
  - device_bridges/isaac_lab_hdf5.py
  - device_bridges/isaac_lab_joint_replay_mimic.py
  - mcp_tools/lerobot_tools.py
  - configs/lerobot.yaml
  - app/main.py
  - scripts/lerobot_managed_replay.py
  - utils/utm_clear_cycle.py
last_verified: 2026-09-06
verified_against: working-tree
related_docs:
  - docs/device_bridges/README.md
  - docs/agents/manipulation_agent.md
  - docs/agents/vision_agent.md
  - docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md
  - docs/hardware/isaac_sim_robotis_omx_mirror_mode.md
supersedes: []
---

# LeRobot Bridge Reference

## Summary

`LeRobotBridge` is the robot/process boundary for profile and port management,
camera capture, teleoperation, recording, training, policy rollout, dataset
inspection, managed recorded-motion replay, visualization, and Isaac-based synthetic/Mimic/RL/mirror
workflows. It owns process/session evidence and stop/status operations; agents
own scientific intent and Guardian/operator policy remains authoritative.

## Scope

Included: ROBOTIS OMX-AI and SO-101 profile families, serial-port memory,
camera checks, active robot camera lease, subprocess lifecycle, policies,
datasets, local visualization/W&B, Isaac sidecars, and API/tool integration.
Excluded: model quality, robot manufacturer safety certification, and claims
that test/fake profiles validate a live robot.

## Source of Truth

The public bridge methods and `register_lerobot_tools` define executable entry
points. `configs/lerobot.yaml` defines profiles, commands, storage roots, and
safety limits. Isaac helper modules are subordinate to bridge methods rather
than independently registered top-level device bridges.

## Actual Role

The bridge validates a selected profile, resolves ports/cameras/policies,
builds bounded commands, starts or simulates processes, records session state,
and exposes stop/status and artifacts. It does not decide that a grasp is safe,
convert model advice into unapproved motion, or accept stale Vision evidence.

## System Position and Agent Handoffs

![LeRobot system position](assets/figures/lerobot_01_system_handoffs.svg)

**Figure LeRobot-1.** Manipulation initiates bounded robot work, Vision supplies
camera/verification context, and Guardian/operator gates live effects; session,
telemetry, dataset, and artifact evidence returns to the closed loop. Dashed
Isaac paths are optional sidecars. Evidence level is `inspection`.

| Producer | Input | Output/consumer |
|---|---|---|
| Manipulation Agent | task, profile, policy, fresh Vision and gate context | rollout/session/task evidence |
| Vision Agent | camera/capture request and scene identity | frame/pose metadata and stop-verification context |
| Operator | port/profile/policy/process controls | configuration, status, logs, datasets/checkpoints |
| Guardian | approval, risk, stop decision | blocked/start/stop status and incident evidence |

## Inputs, Commands, and Outputs

| Family | Inputs | Outputs |
|---|---|---|
| Profiles/ports | profile ID, device baselines, serial paths | validated profile and saved/detected mapping |
| Camera | camera name/map, FPS/depth settings, capture intent | availability, frame/artifact metadata |
| Teleop/record | profile, confirmation, repository/dataset/session fields | command/session/status/logs |
| Train/rollout | policy/checkpoint, dataset, task, runtime limits | process status, checkpoint/result, stop evidence |
| Isaac | source datasets, environment, trial/domain settings | HDF5, preview, Mimic/RL summaries, render/mirror state |

## Internal Execution

![LeRobot execution boundary](assets/figures/lerobot_02_execution_effect_boundary.svg)

**Figure LeRobot-2.** Profile/port/policy/Vision/operator gates precede process
start and serial robot motion; process registration, status, telemetry, and
artifacts define recovery. Internal helper stages are not separate graph nodes.

| Phase | Reads/decision | Writes/effect | Recovery anchor |
|---|---|---|---|
| Resolve | profile inheritance, port memory, camera map | normalized redacted config | validation blockers |
| Preflight | workflow support, live flags, operator confirm, policy/path | command preview | no process started |
| Start | subprocess/session identity | process and possible serial/camera effect | PID/session record |
| Observe | log/status/joint/camera output | progress and evidence artifacts | status/telemetry |
| Stop | matching process/session | terminate/control result | stop evidence and scene verification |
| Sidecar | dataset/HDF5/environment contract | Isaac process and derived artifacts | job summary/failure manifest |

## API Surface

### Standalone ActiveCam camera preparation

The one-shot driver, `scripts/lerobot_active_robot_cam_once.py`, uses a short
RealSense SDK bootstrap (`warmup_s=1`, in addition to the SDK's initial delay)
followed by a readiness gate before commanding the capture pose. The shared
bridge camera warmup of 20 seconds for recording and rollout is unchanged.
The SDK's existing pipeline-start retry remains in place.

Readiness requires at least eight fresh synchronous frames spanning at least
0.5 seconds, evaluated in a rolling window of up to 16 frames:

| Signal | Acceptance condition |
|---|---|
| Color | Finite three-channel image; overall mean between 2 and 253 on the 8-bit scale |
| Exposure stability | Per-channel mean range within the larger of 3 levels or 3% of its window mean |
| Depth, when enabled | Matching color dimensions; at least 5% finite positive pixels |
| Depth stability | Valid-pixel fraction range at most 5 percentage points; median range within the larger of 1 raw unit or 5% of its window mean |

Depth is read with color from the same SDK frameset. Invalid frames clear the
window. Stable frames allow early completion; a 20-second readiness deadline
raises `ACTIVE_ROBOT_CAM_CAMERA_NOT_READY` inside the existing
`ACTIVE_ROBOT_CAM_CONNECT_FAILED` response. It never authorizes capture-pose
movement on timeout. This deadline excludes SDK connection/bootstrap time.
Connection still opens the robot bus and configures hardware; this is not a
hardware-free preflight or a new emergency-stop mechanism.

The driver result includes `camera_readiness.elapsed_s` for connection plus
readiness, and per-camera `elapsed_s`, `stable_frames`, `depth_required`, and
`valid_depth_fraction`. Capture, pose validation, and return motion are unchanged.
These readiness thresholds are software-tested heuristics, not a physical
image-quality certification or a measured startup-time guarantee. The next
standalone invocation reads the updated script without a GUI server restart.

### HTTP endpoints

`/api/lerobot/*` includes config/profiles/ports, camera and specimen-pose,
teleoperate, record, train, rollout, replay, policies/download, datasets/files,
visualization and local W&B, joint telemetry, sessions, augmentation, Isaac
RGB-D, Isaac Lab validation/prepare/synthetic/Mimic/RL/e2e, and mirror
receiver/loop families. Start, status, stop, and artifact retrieval are distinct
operations. OpenAPI remains exhaustive.

### Managed UTM-clear replay

Managed replay is physical playback of a recorded robot episode when the
effective runtime mode is Live. It is not offline event replay or a new VLA
rollout. The current implementation supports local LeRobot v2 parquet data
and the OMX follower profile used by the approved `jin/utm_clear`, episode `0`.

| HTTP (POST) | Registered tool | Contract |
| --- | --- | --- |
| `/api/lerobot/replay/start` | `lerobot.replay.start` | Validate profile/live confirmation, dataset/episode and scoped session; reserve process/ports and launch |
| `/api/lerobot/replay/status` | `lerobot.replay.status` | Read process state, duration bound, logs and validated measured-return evidence |
| `/api/lerobot/replay/stop` | `lerobot.replay.stop` | Stop the matching managed process, including a concurrent pending start |

Requests carry profile, dataset repository/path, `replay_episode`, mode,
confirmation and run/loop/specimen/session identity. Responses retain session,
status, log/evidence paths and `replay_max_duration_s`; completion requires
validated evidence identity and `replay_home_verified`, not exit code alone.
The runner uses the existing saved calibration and native robot action path
without rewriting the dataset, calibration or motor limits. Return is checked
against the final recorded `observation.state`, not the commanded action.
No VLA checkpoint, grasp detector or camera lease is needed for this sweep.

Start is idempotent for an already registered child within the current bridge
process; this is not durable exactly-once execution across server restarts.
The cycle layer prevents automatic effectful rearming. A fixed pending deadline
is derived from the actual replay duration bound, with a bounded observation
budget. Global Stop, Safe Stop, E-stop and PLC stop include managed replay.
Termination first requests graceful cleanup, then escalates if necessary.
Best-effort per-motor torque disable continues after an individual failure,
but a cleanup failure remains unverified and SIGKILL cannot guarantee torque
disable. Reconcile the actual robot before any restart after an unknown effect.

The two-stage image display is described in
[Manipulation](../agents/manipulation_agent.md#post-test-utm-clearance).
An image-card selection never grants motion authority.

## Tools and Registry Integration

`register_lerobot_tools` stores resource `lerobot.bridge` and registers the
corresponding `lerobot.*` methods. Device-labeled actions include joint probes,
camera capture, teleoperation start, record/train/rollout start, mirror loop,
and visualization start. Manipulation uses the same registered bridge; API
handlers resolve the registered resource when available.

## Connections and Protocols

![LeRobot API and connections](assets/figures/lerobot_03_api_connection_architecture.svg)

**Figure LeRobot-3.** The API and Tool Registry converge on one bridge before
subprocess, serial, camera, filesystem/Hugging Face, and optional Isaac/local
service boundaries. Stop/status and evidence paths return independently; no UI
or model bypass is an execution path.

- local subprocesses run LeRobot commands, training, rollout, visualization,
  Isaac workers, and mirror receivers;
- serial device paths identify leader/follower arms;
- camera integrations expose mapped top/wrist/RealSense observations;
- filesystem roots hold datasets, policies, checkpoints, logs, HDF5, previews,
  and job summaries;
- optional Hugging Face and local W&B interactions require their configured
  credentials/services.

## Configuration and Secrets

`configs/lerobot.yaml` owns default mode/profile, profile inheritance, command
templates, safety limits, dataset/output/policy/session roots, Conda
environments, depth settings, sidecar defaults, and token path. Mutable port
and session records live under `memory/` and `runs/`. Hugging Face credentials
are referenced by environment/token path; token values MUST NOT enter docs,
logs, figures, or API responses.

## State, Events, Artifacts, and Evidence

State includes selected profile/ports, process kind/PID/status, session IDs,
commands, timestamps, log paths, and stop results. Evidence may include camera
frames, joint telemetry, episodes, datasets, checkpoints, HDF5 contracts,
success/failure manifests, preview/video files, Isaac summaries, and mirror
receiver samples. Existence is not model-quality or task-success proof.

## Runtime Modes and Fallbacks

Test mode uses fake profiles, simulated sessions, and deterministic artifacts.
Live mode requires a profile with `live_enabled` and workflow-specific
`allow_*`, resolved devices, and operator confirmation where configured.
Profile or policy substitution is explicit. Optional video backend fallback is
an implementation compatibility path, not robot fallback.

## Safety, Approval, and Effect Boundary

Configuration, inspection, dataset processing, and most Isaac work are local
or subprocess effects. Physical possibility begins when teleoperation,
recording with hardware, rollout, mirror loop, or another command opens serial
devices and controls the robot. Required gates include exact profile, supported
workflow, ports, live/allow flags, policy/checkpoint, operator confirmation,
fresh Vision where the agent contract requires it, and Guardian policy.

## Errors, Timeouts, and Recovery

Invalid profiles/ports/policies, unsupported workflows, missing executables,
busy process kinds, malformed HDF5, and failed artifact checks block or fail
with structured status. After start timeout, inspect process/session records,
joint telemetry, logs, camera/scene state, and stop status. Do not restart motion
until the old process and physical effect state are reconciled.

## Operator and GUI Surfaces

The `/lerobot` workspace exposes profiles, ports, camera, teleop/record/train/
rollout, policies, sessions, visualization, augmentation, Isaac, and mirror
operations. The live manipulation workspace can call a bounded agent run, but
the GUI is not an authority boundary and cannot waive bridge or Guardian gates.

Live joint charts replay the selected rollout's saved `motor_events.jsonl`
from its first action sample on every connection, then append all new samples.
The time origin remains the first logged action, not the time the window opens.
Closing the GUI does not stop the in-process motor logger; measured and target
values for all six joints, including the gripper, remain in the saved log.
History is streamed in bounded file chunks without discarding earlier samples;
the GUI retains the complete selected-session history. Read-only bridge safety
observers keep their separate bounded-tail behavior.

Agent-owned streams now support run/loop/agent/attempt directories with a
compatibility locator at the legacy session path. Terminal bridge observations
finalize tracking evidence without an open GUI. See
[Loop Artifact Archiving](../runtime/loop_artifact_archiving.md) for the newer
working-tree storage contract, configured-root resolution, and verification.

`motion_state.grasp_achievement` preserves the first threshold-qualified contact
success in the current rollout execution. The Live GUI's Grasp Achievement card
and saved artifacts use that result; `grasp_outcome`, `latest_grasp_outcome`,
and the complete attempt list retain the latest/raw diagnostic semantics.
The attempt success rate continues to include failed attempts, independently
of the binary achievement. Session changes and logger sequence restarts clear
the achievement; reconnecting and replaying the same log reconstructs it.
This is historical contact evidence, not proof that the specimen is still held.
Final transfer verification, measured-home/stop interlocks, and 3D motion
visualization continue to consume their existing evidence, not this latch.

## Current Verification

Inspection covered bridge/config/tool/API paths and focused tests for core
bridge behavior, GUI API contracts, camera, telemetry, profiles, rollout,
Isaac synthetic/Mimic, and mirror functions at `188a1d6`. No complete physical
robot campaign across every profile/policy was evaluated.

Managed-replay update (2026-09-06, uncommitted working tree):
`tests/unit/test_lerobot_replay.py` covers session identity, duplicate start,
stop/start races, port ownership, partial cleanup failure and measured return;
`tests/unit/test_utm_clear_cycle.py` covers downstream gates and cancellation.
These are non-actuating tests. The new managed wrapper and post-sweep Vision
confirmation have not been commissioned on hardware. Broader pre-existing
bridge failures were not hidden or treated as passing by this focused check.

Standalone readiness update (2026-09-06, working tree): 23 focused driver,
ActiveCam-loop, and artifact tests plus nine selected bridge ActiveCam tests
passed without hardware actuation. Broader checks still reported three Isaac
timeout-expectation failures (0.15 versus 0.5 seconds) and one missing-camera
teleop lease-metadata failure. Those paths were not changed by this update;
this is not a clean full-suite or physical-performance verification.

## Limitations and Known Gaps

The bridge is a large multi-responsibility implementation, and optional Isaac,
Hugging Face, W&B, camera, environment, and robot combinations vary. Graph
metadata summarizes only selected rollout/camera tools and not the complete
registered surface. Test fixtures do not establish live safety or performance.

## Related Documents

- [Manipulation Agent](../agents/manipulation_agent.md)
- [Vision Agent](../agents/vision_agent.md)
- [LeRobot Runtime Guide](../hardware/lerobot_robotis_manipulation_runtime_guideline.md)
- [Isaac OMX Mirror Guide](../hardware/isaac_sim_robotis_omx_mirror_mode.md)
- [Bridge Matrix](bridge_api_connection_matrix.md)
