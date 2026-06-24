# Isaac Sim ROBOTIS OMX Mirror Mode

This page documents the current Isaac Sim mirror-mode baseline for the ROBOTIS OMX-AI follower arm.

## Scope

Mirror mode is a read-only real-to-sim bridge:

- It reads the physical follower arm joint state.
- It maps follower Dynamixel IDs 11-16 to Isaac Sim joints.
- It does not command robot motion.
- It can run as a one-shot probe, a standalone continuous mirror loop, or an
  in-process live teleoperation/recording mirror.
- The standalone loop mirrors measured follower `Present_Position`.
- Live teleoperation/recording uses an in-process LeRobot wrapper that publishes
  the `send_action()` result from the same robot process. This avoids opening a
  second Dynamixel connection while the LeRobot process owns the follower bus.

This is the current foundation for synchronized real/sim teleoperation and recording evidence.

## Scene Files

Generated Isaac scene:

```text
sim/robotis_omx/scene/omx_table_layout.usda
```

Scene builder:

```text
sim/robotis_omx/tools/build_table_layout_scene.py
```

Robot asset reference:

```text
sim/robotis_omx/omx/omx.usda
```

The scene follows the operator-supplied table layout:

- Table: `700 x 450 x 30 mm`
- Robot base slot: `150 x 120 mm`, front-left at `x=240 mm`
- A4 sheet: `297 x 210 mm`, 40 mm behind the robot base, centered on the robot centerline
- Cube: `30 x 30 x 30 mm`, placed on the A4 sheet
- Right disk: `100 mm` diameter, `74 mm` height
- A4 corner markers and center marker are flat imprint markers
- Disk center marker is a flat yellow imprint marker

## Physics-Lite Scene Contract

The table scene is no longer a visual-only layout. It carries a lightweight
PhysX contract so mirror mode can step the scene while keeping collision
geometry simple enough for interactive teleoperation.

Global scene:

- `/World/PhysicsScene`
- Gravity direction: `(0, 0, -1)`
- Gravity magnitude: `9.81`
- PhysX timestep hint: `physxScene:timeStepsPerSecond = 60`

Static collision objects:

| Prim | Physics role |
| --- | --- |
| `/World/Table/TableTop` | fixed table collider |
| `/World/Workspace/A4Sheet` | fixed paper-plane collider |
| `/World/Workspace/RightDiskAluminumTop` | fixed disk top collider |
| `/World/Workspace/RightDiskBlackBase` | fixed disk base collider |

Dynamic workspace object:

| Prim | Physics role |
| --- | --- |
| `/World/Workspace/RedSpecimenBlock` | dynamic rigid body, collision enabled, mass `0.02 kg` |

The physics contract is intentionally "physics-lite":

- The physical robot remains the source of truth.
- The mirror receiver writes Isaac joint drive targets from measured follower
  state.
- Workspace objects have enough collision/rigid-body metadata for interactive
  scene stepping and later contact-aware improvements.
- It is not yet a full manipulation simulator with grasp/contact validation.

Regenerate the scene only through Isaac Sim Python because system Python does
not provide `pxr`:

```bash
/home/jin/IsaacSim/python.sh sim/robotis_omx/tools/build_table_layout_scene.py
```

## Mirror Joint Contract

Isaac articulation root:

```text
/World/Robot/Geometry/link0
```

Follower motor mapping:

| Follower motor ID | Motor name | Isaac joint | Isaac joint path |
| --- | --- | --- | --- |
| 11 | `shoulder_pan` | `Joint1` | `/World/Robot/Geometry/link0/link1/Joint1` |
| 12 | `shoulder_lift` | `Joint2` | `/World/Robot/Geometry/link0/link1/link2/Joint2` |
| 13 | `elbow_flex` | `Joint3` | `/World/Robot/Geometry/link0/link1/link2/link3/Joint3` |
| 14 | `wrist_flex` | `Joint4` | `/World/Robot/Geometry/link0/link1/link2/link3/link4/Joint4` |
| 15 | `wrist_roll` | `Joint5` | `/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/Joint5` |
| 16 | `gripper` | `Gripper` | `/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper` |

The gripper mimic path is:

