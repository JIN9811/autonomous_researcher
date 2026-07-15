# Manipulation Live Pose And Policy Tracking Design

## Objective

Add two native Manipulation Agent cards to the Live GUI:

- `Live Robot Pose`: a browser-rendered OMX digital twin driven by measured follower joint state, with an optional translucent policy-target ghost during rollout.
- `Policy Tracking`: a white-background scientific line plot comparing measured follower position and policy target over elapsed time.

The implementation follows the low-latency pattern used by Hugging Face LeLab: load robot geometry once, send only compact joint-state packets, and render locally in the browser.

## Non-Negotiable Constraints

- Do not change LeRobot control timing, command generation, action clamp, rollout state machine, MotorBus ownership, or serial-port access.
- Do not open a second robot connection for visualization.
- Consume the existing `runs/lerobot_action_logs/<session_id>/motor_events.jsonl` artifact as a read-only observer.
- Keep telemetry failures isolated from robot execution.
- Bound browser history and backend reads so the Live GUI cannot cause unbounded memory growth.
- Use the existing OMX model under `sim/robotis_omx`; do not substitute an SO-101 model.
- Keep the live plot visually equivalent to a conventional Matplotlib publication figure: white background, labeled axes, explicit legend, restrained colors, and no gradients or decorative effects.

## Runtime Data Contract

The observer emits `atr.robot_joint_telemetry.v1` packets:

```json
{
  "schema": "atr.robot_joint_telemetry.v1",
  "type": "joint_sample",
  "session_id": "...",
  "workflow": "rollout",
  "status": "live",
  "sequence": 42,
  "timestamp": "...",
  "elapsed_s": 1.25,
  "source": "omx_action_log",
  "actual_rad": {"Joint1": 0.0},
  "target_rad": {"Joint1": 0.1},
  "actual_deg": {"Joint1": 0.0},
  "target_deg": {"Joint1": 5.73},
  "applied_target_deg": {"Joint1": 5.50},
  "artifact": {}
}
```

`actual` comes from `latest_observation`. `target` comes from `requested_action`, falling back to `sent_action` only when the requested action is unavailable. `applied_target` comes from `sent_action` and remains available for diagnostics without replacing the requested policy target in the graph.

## Backend Design

`utils/lerobot_joint_telemetry.py` owns parsing, normalized OMX joint conversion, bounded incremental file reads, terminal-session detection, and artifact generation.

`/ws/lerobot/joint-telemetry` is a read-only FastAPI WebSocket. It selects the active rollout session from the existing bridge registry, tails only newly appended complete JSONL rows, coalesces stale backlog, and sends compact samples. It never calls `get_observation()`, `send_action()`, or any MotorBus method.

When a session becomes terminal, the observer writes these idempotent artifacts beside the existing motor log:

- `policy_tracking.png`: Matplotlib 3x2 joint comparison figure.
- `policy_tracking_summary.json`: source paths, sample count, timing, and per-joint MAE/RMSE/max error.
- Existing `motor_events.csv` and `motor_events.jsonl` remain the raw tabular evidence.

## Robot Viewer

The browser viewer loads `sim/robotis_omx/omx.xml` and its eight STL meshes through a read-only static asset mount. The MJCF body hierarchy, joint positions, axes, mesh scale, and gripper mimic relationship are used directly.

- Solid model: measured follower pose.
- Translucent ghost: requested policy target, visible only when a target is present.
- Rendering: Three.js, local WebGL, bounded animation loop.
- Incoming telemetry: 15-20 Hz.
- Visual interpolation: browser animation frames only; no change to robot commands.
- Hidden card: pause rendering and release the WebGL surface after the Manipulation report is removed.

## Policy Tracking Card

The live card shows one selected joint at a time for legibility. Joint selector options cover `Joint1` through `Joint5` and `Gripper`.

- X axis: `Elapsed time (s)`.
- Y axis: `Joint position (deg)`.
- Legend: `Measured follower`, `Policy target`.
- White plot background, gray axes/grid, blue actual line, orange target line.
- Display history is capped; full-session evidence remains in the backend artifacts.
- Session completion exposes the PNG and raw-data artifact paths in the card footer.

## Failure Behaviour

- No session: cards show `IDLE` and no fabricated values.
- Session exists but no action row: `WAITING FOR JOINT TELEMETRY`.
- Stale packet: freeze the last valid pose and show `STALE`.
- Malformed row: skip it and continue tailing.
- WebSocket disconnect: reconnect with bounded exponential backoff.
- Model asset failure: graph remains operational and viewer shows a model-load error.

## Verification

- Parser unit tests use real-shaped OMX action-log rows.
- Artifact tests assert PNG/JSON creation and metric values.
- API tests verify the OMX asset mount and telemetry snapshot shape.
- Static GUI tests verify both cards, source/target labels, and the local viewer bundle.
- Browser audit checks card layout, white scientific plot, model load, reconnect state, and absence of JavaScript console errors.
- A control-loop regression check confirms no LeRobot control wrapper or command builder is modified by this feature.
