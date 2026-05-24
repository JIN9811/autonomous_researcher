# LeRobot / ROBOTIS Manipulation Runtime Guideline

Status: implementation guideline for Autonomous Researcher
Last reviewed: 2026-05-06
Scope: ROBOTIS OMX-AI + Hugging Face LeRobot integration for GUI, MCP tools, Manipulation Agent, test mode, live mode, replay, and fault injection.

## 1. Purpose

This document converts the LeRobot/ROBOTIS research prompt into an implementation guideline that matches the current `autonomous_researcher` runtime.

The goal is not to replace the existing robot path immediately. The goal is to add a LeRobot-capable bridge and tool group that can be selected by the Manipulation Agent when the workflow requires teleoperation, dataset recording, policy training, rollout, or SARM-assisted manipulation.

Primary live hardware target:

- ROBOTIS OMX-AI as the first live robot profile.

Required future compatibility:

- SO-101/SO101 must remain supportable by configuration and adapter/profile changes, not by rewriting the GUI, run loop, dataset schema, or Manipulation Agent.

## 2. Current Project Contracts To Preserve

The integration must preserve these contracts from the current project.

Runtime topology:

```text
FastAPI Controller
  -> RunLoop
    -> Stage Agent
      -> MCP Tool
        -> State Update
          -> Event Stream
            -> Web GUI
```

Stage order:

```text
design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> guardian
```

Guardian routing:

- `guardian=continue` routes back to `design`.
- `guardian=stop` routes to `complete`.
- `guardian=error` routes to `error`.

Agent contract:

```python
async run(state: OrchestratorState, ctx: AgentContext) -> AgentResult
```

`AgentResult` fields:

- `success: bool`
- `summary: str`
- `data: dict[str, Any]`
- `next_hint: str | None`

Runtime-required `AgentResult.data` keys:

| Stage | Required key |
|---|---|
| `design` | `experiment_spec` |
| `vision` | `observation` |
| `analysis` | `analysis` |
| `guardian` | `guardian` |

Current tool names must remain stable:

- `printer.prepare`
- `camera.capture`
- `robot.pick_place`
- `utm.run_protocol`
- `equipment.pyautogui.health`
- `equipment.pyautogui.list_programs`
- `equipment.pyautogui.run`
- `equipment.pyautogui.connection_status`
- `equipment.pyautogui.save_connection`
- `device.health`

Important rule:

- Do not rename or repurpose existing tools unless all agents and tests are updated in the same change set.
- Add `lerobot.*` tools beside existing tools.
- Keep `robot.pick_place` as the deterministic baseline and compatibility path.

## 3. Agent Ownership

### Vision Agent

Vision Agent owns camera capture and observation creation.

It should produce a typed observation object that Manipulation Agent can consume.

Required observation shape:

```json
{
  "observation_id": "obs-run-001",
  "timestamp": "2026-05-04T00:00:00Z",
  "camera_key": "top_camera",
  "frame_id": "frame-001",
  "image_uri": "runs/.../frame.png",
  "pose_estimate": {
    "x_mm": 0.0,
    "y_mm": 0.0,
    "z_mm": 0.0,
    "roll_deg": 0.0,
    "pitch_deg": 0.0,
    "yaw_deg": 0.0,
    "confidence": 0.0
  },
  "anomaly": {
    "detected": false,
    "type": null,
    "confidence": 0.0
  },
  "source": "live_camera"
}
```

Allowed `source` values:

- `live_camera`
- `lerobot_dataset`
- `replay`
- `simulator`

Manipulation Agent must not bypass Vision Agent to directly own the camera path if the workflow already has a Vision Agent observation.

### Manipulation Agent

Manipulation Agent owns:

- pick/place/alignment/transfer execution decisions
- selection of manipulation strategy
- robot policy adapter invocation
- SARM scoring and recovery hint generation
- robot-related protocol notes for GUI/logging

Manipulation Agent does not become a LeRobot-specific agent. LeRobot is one strategy/tool backend inside Manipulation Agent.

Manipulation Agent output keys must remain stable:

```json
{
  "manipulation": {},
  "sarm": {},
  "protocol_note": ""
}
```

Recommended extended manipulation payload:

```json
{
  "tool": "lerobot.rollout.start",
  "strategy": "lerobot_policy",
  "profile_id": "robotis_omx_ai",
  "session_id": "lr-session-001",
  "policy_session_id": "policy-001",
  "action_summary": "policy rollout started",
  "start_signal": "START_ROLLOUT",
  "stop_signal": null,
  "success": true,
  "failure_reason": null,
  "step_trace": []
}
```