```text
/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic
```

## Real-to-Sim Joint Calibration

The physical-to-Isaac conversion is centralized in:

```text
utils/isaac_omx_mirror_mapping.py
```

Both the standalone bridge loop and the in-process LeRobot wrapper use this same
module. Do not keep separate joint sign/offset/range logic in the wrapper or the
bridge; otherwise the GUI probe, teleoperation mirror, and recording sidecar can
show different poses for the same physical arm state.

Optional calibration file:

```text
memory/isaac_omx_mirror_calibration.json
```

If the file is absent, the bridge uses identity calibration and still records the
intended path with `loaded=false` in the JSONL evidence. This is the current
default.

Calibration format:

```json
{
  "joints": {
    "shoulder_lift": {
      "sign": -1,
      "scale": 1.0,
      "offset_deg": 5.0,
      "clamp_lower_deg": -120.0,
      "clamp_upper_deg": 90.0
    }
  }
}
```

Rule keys may be the ATR motor name (`shoulder_lift`), Isaac joint name
(`Joint2`), or motor ID as a string (`"12"`). The conversion order is:

```text
LeRobot action/position -> base Isaac target -> sign/scale/offset -> clamp
```

The bridge passes the same calibration file into live teleoperation/recording
with:

```text
ATR_ISAAC_MIRROR_CALIBRATION_PATH=/home/jin/autonomous_researcher/memory/isaac_omx_mirror_calibration.json
```

Use this file only for measured real-to-sim alignment corrections. Do not use it
to hide a broken motor mapping or wrong Isaac joint path; those belong in the
shared mapping module and tests.

## Bridge Tools

MCP-style tools:

```text
lerobot.mirror.joint_mapping
lerobot.mirror.state_probe
lerobot.mirror.receiver_health
lerobot.mirror.receiver_verify
lerobot.mirror.receiver_process_start
lerobot.mirror.receiver_process_status
lerobot.mirror.receiver_process_stop
lerobot.mirror.loop_start
lerobot.mirror.loop_status
lerobot.mirror.loop_stop
```

FastAPI routes:

```text
POST /api/lerobot/mirror/joint-mapping
POST /api/lerobot/mirror/state-probe
POST /api/lerobot/mirror/receiver-health
POST /api/lerobot/mirror/receiver-verify
POST /api/lerobot/mirror/receiver-process/start
POST /api/lerobot/mirror/receiver-process/status
POST /api/lerobot/mirror/receiver-process/stop
POST /api/lerobot/mirror/loop/start
POST /api/lerobot/mirror/loop/status
POST /api/lerobot/mirror/loop/stop
```

`joint_mapping` returns the static scene path, articulation root, and motor-to-joint map.

`state_probe` returns the current follower joint state:

- In `test` mode, it returns deterministic fake joint values.
- In `live` mode, it uses the saved follower port from `memory/lerobot_device_ports.json`.
- Live state probing opens the Dynamixel bus, reads `Present_Position`, and closes the port.
- Live state probing does not call LeRobot teleoperation/recording/rollout commands.

`receiver_health` checks the Isaac Sim receiver before synchronized live execution:

- It converts the configured joint endpoint, for example `http://127.0.0.1:8766/joints`, to the same server's `/health` endpoint.
- It returns the receiver `apply_mode`, `sample_count`, and health URL.
- `teleoperate.start` and `record.start` run this check automatically when `mode=live` and `isaac_mirror_enabled=true`.
- If the receiver is unavailable, the bridge returns `LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE` before starting the real LeRobot subprocess. This prevents a physical teleop/record session from running while the requested Isaac mirror evidence stream is absent.
- If the receiver is reachable but reports a mode other than `deferred_update_tick`, the session is allowed but the trace records that live Isaac GUI update-tick mode was not reported.

`receiver_verify` is a stronger end-to-end check:

- It performs the receiver health check.
- It runs a bounded one-sample `mirror_loop_start` using the current endpoint.
- It then reads the receiver `/state` endpoint and confirms the receiver reports the same mirror `session_id` and `sample_index` as the latest payload.
- It also checks that the receiver `sample_count` increased compared with the pre-check.
- If the receiver state is stale or does not match the just-posted sample, the bridge returns `LEROBOT_ISAAC_MIRROR_VERIFY_STALE_STATE`.

