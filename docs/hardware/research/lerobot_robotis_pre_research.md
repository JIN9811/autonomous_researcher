<a id="사전-조사-요약-robotis-omx-ai--hugging-face-lerobot--autonomous-researcher-gui"></a>
# Preliminary Research Summary: ROBOTIS OMX-AI + Hugging Face LeRobot + Autonomous Researcher GUI

This is a pre-integration research record; “current” below refers to the time of that research.
For installed packages/APIs and execution authority, use the [LeRobot Reference](../../device_bridges/lerobot_bridge.md);
for agent handoff and post-test clearance, use the [Manipulation Reference](../../agents/manipulation_agent.md).
Descriptions of external project features do not establish that every feature has been verified in ATR.

<a id="1-현재-프로젝트-기준선"></a>
## 1. Project Baseline at the Time of Research

The project documents supplied for the research required the runtime to preserve `FastAPI Controller -> LangGraphRunLoop -> Stage Agent -> MCP Tool -> State Update -> Event Stream -> Web GUI`. Stage order is determined by the active `graphs/configs/*.yaml` transitions. The baseline closed loop was described as `design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian`; default guardian=continue returns to design, while stop/error routes to complete/error. This historical linear summary is not the full current conditional graph: current Vision/Manipulation and equipment-clearance transitions must be read from the active configuration.

The existing agent contract is `BaseAgent.run(state, ctx) -> AgentResult`, with MCP-style tool access through `ToolRegistry.call(name, payload)`.

The GUI baseline includes the web dashboard, Live GUI chat/handoff, SSE `/api/events/stream`, run controls, model status, agent status, device health, and a structured log viewer. The proposal requires test/replay/fault-injection modes for every hardware-facing component.

<a id="2-외부-조사-핵심"></a>
## 2. External Research Findings

### Hugging Face LeRobot

The reviewed sources describe LeRobot as a PyTorch-based real-world robotics framework with a hardware-agnostic Python interface, LeRobotDataset, and policy training/deployment tools.

The reviewed OMX documentation specifies `lerobot-find-port`, `robot.type=omx_follower`, `teleop.type=omx_leader`, camera-enabled teleoperation, and `pip install -e ".[dynamixel]"`. It describes OMX as preconfigured, without additional motor setup/calibration before LeRobot use; this external statement does not waive ATR's installed-profile preflight checks.

The general LeRobot real-robot imitation workflow is teleoperate -> record dataset -> train policy -> inference/evaluation. `lerobot-record` is also used for evaluation/inference recording with a policy checkpoint. The main-branch documentation reviewed at the time also described a `lerobot-rollout` deployment CLI with base/sentry/highlight/dagger strategies and sync/RTC inference backends.


For SO-101/SO101 compatibility, the reviewed official LeRobot examples use `robot.type=so101_follower` and `teleop.type=so101_leader`. Its hardware-agnostic Robot interface and Bring Your Own Hardware integration path support separating robot profiles/adapters into a registry rather than hard-coding OMX-AI for long-term compatibility.

### ROBOTIS OMX-AI / Physical AI Tools

The reviewed ROBOTIS hardware page describes OMX-AI as a complete teleoperation set with an OMX-L leader and OMX-F follower. OMX-L has 5 DOF + gripper, a USB-C host interface, TTL internal communication, and a 1 Mbps baud rate. OMX-F also has 5 DOF + gripper, with documented payloads of 100 g at full reach and 250 g at normal reach.

The reviewed ROBOTIS software page describes OMX as based on ROS 2 Jazzy, ros2_control, 100 Hz joint control, Dynamixel SDK, and TTL Dynamixel Protocol 2.0. Physical AI Tools Web UI provides recording-page Start/Stop/Retry/Next/Finish controls, dataset paths, a rosbag2 recording option, and inference-page policy path/FPS/start/finish controls.

<a id="3-권장-통합-방향"></a>
## 3. Proposed Integration Direction

1. Implement a test-mode bridge first; defer live subprocess/ROS2 integration.
2. Use ROBOTIS OMX-AI as the initial live hardware profile and SO-101 as a test-mode compatibility profile with a disabled live placeholder. Build around `RobotProfile`/`LeRobotRobotAdapter` so robot.type/teleop.type can be changed for expansion.
3. Add a `lerobot.*` tool group for strategy-specific use by Manipulation Agent rather than immediately replacing `robot.pick_place`.
4. Add LeRobot-specific GUI tabs without breaking the existing web dashboard or Live GUI contract.
5. Use typed signals for all start/stop/safe-stop actions and include session_id/run_id/experiment_id in logs and SSE.
6. Keep camera ownership with Vision Agent; Manipulation Agent consumes typed VisionObservation.
8. Provide a test-mode state machine, API tests, SSE tests, and fault-injection tests for each GUI surface.

## 4. Canonical implementation guideline

The detailed implementation guideline for this project is:

- `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`

Use that guideline with its current-contract notice; this preliminary research document and the Codex prompt are background and original task-instruction material.

<a id="5-codex-파일"></a>
## 5. Codex File

The detailed Codex prompt is retained at `docs/oldversion/system/codex_lerobot_robotis_gui_prompt.txt`.