Recommended extended SARM payload:

```json
{
  "progress_score": 0.0,
  "stage_index": 0,
  "stage_name": "pre_grasp",
  "stage_confidence": 0.0,
  "progress_delta": 0.0,
  "failure_precursor_score": 0.0,
  "recovery_hint": "none",
  "reward_model_path": "",
  "source": "deterministic_test_scorer"
}
```

### Equipment Agent

Equipment Agent remains responsible for UTM and Windows PyAutoGUI bridge workflows.

Do not move LeRobot teleoperation, recording, training, or rollout control into Equipment Agent. These belong to the Manipulation Agent / robot bridge path.

### Guardian Agent

Guardian Agent remains the policy gate.

Guardian may consume:

- `latest_observations`
- `latest_analysis`
- `manipulation`
- `sarm`
- device health
- fault-injection status
- retry counters

Guardian must not run LeRobot or robot commands directly.

## 4. Required Robot Profile Abstraction

Add a robot profile configuration layer before any real command construction.

Recommended config file:

- `configs/lerobot.yaml`

Alternative if the config grows:

- `configs/robot_profiles.yaml`

Required profile fields:

```yaml
profiles:
  robotis_omx_ai:
    profile_id: robotis_omx_ai
    display_name: ROBOTIS OMX-AI
    robot_family: robotis_omx
    robot_type: omx_follower
    teleop_type: omx_leader
    robot_port: ""
    teleop_port: ""
    robot_id: omx_follower_arm
    teleop_id: omx_leader_arm
    calibration_dir: ""
    camera_map:
      top: top_camera
      wrist: wrist_camera
    fps: 30
    observation_schema: lerobot_omx_v1
    action_schema: lerobot_omx_v1
    safety_limits:
      live_enabled: true
      require_operator_confirm: true
      allow_policy_rollout: true
      allow_recording: true
      allow_training: true
    command_templates:
      find_ports: ["lerobot-find-port"]
      teleoperate: ["python", "-m", "lerobot.teleoperate"]
      record: ["lerobot-record"]
      train: ["lerobot-train"]
      rollout: ["lerobot-rollout"]
    supported_workflows:
      - find_ports
      - teleoperate
      - record
      - train
      - rollout
    test_fixture: fake_omx_ai

  so101:
    profile_id: so101
    display_name: SO-101
    robot_family: so101
    robot_type: so101_follower
    teleop_type: so101_leader
    robot_port: ""
    teleop_port: ""
    robot_id: atr-so101-follower
    teleop_id: atr-so101-leader
    calibration_dir: memory/lerobot/calibration
    camera_map:
      top: top_camera
      wrist: wrist_camera
    fps: 30
    observation_schema: lerobot_so101_v1
    action_schema: lerobot_so101_v1
    safety_limits:
      live_enabled: false
      require_operator_confirm: true
      allow_policy_rollout: false
      allow_recording: false
      allow_training: false
    command_templates:
      find_ports: ["lerobot-find-port"]
      teleoperate: []
      record: []
      train: []
      rollout: []
    supported_workflows:
      - find_ports
      - teleoperate
      - record
      - train
      - rollout
    test_fixture: fake_so101
```

Rules:

- Treat ROBOTIS OMX-AI as the first profile, not as a global assumption.
- SO-101 must be test-mode compatible but live-disabled until verified on real hardware.
- Do not assume policies trained on OMX-AI transfer to SO-101.
- Dataset, policy, calibration, replay, and SARM records must include `profile_id`.
- Hardware-specific joint names, camera keys, gripper assumptions, and action-space mapping belong in profile/adapter code, not global state.

## 5. Recommended Files

Core files:

- `device_bridges/lerobot_bridge.py`
- `mcp_tools/lerobot_tools.py`
- `mcp_tools/lerobot_schemas.py`
- `configs/lerobot.yaml`
- `tests/unit/test_lerobot_bridge.py`
- `tests/unit/test_lerobot_tools.py`

GUI and integration files:

- `tests/integration/test_lerobot_gui_test_mode.py`
- `tests/fault_injection/test_lerobot_signal_handling.py`
- `web/static/lerobot.js`
- `web/templates/lerobot.html`

Existing files likely to modify:

- `app/bootstrap.py`
- `app/main.py`
- `app/controller.py`
- `agents/manipulation_agent.py`
- `docs/README.md`
- `docs/runtime/agent_program_baseline.md`
- `docs/runtime/test_mode.md`