Use `receiver_verify` before relying on mirror evidence for a live teleop/record run. It proves the bridge-to-receiver HTTP path is working; it still does not prove physical robot motion until the live teleop/record session is actually run.

`receiver_process_start`, `receiver_process_status`, and
`receiver_process_stop` are managed receiver-process controls for the LeRobot
GUI:

- The production default launch mode is `isaac_extension`: it starts
  `/home/jin/IsaacSim/isaac-sim.sh` with `sim/robotis_omx/extensions` and the
  `atr.omx.mirror` extension enabled.
- `receiver_process_start` waits for `/health` and returns the PID, endpoint,
  command preview, log path, and health payload.
- `receiver_process_status` reports whether the managed receiver process is
  still running and re-checks `/health` when it is.
- `receiver_process_stop` terminates only the managed receiver process for the
  configured host/port. It does not stop teleoperation, recording, rollout, or
  Isaac Sim itself.

The direct script launch remains available when
`isaac_mirror_receiver_launch_mode=python_script` or
`isaac_mirror_receiver_python` is explicitly supplied. In that path the default
receiver Python is `ATR_ISAAC_MIRROR_RECEIVER_PYTHON`, then
`/home/jin/IsaacSim/python.sh`, otherwise the current Python interpreter. The
direct path is for smoke tests and offline USD target authoring; live physical
teleop/record should use the extension path so `/health.apply_mode` reports
`deferred_update_tick`.

`loop_start` starts a session with workflow `isaac_mirror`.

- It samples the follower joint state at `isaac_mirror_sample_hz` (`15 Hz` default).
- In `live` standalone mode, it opens one persistent Dynamixel reader subprocess
  and reuses that reader for all samples. It must not shell out once per sample.
- It POSTs each sample to `isaac_mirror_endpoint` (`http://127.0.0.1:8766/joints` default).
- It records per-sample synchronization metrics:
  `target_sample_hz`, `sample_period_s`, `loop_lag_ms`,
  `post_latency_ms`, `sample_total_latency_ms`, receiver accepted/status, and
  receiver sample count when the receiver returns it.
- It keeps a compact `sync_summary` in the session/status response for
  `sample_count`, effective achieved Hz, mean/max POST latency, mean/max loop
  lag, and POST success/failure counts.
- Standalone `loop_start` writes one JSONL row per sample to:

```text
runs/isaac_mirror_sessions/<session_id>.jsonl
```

When the mirror loop is attached to `record.start`, the default path is moved into the LeRobot dataset sidecar:

```text
<dataset_path>/sidecar/isaac_mirror/<record_session_id>.jsonl
```

## Live Teleoperation / Recording Mirror

When `mode=live` and `isaac_mirror_enabled=true`, `teleoperate.start` and
`record.start` do not start a separate mirror-loop reader. The bridge changes
the LeRobot command entrypoint to:

```text
python scripts/lerobot_isaac_mirror_runtime_wrapper.py teleoperate ...
python scripts/lerobot_isaac_mirror_runtime_wrapper.py record ...
```

The wrapper then invokes the normal LeRobot command flow after patching the
OMX follower `send_action()` method in the same process. For every bounded
mirror sample, it:

- converts LeRobot OMX action keys such as `shoulder_lift.pos` into the Isaac
  joint payload,
- converts `RANGE_M100_100` joints into the configured Isaac joint degree
  ranges,
- POSTs to the configured Isaac receiver endpoint,
- appends JSONL evidence to the configured mirror sidecar path.

The bridge passes these environment variables to the LeRobot subprocess:

```text
ATR_ISAAC_MIRROR_ENABLED=1
ATR_ISAAC_MIRROR_ENDPOINT=http://127.0.0.1:8766/joints
ATR_ISAAC_MIRROR_SAMPLE_HZ=15
ATR_ISAAC_MIRROR_TIMEOUT_S=0.5
ATR_ISAAC_MIRROR_SESSION_ID=<lerobot_session_id>
ATR_ISAAC_MIRROR_ATTACHED_TO_SESSION_ID=<lerobot_session_id>
ATR_ISAAC_MIRROR_PROFILE_ID=robotis_omx_ai
ATR_ISAAC_MIRROR_CALIBRATION_PATH=/home/jin/autonomous_researcher/memory/isaac_omx_mirror_calibration.json
ATR_ISAAC_MIRROR_RECORD_PATH=<jsonl_sidecar_path>
```

