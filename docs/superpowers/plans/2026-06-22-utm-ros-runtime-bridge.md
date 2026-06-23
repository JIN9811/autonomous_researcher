# UTM ROS Runtime Bridge + RQT-like GUI Implementation Plan

## Objective
Add a production-ready UTM ROS Vision runtime bridge to ATR without replacing the existing ATR architecture. The RQT-like graph must follow the cloned UTM repository at `/home/jin/external_repos/UTM` as the source of truth.

## Source Of Truth
The expected ROS/RQT flow is derived from these UTM files:

- `/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh`
- `/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/camera_rect.launch.py`
- `/home/jin/external_repos/UTM/src/compression_tester_monitor/launch/green_dot_monitor.launch.py`
- `/home/jin/external_repos/UTM/scripts/yolo.sh`

Expected flow:

```text
camera/usb_cam
  -> /camera/image_raw
  -> camera/rectify_node
  -> /camera/image_rect
  -> compression_tester_monitor/green_dot_monitor
  -> /image_utm
  -> yolo_bringup/yolov8

compression_tester_monitor/green_dot_monitor
  -> /compression_tester/state
  -> /compression_tester/summary
  -> /compression_tester/metrics
  -> /compression_tester/green_points
  -> /compression_tester/debug_image

yolo_bringup/yolov8
  -> /yolo/detections
  -> /yolo/tracking
  -> /yolo/dbg_image
```

The GUI graph will show this expected graph and overlay actual ROS graph evidence when ROS is running. It must not invent a different RQT topology.

## Constraints
- Do not wholesale-copy `autonomous_researcher_required_files/app/main.py` or `app/bootstrap.py`; they are older snapshots.
- Keep ATR's current OpenAI/vLLM/NemoClaw, Bambu, LeRobot, Runtime IDE, CalculiX/PINN, and loop architecture intact.
- No silent fallback. If test mode uses virtual UTM evidence, show a fallback trace and message.
- Live mode may auto-start and diagnose, but must not claim physical UTM completion through virtual evidence.
- If no graph change is detected, do not re-render the RQT-like graph.

## TDD Steps
1. Add failing unit tests for UTM state observer parsing and temporal summary.
2. Add failing unit tests for UTM runtime process manager, cloned UTM expected graph, graph hash stability, and missing ROS diagnostics.
3. Add failing unit tests for `vision.equipment_cross_check` UTM behavior:
   - live uses observer evidence
   - live blocks/attention on insufficient evidence
   - test mode falls back to virtual bridge with explicit fallback trace
   - non-UTM checks keep existing simulator behavior
4. Add failing integration tests for `/api/equipment/utm-runtime/status|start|stop|probe|graph|frame`.
5. Add static UI tests for Device Workspace UTM card IDs and JS handlers.

## Implementation Steps
1. Add `device_bridges/utm_state_observer.py` with ROS String JSON parsing and time-window state summarization.
2. Add `device_bridges/utm_runtime_bridge.py` with:
   - process-group start/stop/status
   - ROS command/topic/node probing
   - cloned UTM expected graph builder
   - actual graph overlay parser
   - graph hash/revision tracking
   - frame status placeholder/live hook
   - singleton factory shared by bootstrap and FastAPI routes
3. Extend `configs/devices.yaml` with `devices.utm_vision_runtime` defaulting to `/home/jin/external_repos/UTM`.
4. Wire `app/bootstrap.py` so `register_camera_tools` receives the runtime manager and observer.
5. Extend `mcp_tools/camera_tools.py` for UTM checks and virtual test bridge.
6. Add FastAPI routes under `/api/equipment/utm-runtime/*`.
7. Add Main GUI Device Workspace card and JS controls.
8. Add Live GUI UTM/RQT status panel only after backend API is stable.
9. Update requirements/docs/install notes for ROS2 Jazzy, UTM workspace, and browser verification.
10. Run unit/integration tests, then browser audit/screenshots.

## Verification
Required before completion:

```bash
pytest tests/unit/test_utm_state_observer.py \
       tests/unit/test_utm_runtime_bridge.py \
       tests/unit/test_camera_tools_utm_runtime.py \
       tests/integration/test_utm_runtime_gui_api.py

pytest tests/integration/test_controller_run.py
pytest tests/ui/*utm*  # if added
```

Manual/browser verification:

- Start ATR server.
- Open Main GUI Device Workspaces.
- Confirm UTM ROS System card renders.
- Click Loading/Probe/Unloading and confirm buttons lock during callbacks.
- Confirm RQT-like graph matches cloned UTM flow and only re-renders on hash change.
- Open Live GUI test mode and confirm Vision/Equipment UTM panel shows real probe or explicit virtual fallback.