Do not create a top-level `sarm_agent.py`.

Do not create a top-level `lerobot_agent.py` unless the project later explicitly changes the stage model. For now, LeRobot is a bridge/tool/backend used by Manipulation Agent.

## 6. LeRobot Bridge Contract

Implement `LeRobotBridge` as a hardware bridge with deterministic test behavior first.

Recommended class responsibilities:

- load profile config
- validate profile
- build command previews from list argv, not shell strings
- discover fake ports in test mode
- manage deterministic fake sessions
- support idempotent stop/cancel
- emit structured step events
- block live execution unless explicit gates are enabled
- never log secrets or Hugging Face tokens

Recommended command/session state traces:

Find ports:

```text
PRECHECK -> DISCOVERING -> DONE
```

Teleoperation:

```text
PRECHECK -> CONNECTING -> TELEOP_ACTIVE -> STOPPING -> STOPPED
```

Recording:

```text
READY -> WARMUP -> RECORDING -> RESET -> SAVING -> EPISODE_COMPLETE -> DATASET_COMPLETE
```

Training:

```text
PRECHECK -> LOAD_DATASET -> TRAINING -> CHECKPOINT -> COMPLETED
```

Rollout:

```text
PRECHECK -> LOAD_POLICY -> POLICY_ACTIVE -> STOPPING -> STOPPED
```

Failure states:

- `BLOCKED`
- `FAILED`
- `TIMEOUT`
- `SAFE_STOPPING`
- `SAFE_STOPPED`
- `ERROR`

Minimal response contract for every `lerobot.*` tool:

```json
{
  "ok": true,
  "tool": "lerobot.teleoperate.start",
  "mode": "test",
  "profile_id": "robotis_omx_ai",
  "session_id": "lr-session-001",
  "status": "TELEOP_ACTIVE",
  "command_preview": ["python", "-m", "lerobot.teleoperate", "..."],
  "events": [],
  "step_trace": [],
  "error": null
}
```

Rules:

- Always include `ok`.
- Always include `tool`.
- Always include `mode`.
- Include `profile_id` for profile-sensitive operations.
- Include `session_id` for session operations.
- Include `command_preview` for command-based workflows.
- Include `step_trace` for GUI/log replay.
- Include `failure_code` when blocked or failed.

## 7. MCP Tool Group

Add these tools in `mcp_tools/lerobot_tools.py`:

- `lerobot.profiles.list`
- `lerobot.profiles.validate`
- `lerobot.find_ports`
- `lerobot.teleoperate.start`
- `lerobot.teleoperate.stop`
- `lerobot.teleoperate.status`
- `lerobot.record.start`
- `lerobot.record.control`
- `lerobot.record.status`
- `lerobot.train.start`
- `lerobot.train.cancel`
- `lerobot.train.status`
- `lerobot.rollout.start`
- `lerobot.rollout.stop`
- `lerobot.rollout.status`
- `lerobot.dataset.inspect`
- `lerobot.policy.download`

Do not overwrite `robot.pick_place`.

`robot.pick_place` remains the simple deterministic baseline. Manipulation Agent can select between:

- `fixed_kinematic`: current `robot.pick_place` / simulator path
- `vision_pose_correction`: simulator or robot adapter using Vision Agent pose
- `lerobot_policy`: LeRobot rollout/session adapter
- `vla_policy`: future mock adapter until a real VLA path is verified

## 8. Tool Registration

Current registration happens in `app/bootstrap.py`.

Add registration after existing tool registration:

```python
tools = ToolRegistry()
register_mock_tools(tools)
register_printer_tools(tools, cfg.get("devices", {}), repo_root=resolve_path("."))
register_equipment_tools(tools, cfg.get("devices", {}), repo_root=resolve_path("."))
register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=resolve_path("."))
```

Rules:

- Registration must not require LeRobot to be installed in test mode.
- Missing live dependencies must produce a blocked live response, not import-time failure.
- Test mode must work on a clean development machine without robot hardware.

## 9. Live GUI / SSE Integration

The current controller streams selected tool progress into Live GUI conversation messages.

Current tool event handling only accepts:

- `printer.prepare`
- `equipment.pyautogui.run`

Add `lerobot.*` event support in `app/controller.py`.

Recommended role/message mapping:

| Tool prefix | Live GUI role | Event type |
|---|---|---|
| `lerobot.find_ports` | `manipulation_ai` | `planning_lerobot_step` |
| `lerobot.teleoperate.*` | `manipulation_ai` | `planning_lerobot_step` |
| `lerobot.record.*` | `manipulation_ai` | `planning_lerobot_step` |
| `lerobot.train.*` | `manipulation_ai` | `planning_lerobot_step` |
| `lerobot.rollout.*` | `manipulation_ai` | `planning_lerobot_step` |

Message style:

```text
Manipulation Agent / LeRobot 단계 진행: PRECHECK -> ok
```

Rules:

- Tool-level events are UI/logging signals only.
- Tool-level events must not alter hardware gates.
- Failed or blocked LeRobot events must be visible in Live GUI and structured logs.

## 10. GUI Surfaces

The `atr` main GUI is the top-level control hub. Add a visible LeRobot / ROBOTIS launcher icon, card, or button to the main GUI, and use it to open the dedicated LeRobot GUI route.

Main GUI launcher requirements:

- It must be visible from the `atr` main GUI.
- It must open the dedicated LeRobot GUI route.
- It may show summary status such as selected profile, current session state, live gate status, and robot/device health.
- It must not start teleoperation, recording, training, rollout, or any hardware action by itself.
- It must work in test mode without LeRobot installed.
- It should follow the existing auxiliary-window pattern used by `/live` and `/equipment/windows`.

Recommended route:

- `GET /lerobot`

Recommended API routes:

- `GET /api/lerobot/config`
- `POST /api/lerobot/config`
- `GET /api/lerobot/ports`
- `POST /api/lerobot/ports/baseline`
- `POST /api/lerobot/ports/detect`
- `POST /api/lerobot/ports/save`
- `POST /api/lerobot/camera/test`
- `POST /api/lerobot/teleoperate/start`
- `POST /api/lerobot/teleoperate/stop`
- `POST /api/lerobot/record/start`
- `POST /api/lerobot/record/control`
- `POST /api/lerobot/record/status`
- `POST /api/lerobot/train/start`
- `POST /api/lerobot/train/cancel`
- `POST /api/lerobot/train/status`
- `POST /api/lerobot/rollout/start`
- `POST /api/lerobot/rollout/stop`
- `POST /api/lerobot/rollout/status`
- `POST /api/lerobot/dataset/inspect`
- `POST /api/lerobot/visualize/dataset`
- `GET /api/lerobot/policies`
- `POST /api/lerobot/files/browse`
- `GET /api/lerobot/visualization/file`
- `GET /api/lerobot/sessions`

Recommended GUI sections:

- Hardware Profile Selector
- Hardware Setup / Ports: follower and leader MotorBus ports are identified separately using a baseline/device-change/detect workflow; camera port/index setup is key-based and multi-camera. Default camera keys are `top` and `wrist`, and the GUI must allow adding more camera keys with `+ Camera`.
- Teleoperation
- Recording
- Dataset / Visualization
- Training
- Inference / Rollout
- Manipulation Agent + SARM
- Logs / Replay / Fault Injection

Rules:

- Reuse `/api/events/stream`.
- Reuse structured log viewer concepts.
- Do not create a parallel event system unless the current SSE path cannot support a required event and the reason is documented.
- GUI test mode must not touch `/dev`, ROS 2, robot ports, cameras, GPU training, or Hub upload.
- The dedicated GUI must be refreshable and must reconstruct its current visible state from backend APIs.

Teleoperation GUI requirements:

- select profile
- show robot/teleop type
- show command preview
- fake port discovery in test mode
- persist follower and leader ports per profile after explicit baseline/detect or manual save
- for the current ROBOTIS OMX-AI installation, treat leader as Dynamixel motor IDs `1-6` and follower as IDs `11-16`; if a saved port mapping contradicts that, Teleop must fail visibly rather than silently swapping roles
- persist cameras per profile under `devices.cameras.<camera_key>` so `top`, `wrist`, and additional cameras can be configured independently
- prefer stable device identity links when persisting live devices: `/dev/serial/by-id/*` for leader/follower and `/dev/v4l/by-id/*` or `/dev/v4l/by-path/*` for cameras; retain the original dynamic value as `raw_port` and store `device_id` / `device_link` for later lookup
- resolve saved identity links to the current kernel node at execution time for all live LeRobot hardware paths: teleoperation, recording, rollout, and camera capture tests. For this ROBOTIS OMX-AI setup, that means saved follower identity resolves to `/dev/ttyACM0`, saved leader identity resolves to `/dev/ttyACM1`, and saved camera identities resolve to `/dev/video*` / integer OpenCV indices.
- allow GUI removal of non-default camera keys while protecting default `top` and `wrist` cameras
- expose capture smoke tests per camera key
- run live camera smoke tests through the LeRobot conda environment's OpenCV backend if the main application virtualenv does not include `cv2`
- show per-button-group status boxes so operators can see whether each action is running, OK, or failed without opening the raw result log
- render filtered live subprocess `log_tail` directly inside the same status box, especially under Teleoperation, so LeRobot motor-ID, calibration, camera, and process-start failures are visible at the button that caused them
- generate timestamped LeRobot live session IDs and write each subprocess log to a unique file; never rely on restart-local counters alone because reused log names can mix stale failure logs into later Stop/Status responses
- use saved follower and leader device identities when building `python -m lerobot.teleoperate`, `lerobot-record`, and policy rollout command previews, then resolve them to current ports immediately before subprocess execution
- build `--robot.cameras` from saved camera identities when camera capture is enabled, as LeRobot camera config dictionaries, not raw port strings, e.g. `{top: {type: opencv, index_or_path, width, height, fps}}`
- keep camera capture independent from LeRobot display visualization; display toggles `--display_data`, not whether saved cameras are recorded into the dataset
- run live LeRobot subprocesses with `conda run --no-capture-output -n lerobot ...` and unbuffered Python output so command logs stream into the GUI while the process is active
- start fake teleoperation in test mode
- in live mode, surface immediate LeRobot startup failures such as missing interactive calibration as structured failures such as `LEROBOT_CALIBRATION_REQUIRED`
- stop fake teleoperation idempotently
- safe-stop active session
- show synthetic camera event if camera is enabled

Recording GUI requirements:

- show task/instruction, FPS, warmup, episode duration, reset duration, and episode count fields
- pass the task/instruction field as LeRobot's required `--dataset.single_task` argument
- reuse the same follower, leader, and camera resolution path as teleoperation; current ROBOTIS OMX live recording resolves follower to `/dev/ttyACM0`, leader to `/dev/ttyACM1`, top camera to OpenCV index `2`, and wrist camera to OpenCV index `0` when the saved identities are connected
- if the selected dataset already exists and `resume` is false, live recording must not silently resume it; use a fresh suffixed dataset path and surface `existing dataset detected; recording to fresh dataset ...` in the trace so partial/corrupt prior runs do not break camera-enabled recording startup
- live `record.control` must send LeRobot's actual recording keyboard events: Right Arrow for save/advance, Left Arrow for rerecord, Esc for graceful finish. Do not mark episodes complete in GUI without sending the corresponding control event.
- live `record.control` must prefer the active recording session over newer stopped/stale record sessions, because repeated start/stop attempts can leave stopped sessions later in the GUI list than the currently running process.
- live `record.control` must block extra Right/Left Arrow events while LeRobot is saving parquet/video after reset. The next permitted control point is after LeRobot logs the next `Recording episode` or `Reset the environment`. This prevents the next episode from exiting before any frames are added.
- reserve force-stop for process recovery; it must terminate tracked and stale LeRobot subprocess groups tied to this checkout so child `lerobot-record` / `lerobot.teleoperate` processes do not keep cameras or serial ports open.
- start fake recording in test mode
- support Stop, Retry, Next, and Finish controls
- show fake dataset path and metadata
- represent rosbag option as dry-run metadata only
- block Hub upload unless explicitly configured

Inference / Rollout GUI requirements:

- show policy path or repo selector
- validate missing policy path before action
- show command preview
- fake policy loading in test mode
- fake policy active state in test mode
- keep training dataset, policy repo, and rollout/evaluation dataset names separate
- apply `eval_` only to rollout/evaluation output datasets; the bridge must normalize `jin/foo_rollout` to `jin/eval_foo_rollout`
- leave rollout duration blank by default so policy rollout runs until `Stop Rollout`; internally this maps to one long LeRobot episode
- enable ACT Temporal Ensemble by default and add `--policy.temporal_ensemble_coeff=0.01 --policy.n_action_steps=1` unless the operator disables it
- enable Safe Action Clamp by default and add `--robot.max_relative_target=5` unless the operator disables it
- stop rollout idempotently
- block rollout while teleoperation is active unless a verified workflow explicitly permits it

Detailed naming and manual-stop behavior is defined in `docs/runtime/lerobot_dataset_policy_naming.md`.

## 11. Signal Model