This is the production path for synchronized real/sim teleoperation and
recording because it matches normal LeRobot usage: one long-lived LeRobot
process owns the follower, leader, cameras, and dataset writing.

Standalone `lerobot.mirror.loop_start` remains useful for non-actuating
follower-state checks before running teleoperation.

The dataset metadata file also records the mirror contract:

```text
<dataset_path>/meta/atr_pipeline.json
```

Metadata field:

```json
{
  "isaac_mirror": {
    "enabled": true,
    "session_id": "<mirror_session_id>",
    "attached_to_session_id": "<record_session_id>",
    "record_path": "<dataset_path>/sidecar/isaac_mirror/<record_session_id>.jsonl",
    "endpoint": "http://127.0.0.1:8766/joints",
    "sample_hz": 15.0,
    "sample_count": 0,
    "status": "MIRROR_ACTIVE",
    "sync_summary": {
      "target_sample_hz": 15.0,
      "sample_period_s": 0.066667,
      "sample_count": 0,
      "effective_sample_hz": 0.0,
      "mean_post_latency_ms": 0.0,
      "max_post_latency_ms": 0.0,
      "mean_loop_lag_ms": 0.0,
      "max_loop_lag_ms": 0.0,
      "post_ok_count": 0,
      "post_fail_count": 0
    },
    "receiver_state_at_stop": {}
  }
}
```

- In `test` mode, `isaac_mirror_max_samples` controls deterministic bounded execution. If omitted, one sample is written.
- In `live` mode, the loop runs in a background thread until `loop_stop`, teleop stop, record stop, or GUI server shutdown.
- If the Isaac endpoint cannot accept an update, the mirror session fails visibly with `LEROBOT_ISAAC_MIRROR_POST_FAILED`. The bridge does not silently fall back to a fake mirror.

When the LeRobot GUI checkbox `Mirror during Teleop / Recording` is enabled, `teleoperate.start` and `record.start` start an attached mirror loop and return:

```text
isaac_mirror_session_id
isaac_mirror.mirror_record_path
isaac_mirror.sample_count
```

Stopping the teleop/record session also stops the mirror loop attached to that session.

For recording, this means the dataset, RGB-D/raw-depth sidecars, and Isaac mirror state can be archived together as one experiment evidence package.

While a live in-process recording is still active, `record.status` and session
list responses expose `isaac_mirror` directly. The bridge updates
`isaac_mirror.sample_count` from the JSONL sidecar line count before responding,
so the GUI can show mirror progress without waiting for `record.control
action=stop`.

When `record.control action=stop` stops a recording session, the bridge also stops the attached mirror loop and refreshes `meta/atr_pipeline.json` with the final mirror `status`, `sample_count`, and `receiver_state_at_stop` snapshot from the receiver `/state` endpoint when available. This makes the dataset metadata usable after the recording finishes, not only at recording start.

The mirror JSONL rows are intentionally direct evidence, not just logs. A row
contains the follower joint state that was sampled, the exact payload sent to
Isaac, the receiver POST result, and `sync_metrics`. The session response and
recording metadata contain `sync_summary`, which is the quick operator-facing
answer to "did it keep up with the requested mirror rate?"

## Isaac Sim Receiver

Receiver script:

```text
sim/robotis_omx/tools/isaac_omx_mirror_server.py
```

Isaac Sim in-process extension:

```text
sim/robotis_omx/extensions/atr.omx.mirror
```

The extension is the production path for live teleoperation/record mirror mode.
It starts the same HTTP receiver inside the Isaac Sim process and applies queued
joint samples on Isaac Kit update ticks. This is the path that can update the
visible/current Isaac stage while the physical robot moves.

Timeline handling:

- The extension does not call `timeline.play()` immediately during startup.
- When `playTimelineOnStartup=true`, it registers a delayed Kit update callback
  and starts the timeline after the GUI and scene have settled.
