# 사전 조사 요약: ROBOTIS OMX-AI + Hugging Face LeRobot + Autonomous Researcher GUI

## 1. 현재 프로젝트 기준선

현재 제공된 프로젝트 문서 기준으로 런타임은 `FastAPI Controller -> LangGraphRunLoop -> Stage Agent -> MCP Tool -> State Update -> Event Stream -> Web GUI` 구조를 유지해야 한다. 단계 순서는 active `graphs/configs/*.yaml` 전이에 의해 결정되며, 기본 closed-loop는 `design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian`이다. 기본 guardian=continue는 다시 design으로, stop/error는 complete/error로 라우팅된다.

SARM은 최상위 agent가 아니라 Manipulation Agent 내부의 submodule로 유지해야 한다. 기존 agent contract는 `BaseAgent.run(state, ctx) -> AgentResult`이고, tool access는 `ToolRegistry.call(name, payload)` 형태의 MCP-style contract를 따른다.

현재 GUI 기준선은 웹 대시보드, Live GUI chat/handoff, SSE `/api/events/stream`, run controls, model status, agent status, device health, structured log viewer를 포함한다. test/replay/fault-injection 모드는 모든 hardware-facing component에 적용되어야 한다.

## 2. 외부 조사 핵심

### Hugging Face LeRobot

LeRobot은 PyTorch 기반 real-world robotics framework이며, hardware-agnostic Python interface, LeRobotDataset, policy training/deployment tooling을 제공한다.

OMX 문서에는 `lerobot-find-port`, `robot.type=omx_follower`, `teleop.type=omx_leader`, camera-enabled teleoperation, `pip install -e ".[dynamixel]"`가 명시되어 있다. OMX는 preconfigured 상태로 LeRobot 사용 전 추가 motor setup/calibration이 필요 없다고 문서화되어 있다.

일반 LeRobot real robot imitation workflow는 teleoperate -> record dataset -> train policy -> inference/evaluation이다. `lerobot-record`는 dataset recording과 policy checkpoint를 넣은 evaluation/inference recording에도 사용된다. 최신 main 문서에서는 policy deployment용 `lerobot-rollout` CLI도 제공되며, base/sentry/highlight/dagger strategy와 sync/RTC inference backend를 지원한다고 문서화되어 있다.

SARM은 Stage-Aware Reward Modeling으로, task stage와 within-stage progress를 예측한다. LeRobot docs는 single_stage/dense_only/dual annotation mode, `sarm_progress.parquet`, RA-BC weighting workflow를 설명한다.

SO-101/SO101 호환성 측면에서는 LeRobot 공식 문서가 SO101 teleoperation 예시를 `robot.type=so101_follower`, `teleop.type=so101_leader`로 제시한다. 또한 LeRobot은 hardware-agnostic Robot interface와 Bring Your Own Hardware 통합 경로를 제공하므로, OMX-AI를 하드코딩하지 말고 robot profile / adapter registry로 분리하는 것이 장기 호환성에 맞다.

### ROBOTIS OMX-AI / Physical AI Tools

ROBOTIS OMX-AI는 OMX-L leader와 OMX-F follower로 구성되는 complete teleoperation set이다. ROBOTIS hardware page에 따르면 OMX-L은 5 DOF + gripper, USB-C host interface, TTL internal communication, 1 Mbps baudrate를 사용한다. OMX-F도 5 DOF + gripper이며 payload는 full reach 100 g, normal reach 250 g로 문서화되어 있다.

ROBOTIS software page는 OMX가 ROS 2 Jazzy, ros2_control, 100 Hz joint control, Dynamixel SDK, TTL Dynamixel Protocol 2.0 기반이라고 설명한다. Physical AI Tools Web UI는 recording page의 Start/Stop/Retry/Next/Finish controls, dataset path, rosbag2 recording option, model inference page의 policy path/FPS/start/finish 등을 제공한다.

## 3. 권장 통합 방향

1. LeRobot/ROBOTIS live integration은 먼저 test-mode bridge로 구현하고, live subprocess/ROS2 integration은 후순위로 둔다.
2. ROBOTIS OMX-AI는 초기 live hardware profile로 두고, SO-101은 test-mode compatibility profile 및 disabled live placeholder로 둔다. 구현은 `RobotProfile`/`LeRobotRobotAdapter` 중심으로 만들어 robot.type/teleop.type 교체만으로 확장되게 한다.
3. 기존 `robot.pick_place` tool을 바로 바꾸지 말고 `lerobot.*` tool group을 추가한 뒤 Manipulation Agent에서 strategy별로 사용할 수 있게 한다.
4. GUI는 기존 web dashboard와 Live GUI contract를 깨지 않고 LeRobot-specific tabs를 추가한다.
5. 모든 start/stop/safe-stop 신호는 typed signal로 관리하고 session_id/run_id/experiment_id를 로그와 SSE에 포함한다.
6. Vision Agent는 camera ownership을 유지하고 Manipulation Agent는 typed VisionObservation을 소비한다.
7. SARM은 Manipulation Agent 내부 advisory module로 먼저 연결한다. live SARM model이 없으면 deterministic test-mode scorer를 사용한다.
8. 각 GUI surface마다 test-mode state machine, API tests, SSE tests, fault-injection tests를 둔다.

## 4. Canonical implementation guideline

현재 프로젝트에 맞춘 실제 구현 기준 문서는 다음 파일이다.

- `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`

이 문서를 우선 기준으로 삼고, 본 사전조사 문서와 Codex 프롬프트는 배경/작업 지시 원자료로 사용한다.

## 5. Codex 파일

Codex용 상세 프롬프트는 `docs/system/codex_lerobot_robotis_gui_prompt.txt`에 작성되어 있다.