Add or extend a typed signal model before live subprocess execution.

Recommended signals:

- `START_TELEOP`
- `STOP_TELEOP`
- `START_RECORDING`
- `STOP_RECORDING`
- `RETRY_EPISODE`
- `NEXT_EPISODE`
- `FINISH_RECORDING`
- `START_TRAINING`
- `CANCEL_TRAINING`
- `START_ROLLOUT`
- `STOP_ROLLOUT`
- `PAUSE_POLICY`
- `RESUME_POLICY`
- `HUMAN_INTERVENTION_START`
- `HUMAN_INTERVENTION_STOP`
- `SAFE_STOP`
- `EMERGENCY_STOP`

Required behavior:

- Every start command creates a `session_id`.
- Every start command emits `session_started`.
- Every stop command is idempotent.
- Double stop must not crash.
- Safe-stop attempts graceful shutdown first, then process-group termination after timeout.
- Emergency-stop prioritizes halting motion over preserving dataset/checkpoint artifacts.
- GUI must disable mutually exclusive controls while a session is active.
- Rollout must not start while teleoperation is active unless the verified workflow explicitly allows it.

## 12. Test Mode Requirements

Absolute rule:

- Test mode must never move the real robot.
- Test mode must never upload datasets or policies.
- Test mode must never start physical write actions.
- Test mode must never access real `/dev` ports unless a specifically gated live diagnostic route is selected.

Required fake profiles:

- `fake_omx_ai`
- `fake_so101`

Test-mode fake ports:

```json
{
  "ok": true,
  "tool": "lerobot.find_ports",
  "mode": "test",
  "profile_id": "robotis_omx_ai",
  "ports": [
    {"role": "robot", "port": "/dev/ttyUSB_FAKE_FOLLOWER", "detected": true},
    {"role": "teleop", "port": "/dev/ttyUSB_FAKE_LEADER", "detected": true}
  ],
  "command_preview": ["lerobot-find-port"],
  "step_trace": []
}
```

Test-mode fake session requirements:

- deterministic `session_id`
- deterministic state transitions
- deterministic `step_trace`
- deterministic `command_preview`
- no real subprocess launch
- no shell execution
- no physical device access

## 13. Live Mode Gates

Live mode must be disabled by default.

Live execution requires all of these:

- selected profile exists
- `safety_limits.live_enabled: true`
- operator explicitly chooses live mode
- ports are configured or discovered
- hardware profile passes validation
- conflicting sessions are inactive
- command preview is shown before execution
- live dependency preflight passes
- secrets are not logged

Profiles that disable a live gate must return structured blockers.

Example:

```json
{
  "ok": false,
  "tool": "lerobot.rollout.start",
  "mode": "live",
  "profile_id": "so101",
  "status": "blocked",
  "failure_code": "LEROBOT_LIVE_GATE_DISABLED",
  "message": "Live robot rollout is disabled in the selected robot profile.",
  "step_trace": [
    {
      "step": "PRECHECK",
      "status": "blocked",
      "detail": "safety_limits.allow_policy_rollout=false"
    }
  ]
}
```

## 14. SARM Runtime Plan

SARM remains inside Manipulation Agent.

Minimum required runtime behavior:

- deterministic test-mode scorer
- no live SARM model required
- no SARM training required
- output visible in GUI/logs

Optional extension behavior:

- optional configured SARM reward model
- optional dataset subtask annotations
- optional `sarm_progress.parquet`
- optional RA-BC weighting if supported by the selected policy

Runtime recovery examples:

- no progress for N frames
- negative progress delta
- low stage confidence after grasp
- anomaly from Vision Agent
- unsafe workspace estimate
- policy timeout
- repeated stop/start failures

SARM decisions are advisory unless Guardian policy escalates them.

## 15. Dataset / Training / Rollout Rules

Dataset metadata must include:

- `robot_profile_id`
- `robot_type`
- `teleop_type`
- `calibration_id`
- `action_space_version`
- `observation_space_version`
- `run_id`
- `experiment_id`
- `task_instruction`
- `fps`
- camera keys

Training rules:

- test mode simulates logs, loss values, checkpoints, and completion
- live training must be separately gated and currently requires `live_enabled=true`, `allow_training=true`, and operator `confirm_live_execute=true`
- ACT can be a quick baseline only if dependencies are verified
- SmolVLA/VLA options must be config-driven and dependency-verified
- no Hub upload unless explicitly configured
- GUI training controls must expose practical LeRobot CLI parameters instead of only policy type/job name:
  - dataset repo/root, policy type/repo, output dir, job name, device
  - batch size, steps, num workers
  - eval/log/save frequency, save checkpoint, resume, seed
  - optimizer, scheduler, AMP, policy window/chunk/action fields
  - WandB enable/project/mode
  - advanced one-safe-argument-per-line `--key=value` passthrough