- The default delayed Play setting is `playTimelineDelayTicks=300`.
- This avoids the observed Isaac/Kit startup crash
  `Cannot calculate frequency: TSC ran backwards` while preserving automatic
  visible-stage playback.
- If the timeline is paused, `/health.sample_count` can still increase and the
  USD joint target/state attributes can still update, but the viewport may not
  visibly step until Play is active.

Run it inside Isaac Sim Python while the OMX scene is open:

```bash
/home/jin/IsaacSim/python.sh sim/robotis_omx/tools/isaac_omx_mirror_server.py \
  --host 127.0.0.1 \
  --port 8766
```

Endpoint:

```text
POST http://127.0.0.1:8766/joints
```

The receiver:

- accepts the bridge's `joint_state[]` payload,
- writes the latest payload to `/tmp/atr_isaac_omx_mirror_latest.json`,
- applies `UsdPhysics.DriveAPI` angular `targetPosition` values on the mapped Isaac joints when a live/current stage is available,
- saves the stage layer when possible.

When the script can access Isaac Kit's update event stream, it switches to `deferred_update_tick` mode:

- HTTP handler thread only accepts/queues the latest sample.
- Isaac Kit's update tick applies the pending sample to the USD/PhysX articulation target.
- This avoids mutating a live Isaac GUI stage directly from the HTTP server thread.

If the Kit update event stream is not available, the script uses `direct_http_thread` mode. This is suitable for offline USD authoring or smoke tests, but live GUI mirroring should prefer `deferred_update_tick`.

If the script is run outside an Isaac/pxr-capable environment, it can still expose health/state endpoints, but joint application will report `stage_unavailable`. That is a visible bridge failure, not a silent simulated success.

Managed GUI launch uses the extension by default:

```bash
/home/jin/IsaacSim/isaac-sim.sh \
  --ext-folder /home/jin/autonomous_researcher/sim/robotis_omx/extensions \
  --enable atr.omx.mirror \
  --/exts/atr.omx.mirror/enabled=true \
  --/exts/atr.omx.mirror/host=127.0.0.1 \
  --/exts/atr.omx.mirror/port=8766 \
  --/exts/atr.omx.mirror/scene=/home/jin/autonomous_researcher/sim/robotis_omx/scene/omx_table_layout.usda \
  --/exts/atr.omx.mirror/useCurrentStage=true \
  --/exts/atr.omx.mirror/openSceneOnStartup=true \
  --/exts/atr.omx.mirror/playTimelineOnStartup=true \
  --/exts/atr.omx.mirror/playTimelineDelayTicks=300
```

Direct `python.sh sim/robotis_omx/tools/isaac_omx_mirror_server.py` remains
available for HTTP smoke tests, but live teleop/record preflight blocks a
receiver that reports `apply_mode=direct_http_thread`. For live physical
mirroring, `/health` must report `apply_mode=deferred_update_tick`.

Receiver health:

```bash
curl http://127.0.0.1:8766/health
```

Expected live GUI receiver fields:

```json
{
  "ok": true,
  "status": "ready",
  "apply_mode": "deferred_update_tick",
  "pending_sample": false,
  "sample_count": 0
}
```

Receiver state:

```bash
curl http://127.0.0.1:8766/state
```

Expected state fields after one posted sample:

```json
{
  "ok": true,
  "sample_count": 1,
  "last_payload_summary": {
    "session_id": "<mirror_session_id>",
    "sample_index": 1,
    "joint_count": 6,
    "target_count": 6
  },
  "last_apply_result": {
    "status": "applied",
    "applied_count": 7,
    "missing_paths": [],
    "stage_summary": {
      "physics_ready": true,
      "physics_scene_paths": ["/World/PhysicsScene"],
      "collision_paths": [
        "/World/Table/TableTop",
        "/World/Workspace/A4Sheet",
        "/World/Workspace/RightDiskAluminumTop",
        "/World/Workspace/RightDiskBlackBase",
        "/World/Workspace/RedSpecimenBlock"
      ],
      "rigid_body_paths": ["/World/Workspace/RedSpecimenBlock"]
    }
  }
}
```

