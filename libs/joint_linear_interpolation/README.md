# Joint Linear Interpolation

A small, dependency-free Python layer for **LeRobot / VLA output → linear joint interpolation → the existing robot bus**.

It does not run a policy, change camera observations, recalibrate motors, or replace your robot driver. It subdivides the joint-position targets that your existing `robot.send_action()` sends to `bus.sync_write("Goal_Position", ...)`.

**Experimental robot-control software. This is not collision avoidance, trajectory planning, a safety controller, or hard-real-time control.** Keep your existing safety checks and emergency stop. Test with an operator present and an unobstructed workspace.

## Install

Use the **same Python environment as your LeRobot inference process**:

```bash
python -m pip install git+https://github.com/JIN9811/joint-linear-interpolation.git
```

For a reproducible experiment, replace the URL suffix with `git+https://github.com/JIN9811/joint-linear-interpolation.git@<commit-sha>` and record that commit.

For local development:

```bash
git clone https://github.com/JIN9811/joint-linear-interpolation.git
cd joint-linear-interpolation
python -m pip install -e .
python examples/fake_bus_demo.py
```

Python 3.10+; no runtime dependencies. The fake-bus demo does **not** access a robot, camera, network, or GPU. LeRobot and your robot driver are separate prerequisites for real use.

## Where to attach it in LeRobot

Attach **after the original `robot.connect()` has finished** and before the normal inference loop begins. Keep your existing observation preprocessing, policy calls, action postprocessing, action chunk handling and loop pacing unchanged.

```python
from joint_linear_interpolation import LinearTransmit

# Keep your existing robot creation/configuration.
robot.connect()  # original calibration, camera warmup and motor configuration
sender = None
try:
    sender = LinearTransmit(
        robot.bus,
        input_hz=30,    # SAME as the existing loop's action dispatch FPS
        output_hz=100,  # desired interpolated motor transmission rate
    )

    # Run YOUR EXISTING inference loop here, unchanged:
    # observation = robot.get_observation()
    # action = ... your existing policy + processors + action queue ...
    # robot.send_action(action)
    # ... your existing 30 Hz pacing ...
    run_your_existing_inference_loop(robot)
finally:
    # Stop/join the sender BEFORE the original driver disconnects the bus.
    if sender is not None:
        sender.close()
    robot.disconnect()
```

`run_your_existing_inference_loop` is a placeholder for your application's existing loop, **not a function provided by this package**. Do not replace that loop with an unpaced `while True`, and do not call `robot.connect()` twice. In an existing LeRobot record/evaluation script, insert the constructor after its existing `robot.connect()` and insert `sender.close()` immediately before its existing `robot.disconnect()` in the cleanup block.