- Training status must show current step, total steps, percent, elapsed time, steps/sec, last parsed loss, and ETA when logs expose progress.

Rollout rules:

- test mode simulates policy loading and active control
- live rollout requires no active teleoperation conflict
- missing policy path must block before any physical action
- DAgger-like mode requires teleop config and explicit operator gate

## 16. Fault Injection

Fault-injection support must include:

- port missing
- duplicate/ambiguous ports
- camera missing
- camera disconnect
- malformed LeRobot output
- policy path missing
- policy load failure
- process timeout
- stop during recording
- stop during rollout
- safe-stop timeout
- SARM timeout
- model timeout

Every injected fault must produce:

- visible GUI error
- structured event
- structured log entry
- failure memory candidate, when applicable
- deterministic test assertion

## 17. Replay

All LeRobot session events should be replayable from structured logs.

Replay requirements:

- `run_id`
- `experiment_id`
- `session_id`
- `profile_id`
- `tool`
- `step`
- `status`
- `timestamp`
- `payload summary`
- `result summary`
- `failure_code`, when applicable

Replay must reconstruct:

- selected robot profile
- session state
- last command preview
- latest step trace
- visible GUI status

## 18. Implementation Checklist

This guideline is not divided into mandatory phases. Use the checklist below to implement the full LeRobot/ROBOTIS integration in a way that preserves current project contracts.

Read before coding:

- this guideline
- `docs/project/Project_guide.txt`
- `docs/runtime/agent_program_baseline.md`
- `docs/runtime/architecture.md`
- `docs/runtime/test_mode.md`
- current repository files under `app`, `agents`, `orchestrator`, `mcp_tools`, `device_bridges`, `configs`, and `tests`
- current official LeRobot and ROBOTIS sources for any external fact used in code

Core bridge/tool implementation checklist:

- typed schemas
- `LeRobotBridge`
- profile loading and validation
- fake OMX-AI profile
- fake SO-101 profile
- fake port discovery
- fake teleoperation session
- fake recording session
- fake training session
- fake rollout session
- `mcp_tools/lerobot_tools.py`
- `app/bootstrap.py` tool registration
- unit tests

GUI/API implementation checklist:

- main GUI LeRobot launcher icon/card
- `/lerobot` GUI surface
- `/api/lerobot/*` routes
- profile selection
- port discovery panel
- teleoperation controls
- recording controls
- training controls
- training parameter controls and progress/ETA display
- rollout controls
- dataset inspection panel
- Manipulation Agent + SARM status panel
- SSE events
- Live GUI event cards
- GUI/API tests

Manipulation Agent integration checklist:

- strategy selection
- typed VisionObservation consumption
- `fixed_kinematic`
- `vision_pose_correction`
- `lerobot_policy`
- deterministic SARM scorer
- optional live SARM adapter
- Guardian-visible recovery hints

Live command checklist:

- live command builder
- live dependency preflight
- operator confirmation gates
- ROBOTIS OMX-AI live gates
- command preview before execution
- process group lifecycle
- idempotent stop
- safe-stop
- emergency-stop
- live boundary fault-injection tests
- SO-101 live mode remains disabled until real hardware verification exists

Dataset, training, rollout, replay, and docs checklist:

- dataset inspection fixtures
- dataset metadata with `profile_id`
- training metadata
- rollout metadata
- replay support
- metrics events if metrics subsystem exists
- documentation updates

Target tests:

```bash
pytest tests/unit/test_lerobot_bridge.py -q
pytest tests/unit/test_lerobot_tools.py -q
```

## 19. Acceptance Criteria

Bridge/tool acceptance:

- `lerobot.*` tools registered.
- Fake OMX-AI and fake SO-101 profiles work in test mode.
- Commands are list argv previews, not shell strings.
- Stop/cancel is idempotent.
- No live subprocess starts.
- No LeRobot installation required for test-mode unit tests.
- No `/dev` access in test mode.
- No secrets are logged.
- Unit tests pass.

GUI/API acceptance:

- Main GUI has a LeRobot launcher icon/card.
- Launcher opens the dedicated LeRobot GUI route.
- GUI can select fake profile.
- GUI can discover fake ports.
- GUI can start/stop fake teleoperation.
- GUI can simulate recording controls.
- GUI can simulate training/rollout progress.
- GUI can browse local dataset/policy/output roots.
- Browse buttons must open a native OS picker for actual workstation folders/files; the in-page browser is fallback only when the native picker is unavailable. Rollout policy browse starts from `outputs/train`, shows folders plus recognized policy output files (`*.safetensors`, `*.ckpt`, `*.pt`, `*.pth`, `*.bin`), and resolves selected LeRobot model files to the parent `pretrained_model` checkpoint directory.
- GUI can select configured HF policy repo IDs or discovered local checkpoints.
- GUI can visualize local dataset metadata and local video/image media without requiring Hugging Face dataset upload.
- SSE shows session progress.
- Structured logs contain run/session/profile metadata.

Live gate acceptance:

- Live ROBOTIS OMX-AI path remains blocked by default.
- Operator can see exact command preview.
- Missing port/policy/camera blocks before physical action.
- Safe-stop and emergency-stop behavior are tested.
- SO-101 live mode remains disabled unless verified on hardware.

Manipulation/SARM acceptance:

- Manipulation Agent can use `robot.pick_place` baseline.
- Manipulation Agent can use `lerobot_policy` in test mode.
- VisionObservation is consumed without raw camera ownership transfer.
- SARM remains inside Manipulation Agent.
- Guardian can see SARM recovery hints.

## 20. Documentation Updates Required With Implementation

When code is added, update:

- `docs/runtime/agent_program_baseline.md`
- `docs/runtime/test_mode.md`
- `docs/runtime/architecture.md`
- `docs/gui/gui.md`
- `docs/README.md`
- this file

If CLI commands are added, update:

- `install/README.md`

Recommended CLI commands if CLI support is added:

- `atr lerobot status`
- `atr lerobot profiles`
- `atr lerobot ports`
- `atr lerobot teleop start`
- `atr lerobot teleop stop`
- `atr lerobot record start`
- `atr lerobot record control`
- `atr lerobot rollout start`
- `atr lerobot rollout stop`

## 21. Verified External Sources

External facts must be rechecked before live implementation because LeRobot CLI and docs can change.

Sources checked for this guideline:

- Hugging Face LeRobot OMX documentation: https://huggingface.co/docs/lerobot/en/omx
- Hugging Face LeRobot SO-101 documentation: https://huggingface.co/docs/lerobot/main/en/so101
- Hugging Face LeRobot inference / rollout documentation: https://huggingface.co/docs/lerobot/main/inference
- Hugging Face LeRobot SARM documentation: https://huggingface.co/docs/lerobot/sarm
- ROBOTIS OMX-AI hardware documentation: https://ai.robotis.com/omx/hardware_omx.html
- ROBOTIS OMX-AI software documentation: https://ai.robotis.com/omx/software_omx.html
- ROBOTIS OMX-AI recording workflow documentation: https://ai.robotis.com/omx/dataset_preparation_recording_omx.html

Verified assumptions:

- LeRobot supports OMX with `omx_follower` / `omx_leader` profile naming in official docs.
- LeRobot supports SO-101 with `so101_follower` / `so101_leader` profile naming in official docs.
- LeRobot provides teleoperation, recording, training, and rollout/inference workflows.
- SARM is Stage-Aware Reward Modeling and belongs inside Manipulation Agent for this project.
- ROBOTIS OMX-AI is a leader/follower manipulation kit suitable as the first robot profile.

Unverified until local installation/hardware test:

- Exact installed LeRobot CLI entrypoints and flags in the target environment.
- Exact ROBOTIS Physical AI Tools local command behavior.
- Real USB port names.
- Real camera topic/device names.
- Real ROS 2 node names and process lifecycle on this machine.
- Safe live payload limits for the actual hardware setup.

## 22. Do Not Do

- Do not create a top-level SARM agent.
- Do not create a top-level LeRobot stage.
- Do not replace the existing stage enum.
- Do not remove `robot.pick_place`.
- Do not hard-code ROBOTIS constants into global state.
- Do not enable SO-101 live mode without real hardware verification.
- Do not launch live LeRobot commands in test mode.
- Do not build shell command strings with unsanitized user input.
- Do not log tokens or secrets.
- Do not allow policy rollout while teleoperation is active unless a verified workflow explicitly permits it.
- Do not treat SARM recovery hints as final decisions unless Guardian policy escalates them.