`applied_count=7` is expected for a six-motor follower payload because the
gripper has one mimic target. `missing_paths=[]` confirms that every mapped
joint path was found on the current Isaac stage. `physics_ready=true` confirms
that the opened stage has a PhysicsScene, collision objects, and at least one
rigid body.

## GUI Use

LeRobot GUI route:

```text
/lerobot
```

Use the `3. Isaac Sim Link` card:

1. Use `Open Isaac Sim Mirror` from the card, or manually start Isaac Sim with
   `--ext-folder sim/robotis_omx/extensions --enable atr.omx.mirror`.
2. Confirm Isaac Sim opens `sim/robotis_omx/scene/omx_table_layout.usda`.
3. In `/lerobot`, confirm the endpoint is `http://127.0.0.1:8766/joints`.
4. Use `Check Isaac Link` to confirm that the endpoint is reachable.
5. Use `Send Test Pose` to POST one bounded mirror sample and confirm
   `/state` reports it as latest.
6. Open `Advanced diagnostics and Standalone Mirror Test` only when you need
   joint mapping, one-shot follower reads, link process status, or standalone
   mirror-loop testing.
7. Keep `Mirror during Teleop / Recording` checked before starting
   teleoperation or recording.
8. Use `Close Isaac Sim Link` only when the managed receiver process should be
   terminated.

During teleoperation the source of truth is:

```text
physical follower Present_Position -> ATR LeRobot bridge -> Isaac mirror endpoint -> Isaac joint targetPosition
```

Inference/rollout can also be observed by the mirror loop, but only because the physical follower moves. The bridge does not mirror policy output directly.

## Live Prerequisites

Before live mirror probing:

1. Open the LeRobot GUI.
2. Detect/save the follower arm port.
3. Verify the saved follower entry exists in:

```text
memory/lerobot_device_ports.json
```

The bridge blocks with a structured failure if the saved follower port is missing or unavailable.

## Verification

Targeted bridge tests:

```bash
uv run pytest -q \
  tests/unit/test_isaac_omx_scene_physics.py \
  tests/unit/test_isaac_omx_mirror_server.py \
  tests/unit/test_isaac_omx_mirror_extension.py \
  tests/unit/test_lerobot_bridge.py::test_mirror_joint_mapping_returns_isaac_omx_contract \
  tests/unit/test_lerobot_bridge.py::test_mirror_joint_state_probe_test_mode_returns_fake_positions \
  tests/unit/test_lerobot_bridge.py::test_mirror_joint_state_probe_live_reads_saved_follower_port \
  tests/unit/test_lerobot_bridge.py::test_mirror_loop_start_test_mode_posts_and_records_samples \
  tests/unit/test_lerobot_bridge.py::test_mirror_receiver_process_start_status_and_stop \
  tests/unit/test_lerobot_bridge.py::test_mirror_receiver_extension_command_uses_isaac_app_and_extension \
  tests/unit/test_lerobot_bridge.py::test_teleoperate_start_can_attach_isaac_mirror_loop \
  tests/unit/test_lerobot_bridge.py::test_teleoperate_stop_stops_attached_isaac_mirror_loop
```

Full LeRobot bridge unit test:

```bash
uv run pytest -q tests/unit/test_lerobot_bridge.py
```

Regenerate the Isaac scene:

```bash
/home/jin/IsaacSim/python.sh sim/robotis_omx/tools/build_table_layout_scene.py
```

Check the receiver script syntax:

```bash
.venv/bin/python -m py_compile sim/robotis_omx/tools/isaac_omx_mirror_server.py
```

Receiver payload unit test:

```bash
uv run pytest -q tests/unit/test_isaac_omx_mirror_server.py
```

Validated live smoke path on the Spark workstation:

- Isaac receiver launched with `isaac-sim.sh --enable atr.omx.mirror`.
- `/health` returned `status=ready`, `apply_mode=deferred_update_tick`, and
  `last_scene_open_status=ready:/World/Robot`.
- A manual `/joints` sample produced `/state.last_apply_result.status=applied`,
  `applied_count=7`, `missing_paths=[]`, and `stage_summary.physics_ready=true`.