This package does not add flags to stock `lerobot-record`. Integration requires those two lifecycle hooks (or your application's existing wrapper). Do not assume that an arbitrary `--linear` CLI flag is understood by LeRobot.

### Why this attachment point?

1. `robot.get_observation()` continues to read the real bus and cameras.
2. The existing `robot.send_action()` applies its original normalization, clamps and other configured protections.
3. Its final normalized `Goal_Position` write becomes an interpolation target.
4. A single in-process thread sends intermediate positions through the **original** bus write method.

The bus object, motor IDs, calibration and units are unchanged. Reads and interpolated writes share a lock to prevent concurrent serial transactions. There is no separate motor process or stale-feedback IPC cache.

## Input FPS and output Hz are different

| Existing action dispatch rate (`input_hz`) | Segment duration | Example `output_hz` |
|---|---|---|
| 15 Hz | 66.67 ms | 100 Hz |
| 30 Hz | 33.33 ms | 100 Hz |
| 30 Hz | 33.33 ms | 60 Hz |
| 60 Hz | 16.67 ms | 100 Hz |

`input_hz` is how frequently your application **dispatches actions**, not camera FPS, neural-network forward-pass FPS, or action-chunk length. For example, a policy that predicts a chunk of 50 actions can still dispatch those actions at 30 Hz: use `input_hz=30`.

The interpolation period is `1 / input_hz`. The sender's target tick interval is `1 / output_hz`. Changing output Hz does not change the policy, its scheduler, camera FPS or action-chunk length. Set rates before starting the sender; close it before reconfiguration.

The generic package accepts finite rates satisfying `0 < input_hz <= output_hz <= 1000`. **This numeric ceiling is not a tested hardware capability.** The initial application exposes up to 100 Hz. Higher rates require separate measurements of bus throughput, driver timeouts, CPU load and robot behavior.

## Supported bus contract

The bus must already be connected and expose:

```python
bus.sync_read("Present_Position")       # returns {joint_name: normalized_position}
bus.sync_write("Goal_Position", values) # accepts the same joint names and units
```

Both methods must be writable instance attributes. This matches the tested LeRobot OMX/Dynamixel path; it does **not** establish compatibility with every LeRobot robot. Torque, velocity, current, Cartesian-action and network-streaming drivers need their own integration.

The adapter accepts normalized position writes without additional positional/keyword arguments. Other register writes pass through with the same serial lock. Do not add another thread/process that directly accesses the port or calls unwrapped bus methods while the sender is attached.

## Interpolation behavior and limitations

- The first target starts from a fresh position read through the existing bus.
- Later targets start from the last position actually **commanded**, not from a predicted future waypoint.
- A new target replaces the unfinished segment. Old targets are not queued for catch-up.
- Values are bounded to the current segment endpoint; there is no extrapolation.
- After reaching the last target, the sender stops issuing writes until another target arrives. It does not invent a return-home or recovery motion.
- Missed ticks are skipped, not replayed in a burst.
- A transmit exception stops the sender and surfaces on the next ordinary wrapped read/write. There is no automatic retry or fallback.
- `close()` stops the sender and restores the original read/write methods. **It does not itself disable torque, halt a moving servo, or move the robot.** Your driver and existing stop path remain responsible for those actions. Motors may continue towards the last accepted target.
- Bus methods must have finite I/O timeouts. If a write cannot return, a Python thread cannot safely preempt it. `close()` raises if the sender fails to exit; do not reuse the bus in that state.

This is **causal smoothing**, not exact future-waypoint resampling. It can introduce approximately one action period of tracking lag. Retargeting before an endpoint is reached can cut corners and skip intermediate waypoints. Linear segments also have velocity discontinuities; there is no acceleration/jerk limit. Neither grasp success nor unchanged motion timing is guaranteed.

## Logging

Optional logging uses only command data; it does not add monitoring reads:

```python
sender = LinearTransmit(
    robot.bus, input_hz=30, output_hz=100,
    session_id="my-run", log_dir="./linear-logs",
)
```

`linear_io.jsonl` contains target sequence, target joint positions, actual intermediate commands, monotonic timestamps, requested output Hz and shutdown state. An application's original LeRobot action log typically still contains policy-level targets, not each intermediate bus write.

Measure achieved cadence from `event == "write"` timestamps. Idle time while waiting for new policy targets or encoding recordings is not active motor transmission time. The operating system and Python scheduling can prevent the requested rate from being achieved.

If writing/flushing/closing a diagnostic log fails (for example, a full disk), logging is disabled and the exception is retained as `sender.logging_error`. That diagnostic failure does not stop transmission or prevent original driver cleanup. Motor I/O errors are handled separately and are not ignored.

## What has been tested?

- Unit tests: interpolation endpoints, retargeting, variable rates, partial targets, no startup commands, serial mutual exclusion, errors and cleanup.
- Application integration: installed LeRobot OMX methods with physical serial/camera I/O substituted, including preservation of original action clamping.
- One supervised physical OMX trial of the preceding fixed-100-Hz implementation: a 30-second episode, 15-Hz action dispatch, 2,739 intermediate writes over 29.179 active seconds; average 93.836 Hz, median interval 10.000 ms. The process exited normally; the operator reported apparently smoother motion.

That single trial is **not** validation of every configurable rate, collision safety, all robot models, or improved grasp/placement success. The packaged variable-rate version is covered by software tests; it must be validated on your own hardware before routine use.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ModuleNotFoundError` | Install in the interpreter/environment that actually launches LeRobot. |
| Output rate rejected | Output Hz must not be lower than action-dispatch FPS; rates must be positive and finite. |
| Camera startup causes a failure | Attach only after the original `robot.connect()` returns. Do not change camera warmup or calibration just for interpolation. |
| Robot follows late/cuts corners | Expected causal-interpolation trade-off. Compare against OFF with the same policy, initial pose and specimen. |
| Port contention | Keep one driver/serial owner and the shared lock. Remove other direct serial access. |
| Rate below requested Hz | Inspect write intervals, bus latency, policy pauses and CPU scheduling. The setting is not a throughput guarantee. |
| Stop/torque behavior is unexpected | `close()` is sender cleanup, not an emergency stop; check the existing robot driver's stop/disconnect configuration. |

## Development

```bash
python -m pip install -e . pytest build
python -m pytest tests -q
python -m build
```

License: MIT. No LeRobot, robot calibration, policy checkpoint or lab data is distributed in this repository.