- A live `teleoperate.start` with `isaac_mirror_enabled=true`, `fps=30`,
  `camera_enabled=false`, and a five-second duration attached a mirror session
  and stopped cleanly with mirror samples recorded.
- A bounded test-mode record mirror smoke run posted two samples to the live
  Isaac receiver (`last_receiver_sample_count=143`), wrote
  `<dataset_path>/sidecar/isaac_mirror/<record_session_id>.jsonl` and refreshed
  `<dataset_path>/meta/atr_pipeline.json` with
  `isaac_mirror.sample_count=2` and `isaac_mirror.sync_summary`.

## Verified Smoke Tests

Last local verification: 2026-06-24 KST.

The current validated path is:

```text
LeRobot record/teleoperate process
-> scripts/lerobot_isaac_mirror_runtime_wrapper.py
-> OmxFollower.send_action() mirror hook
-> http://127.0.0.1:8766/joints
-> Isaac Sim atr.omx.mirror extension
-> deferred update-tick joint target apply
-> JSONL sidecar + dataset metadata evidence
```

Receiver continuity smoke:

- Endpoint: `http://127.0.0.1:8766/joints`
- State endpoint: `http://127.0.0.1:8766/state`
- Direct POST sequence: 4 samples
- Receiver sample count advanced from `171` to `175`
- Last apply result: `ok=true`, `target_count=6`, `applied_count=6`, `missing_paths=[]`

Live record smoke:

- Workflow: `lerobot.record.start`, `mode=live`, `camera_enabled=false`
- Dataset: `runs/isaac_mirror_live_record_smoke_datasets/atr/live-isaac-record-smoke-20260623153210`
- Session: `lr-record-20260623T153210167778Z-0001`
- LeRobot status: `COMPLETED`, return code `0`
- Mirror sidecar: `sidecar/isaac_mirror/lr-record-20260623T153210167778Z-0001.jsonl`
- Sidecar lines: `33`
- Receiver sample count at stop: `208`
- Sync summary written to `meta/atr_pipeline.json`:
  - `target_sample_hz=15.0`
  - `sample_period_s=0.066667`
  - `sample_count=33`
  - `effective_sample_hz=10.88`
  - `mean_post_latency_ms=3.21`
  - `max_post_latency_ms=6.81`
  - `post_ok_count=33`
  - `post_fail_count=0`
  - `last_receiver_sample_count=208`

Implementation notes:

- Live teleoperation/recording mirror must use the in-process wrapper, not a second standalone Dynamixel polling loop, because LeRobot owns the follower bus during live sessions.
- In-process JSONL sidecar directories must not be created before LeRobot creates the dataset root. Pre-creating the dataset root causes LeRobot dataset creation to fail with `FileExistsError`.
- Stop/status metadata must summarize JSONL `sync_metrics` from the sidecar. Counting JSONL lines only is insufficient because it drops target Hz, latency, receiver accept/fail counts, and receiver sample count.
- `meta/atr_pipeline.json` is the canonical place to verify whether a recording contains synchronized Isaac mirror evidence.

Live teleoperation smoke:

- Workflow: `lerobot.teleoperate.start`, `mode=live`, `teleop_time_s=5.0`
- Session: `lr-teleoperate-20260623T153448284844Z-0001`
- LeRobot status: `COMPLETED`, return code `0`
- Teleop log rate: `15 Hz`
- Mirror sidecar: `runs/isaac_mirror_sessions/lr-teleoperate-20260623T153448284844Z-0001.jsonl`
- Sidecar lines: `62`
- Receiver sample count at stop: `270`
- Last receiver payload: `session_id=lr-teleoperate-20260623T153448284844Z-0001`, `sample_index=62`, `joint_count=6`, `target_count=6`
- Last apply result: `ok=true`, `applied_count=7`, `missing_paths=[]`
- Sync summary at stop:
  - `target_sample_hz=15.0`
  - `sample_period_s=0.066667`
  - `sample_count=62`
  - `effective_sample_hz=12.328`
  - `mean_post_latency_ms=2.315`
  - `max_post_latency_ms=6.955`
  - `post_ok_count=62`
  - `post_fail_count=0`
  - `last_receiver_sample_count=270`
