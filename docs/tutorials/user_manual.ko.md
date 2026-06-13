# Autonomous Researcher 사용자 종합 매뉴얼

이 문서는 새 사용자가 저장소를 받아서 실행하고, 기존 사용자가 구조를 이해해 수정/확장할 수 있도록 만든 운영 매뉴얼입니다.

대상 독자:

- 초보자: GUI를 열고 테스트 모드로 첫 실행을 확인해야 하는 사용자
- 운영자: 프린터, 로봇, Windows bridge, CAE/BO 워크스페이스를 설정해야 하는 사용자
- 개발자: LangGraph, agent module, API, 테스트를 수정하거나 확장해야 하는 사용자

## 0. 한눈에 보는 시스템

```text
사용자
  -> Main GUI 또는 Live GUI
  -> FastAPI runtime controller
  -> LangGraphRunLoop
  -> design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian
  -> continue면 design으로 반복, stop이면 complete, error면 error
```

핵심 원칙:

- GUI, CLI, API는 같은 runtime state/event/artifact를 본다.
- 실제 실행 순서는 `graphs/configs/atr_closed_loop.yaml`이 기준이다.
- 각 단계의 실제 계약은 `graphs/modules/<agent>/module.yaml`이 기준이다.
- 실제 장비는 bridge와 safety gate를 통과해야만 호출된다.
- generated output, 비밀번호, 로컬 장비 IP, 모델 캐시는 Git에 넣지 않는다.

## 1. 초보자용: 처음 실행하기

### 1.1 준비물

필수:

- Linux workstation
- Python 3.11 이상
- Git
- Bash terminal
- 이 저장소: `/home/jin/autonomous_researcher`

선택/장비별 필요:

- vLLM/Nemoclaw: NVIDIA GPU, Docker/k3s, NemoClaw container
- 3DP: Prusa MK4S, PrusaLink, PrusaSlicer Docker wrapper
- Robot: `/home/jin/lerobot`, conda env `lerobot`, ROBOTIS/LeRobot 장비
- Windows bridge: Windows PC, Python, PyAutoGUI bridge server
- CAE live solver: CalculiX/Gmsh 또는 현재 bridge가 지원하는 solver 환경

자세한 설치 조건은 [../../REQUIREMENTS.md](../../REQUIREMENTS.md)를 먼저 봅니다.

### 1.2 설치

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
```

새 터미널에서 `atr` 명령이 안 보이면:

```bash
source ~/.bashrc
```

### 1.3 서버 실행과 종료

```bash
atr up
```

브라우저에서 접속:

- Main GUI: `http://localhost:7860/`
- Live GUI: `http://localhost:7860/live`
- API 문서: `http://localhost:7860/docs`

종료:

```bash
atr down
```

직접 실행이 필요할 때:

```bash
.venv/bin/python -m app.serve
```

### 1.4 첫 테스트 실행 권장 순서

1. `atr up`으로 서버를 켠다.
2. Main GUI `http://localhost:7860/`에 들어간다.
3. 모델 상태와 Device Workspace 버튼이 보이는지 확인한다.
4. Live GUI `http://localhost:7860/live`를 연다.
5. 채팅에 `테스트 모드` 또는 테스트 목적을 입력한다.
6. Report, Backend, Graph, Artifacts, Timeline 탭을 보면서 단계가 진행되는지 확인한다.
7. 결과 파일은 `runs/`, `artifacts/`, `memory/` 아래에서 확인한다.

테스트 모드에서 봐야 하는 증거:

- `run_id`가 생성됨
- `design`, `specimen`, `analysis`, `bo`, `guardian` 등 stage 이벤트가 기록됨
- 실패 시 `failure_code`, `node.failed`, `run.failed`가 표시됨
- 실제 장비를 쓰지 않는 경로에서는 upload/start/rollout 같은 live action이 실행되지 않음

### 1.5 GUI 페이지별 사용법

| 화면 | 언제 쓰는가 | 처음 할 일 |
|---|---|---|
| Main GUI `/` | 전체 상태 확인, 서버/모델/장비 진입 | runtime state, model status, device workspace 확인 |
| Live GUI `/live` | 오케스트레이터와 대화하며 실험 실행 | 먼저 test mode로 목표 입력 |
| Runtime IDE `/ide` | graph 구조를 보고 수정/검증 | Main System graph dry-run 확인 |
| Module Management `/module-management` | agent module 검증/버전 관리 | 각 module validate/dry-run 확인 |
| 3DP `/printer` | PrusaLink/슬라이싱/오토이젝션 설정 | connection/profile/test options 저장 |
| LeRobot `/lerobot` | 포트, 카메라, teleop, record, train, rollout | follower/leader/camera 포트 저장 |
| BO `/bo` | acquisition/strategy/parameter space 설정 | settings 저장 후 benchmark 실행 |
| CAE `/cae` | STL 해석 조건 설정 | bottom fixed/top cyclic 기본값 확인 |
| Windows `/equipment/windows` | Windows PyAutoGUI bridge 연결 | scan, candidate save, test program 실행 |
| Self-Evolution `/evolution-lab` | prompt/module/graph variant 관리 | target 선택 후 variant validate |

### 1.6 Live GUI에서 보는 핵심 영역

- Chat: 사용자와 오케스트레이터/agent 메시지
- Agent Binder: 현재 stage와 agent별 상태
- Report: 선택 agent의 요약 보고서
- Backend: raw trace, LLM/tool input/output, failure code
- Graph: 현재 graph/node 흐름
- Artifacts: STL, G-code, CAE contour, BO plot, log 등 산출물
- Timeline: runtime event 순서
- Device strip: GPU/LLM/Printer/Robot/Camera/Windows bridge 등 상태

### 1.7 작업 결과가 저장되는 곳

| 위치 | 내용 |
|---|---|
| `runs/<run-id>/` | run별 이벤트, 로그, workspace evidence |
| `artifacts/` | STL, G-code, CAE, UI audit 결과 |
| `memory/` | 로컬 설정, 장비 연결, graph/module version memory |
| `outputs/train/` | LeRobot training output/checkpoint |
| `user_files/` | 사용자가 넣는 입력 파일 |

## 2. 초보자용: 장비별 설정

### 2.1 3DP / Prusa MK4S

설정 위치:

- GUI: `/printer`
- 연결 정보: `memory/prusa_connection.json`
- 출력 profile: `memory/prusa_print_profile.json`

처음 해야 할 일:

1. Prusa MK4S가 같은 네트워크에서 접근 가능한지 확인한다.
2. `/printer`에서 host/IP, username/password 또는 API key를 저장한다.
3. profile에서 material, nozzle, layer height, bed temperature, first layer speed를 확인한다.
4. test specimen size와 test unit cell size를 저장한다.
5. 실제 출력 전에는 upload/start gate와 autoejection 옵션을 확인한다.

주의:

- password/API key는 Git에 커밋하지 않는다.
- `test` 기본 흐름은 dry/virtual이어야 한다.
- `테스트 모드, 실제 출력`은 명시적으로 실제 출력 경로를 요청한 경우에만 사용한다.

### 2.2 LeRobot / ROBOTIS

설정 위치:

- GUI: `/lerobot`
- profile/port memory: `memory/lerobot_device_ports.json`
- conda env: `lerobot`
- LeRobot checkout: `/home/jin/lerobot`

처음 해야 할 일:

1. follower와 leader를 각각 연결한다.
2. baseline/detect 방식으로 follower/leader 포트를 저장한다.
3. 기본 카메라 `top`, `wrist`를 각각 capture test한다.
4. teleoperation을 먼저 확인한다.
5. recording, visualization, training, rollout 순서로 진행한다.

주의:

- `/dev/ttyACM*`, `/dev/video*`는 재부팅 후 바뀔 수 있으므로 by-id/by-path 저장을 우선한다.
- live motion은 operator confirmation과 profile gate가 필요하다.
- rollout은 duration을 비워두면 stop할 때까지 이어지는 경로로 동작할 수 있다.

### 2.3 Windows PyAutoGUI Bridge

설정 위치:

- GUI: `/equipment/windows`
- Windows server: `install/windows_pyautogui_bridge_server.py`
- 연결 memory: `memory/windows_pyautogui_connection.json`

Windows에서:

```powershell
py -m pip install pyautogui
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<token>"
py windows_pyautogui_bridge_server.py
```

GUI에서:

1. subnet과 token으로 scan한다.
2. candidate가 뜨면 원하는 이름으로 저장한다.
3. saved target을 select한다.
4. `test` 또는 `program1` 실행으로 통신을 확인한다.

### 2.4 BO / CAE

BO:

- GUI: `/bo`
- 설정 memory: `memory/bo_workspace_settings.json`
- 주요 옵션: strategy, acquisition, budget, seed, parameter space
- 직접 장비를 시작하지 않고 후보 추천/benchmark/evidence 생성에 집중한다.

CAE:

- GUI: `/cae`
- 설정 memory: `memory/cae_workspace_settings.json`
- 기본 조건: bottom fixed support, top cyclic compression loading
- live solver가 없으면 `CAE_SOLVER_REQUIRED`로 차단될 수 있다.

## 3. 상급자용: 런타임 구조

### 3.1 실행 엔트리포인트

주요 route는 `app/main.py`에 있다.

| 기능 | API |
|---|---|
| runtime state | `GET /api/runtime/state`, `GET /api/state` |
| recent events | `GET /api/events/recent` |
| SSE stream | `GET /api/events/stream` |
| start/pause/resume/stop | `POST /api/run/start`, `/api/run/pause`, `/api/run/resume`, `/api/run/stop` |
| safe stop | `POST /api/run/safe-stop` |
| run detail | `GET /api/runs/{run_id}` |
| run events/artifacts | `GET /api/runs/{run_id}/events`, `GET /api/runs/{run_id}/artifacts` |
| approvals | `GET/POST /api/runs/{run_id}/approvals`, `POST /api/runs/{run_id}/approvals/{approval_id}/resolve` |

### 3.2 Graph 계약

기본 graph:

- `graphs/configs/atr_closed_loop.yaml`

workspace graph templates:

- `graphs/configs/printer_pipeline.yaml`
- `graphs/configs/lerobot_pick_place.yaml`
- `graphs/configs/utm_test_flow.yaml`

Graph API:

- `GET /api/graphs`
- `GET /api/graphs/{graph_id}`
- `POST /api/graphs/{graph_id}/validate`
- `POST /api/graphs/{graph_id}/validate-draft`
- `POST /api/graphs/{graph_id}/compile`
- `POST /api/graphs/{graph_id}/export-yaml`
- `POST /api/graphs/{graph_id}/import-yaml`
- `POST /api/graphs/{graph_id}/dry-run`
- `GET /api/graphs/{graph_id}/dry-run-gate`
- `POST /api/graphs/{graph_id}/save-version`
- `POST /api/graphs/{graph_id}/run`

Live 실행 전 요구:

- graph validate 통과
- compile 통과
- dry-run gate 통과
- Guardian/safety gate 통과
- 장비별 live gate 통과

### 3.3 Module 계약

각 stage module은 `graphs/modules/<module>/module.yaml`에 있다.

공통 필드:

- `module.id`
- `module.label`
- `module.handler`
- `module.llm_role`
- `module.safety`
- `module.tools`
- `module.pre_execution`
- `module.internal_graph`
- `module.io_contract`

Module API:

- `GET /api/modules`
- `GET /api/modules/management-state`
- `POST /api/modules`
- `GET /api/modules/{module_id}`
- `POST /api/modules/{module_id}/load`
- `POST /api/modules/{module_id}/unload`
- `POST /api/modules/{module_id}/validate`
- `POST /api/modules/{module_id}/dry-run`
- `GET /api/modules/{module_id}/versions`
- `GET /api/modules/{module_id}/versions/{version_id}`
- `POST /api/modules/{module_id}/register-generated`

중요한 경계:

- GUI가 module YAML을 수정해도 arbitrary Python을 바로 실행하지 않는다.
- handler는 allowlisted registry를 통과해야 한다.
- generated adapter는 register/approval 없이는 실제 runtime handler로 승격되지 않는다.

### 3.4 Agent 단계별 내부 step

| Stage | 내부 step 요약 |
|---|---|
| design | constraint intake, candidate spec, FDM printability, specimen handoff |
| specimen | print profile, TPMS STL, slicing, upload/virtual bridge, vision handoff |
| vision | output capture, pose estimate, transfer readiness, manipulation handoff |
| manipulation | policy profile, robot bridge, transfer rollout, equipment handoff |
| equipment | Windows bridge, program selection, UTM macro, analysis handoff |
| analysis | UTM curve parse, metrics, CAE, objective score |
| knowledge | prior runs retrieval, failure summary, memory write, BO handoff |
| bo | history load, surrogate fit, acquisition evaluation, next constraints |
| guardian | safety gates, failure review, continue/stop/error decision |

### 3.5 LLM backend

관련 위치:

- `backends/`
- `deploy/nemoclaw-vllm.yaml`
- Main GUI model controls
- `POST /api/runtime/backend`
- `GET /api/runtime/models`
- `POST /api/runtime/models/load`
- `POST /api/runtime/models/unload`
- `POST /api/runtime/gpu-clear`

운영 원칙:

- backend switching은 runtime 전체에 영향을 준다.
- model load/unload는 GUI와 CLI가 같은 API를 쓴다.
- vLLM/Nemoclaw 모델 상태가 준비됐다고 해서 첫 generation JIT 지연이 없다는 뜻은 아니다.
- context overflow가 나면 최근 대화/프롬프트/출력 토큰을 먼저 줄인다.

### 3.6 CLI와 GUI 상호호환

`atr`는 GUI와 같은 API를 호출한다.

자주 쓰는 명령:

```bash
atr
atr up
atr down
atr status
atr events
atr run start test
atr run start live "PLA compression specimen"
atr run safe-stop
atr models
atr model load e4b
atr model unload e4b
atr graph validate atr_closed_loop
atr graph dry-run atr_closed_loop
atr module validate design
atr module dry-run design
atr chat "테스트 모드"
```

GUI에서 바꾼 graph/module은 API를 통해 저장되므로 CLI에서도 같은 상태를 확인해야 한다.

## 4. 상급자용: 개발/확장 규칙

### 4.1 새로운 agent나 module을 추가할 때

1. `graphs/modules/<new_module>/module.yaml`을 만든다.
2. handler는 기존 allowlist 방식에 맞춘다.
3. `tools` allowlist를 최소화한다.
4. `internal_graph`를 단계별로 나눈다.
5. Runtime IDE 또는 API로 validate/dry-run한다.
6. 필요하면 `graphs/configs/*.yaml`에 node/edge/transition을 추가한다.
7. 테스트와 문서를 같이 갱신한다.

### 4.2 새로운 장비 bridge를 추가할 때

1. bridge health API를 먼저 만든다.
2. test/virtual/live mode를 분리한다.
3. live gate는 fail-closed로 둔다.
4. 실제 장비 action은 job/session id를 남긴다.
5. command input/output, status, log path, artifact path를 event로 남긴다.
6. GUI와 CLI/API가 같은 저장 설정을 보게 한다.
7. 비밀번호/token/IP는 `memory/*.json` 또는 `.env`에만 둔다.

### 4.3 Runtime IDE에서 graph를 수정할 때

권장 순서:

1. Main System 또는 agent tab에서 draft를 수정한다.
2. Validate를 실행한다.
3. Dry Run을 실행한다.
4. Compile summary와 transition path를 확인한다.
5. Save Version을 실행한다.
6. live mode 전에는 dry-run gate digest가 active graph와 맞는지 확인한다.

하지 말아야 할 것:

- 검증 없이 live run 시작
- handler allowlist 없이 Python 실행
- Guardian stop/error route 제거
- 장비 gate를 우회하는 edge 추가

### 4.4 Module Designer를 사용할 때

Module Designer는 Python 파일을 ATR 통신규약에 맞는 module 형태로 변환하는 도구다.

흐름:

1. Python 파일 업로드
2. Gemma 31B로 module metadata/adapter 초안 생성
3. `graphs/modules/<module_id>/handler.py`와 `module.yaml` 생성
4. module validate/dry-run
5. explicit register-generated 승인
6. graph에 연결하고 dry-run

보안/안전 원칙:

- 업로드된 Python은 바로 실행하지 않는다.
- generated handler는 wrapper/adapter와 registry gate를 통과해야 한다.
- 실행 전 `module.dry-run` evidence를 남긴다.

## 5. 테스트와 검증

기본 테스트:

```bash
pytest
```

분야별 테스트:

```bash
pytest tests/unit/test_design_agent.py
pytest tests/unit/test_specimen_agent.py
pytest tests/unit/test_printer_tools.py
pytest tests/integration/test_controller_run.py
pytest tests/integration/test_live_gui_runtime_layout.py
pytest tests/integration/test_printer_gui_api.py
pytest tests/integration/test_lerobot_gui_api.py
pytest tests/integration/test_bo_gui_api.py
pytest tests/integration/test_cae_gui_api.py
```

브라우저/UI audit:

```bash
python tests/ui/planning_browser_audit.py
python tests/ui/runtime_ide_browser_audit.py
python tests/ui/module_management_browser_audit.py
python tests/ui/live_runtime_ide_browser_audit.py
```

검증 기준:

- API route가 200/정상 JSON을 반환한다.
- Live GUI가 event/session/artifact를 같은 run_id로 본다.
- graph validate/compile/dry-run이 통과한다.
- 장비 live action은 gate 없이는 실행되지 않는다.
- generated artifact가 `runs/` 또는 `artifacts/`에 남는다.
- 실패는 `failure_code`, `node.failed`, `run.failed`로 추적 가능해야 한다.

## 6. 트러블슈팅

### 서버가 안 켜질 때

확인:

```bash
atr status
atr down
atr up
```

직접 실행으로 traceback 확인:

```bash
cd /home/jin/autonomous_researcher
source .venv/bin/activate
python -m app.serve
```

### Live GUI가 멈춘 것처럼 보일 때

확인 순서:

1. `GET /api/runtime/state`에서 `run_id`, `stage`, `is_running` 확인
2. `GET /api/events/recent`에서 최근 event 확인
3. `GET /api/runs/{run_id}/events`에서 run event 확인
4. `guardian` decision, approval pending, failure_code 확인
5. 브라우저를 새로고침해도 session state가 유지되는지 확인

### 모델 호출이 실패할 때

확인:

- backend가 원하는 값인지
- 모델이 loaded인지
- context length를 넘지 않았는지
- vLLM 첫 generation JIT 지연인지
- GPU memory가 다른 프로세스에 잡혀 있는지

명령:

```bash
atr backend
atr models
atr model load e4b
atr gpu clear
```

### 프린터가 upload만 하고 start하지 않을 때

확인:

- `memory/prusa_connection.json` host/auth
- `/printer`의 upload/start gate
- PrusaLink storage filename과 requested filename 차이
- transfer idle 대기 여부
- `/api/v1/job`이 이전 작업 99/100% 상태에 남아 있는지
- start retry history

### LeRobot 카메라/포트가 안 잡힐 때

확인:

- saved port가 `/dev/serial/by-id` 또는 `/dev/v4l/by-id`인지
- follower/leader 역할이 바뀌지 않았는지
- top/wrist 카메라 index 또는 by-id 링크가 현재 연결 상태와 맞는지
- stale subprocess가 카메라/serial을 점유 중인지

조치:

```bash
atr down
atr up
```

필요하면 LeRobot GUI의 force stop/status를 사용한다.

### graph가 live에서 막힐 때

확인:

- graph validate 통과 여부
- dry-run gate digest가 active graph와 일치하는지
- Guardian terminal route가 있는지
- cycle에 guard가 있는지
- handler signature/registry error가 없는지

## 7. Git/GitHub 운영

기본 원칙:

- `main`은 실행 가능한 기준선으로 유지한다.
- 작은 문서/안전 변경은 바로 main에서 처리할 수 있다.
- 위험 변경이나 사용자가 브랜치를 요청한 작업은 branch에서 진행한다.
- 커밋 전 `git status`로 의도하지 않은 변경을 확인한다.
- secrets, device IP/password, generated STL/G-code, model cache는 커밋하지 않는다.

권장 순서:

```bash
git status
git add <files>
git commit -m "docs: update user manual"
git push
```

자세한 규칙은 [../repository/github_version_control.md](../repository/github_version_control.md)를 본다.

## 8. 문서 유지 규칙

변경 종류별로 같이 고쳐야 하는 문서:

| 변경 | 같이 수정할 문서 |
|---|---|
| GUI route/API 변경 | `docs/README.md`, `docs/gui/gui.md`, 이 문서 |
| graph/stage 변경 | `docs/runtime/langgraph_runtime.md`, `docs/runtime/closed_loop_and_pages_reference.md`, 이 문서 |
| agent module 변경 | `docs/agents/*`, `docs/runtime/agent_program_baseline.md`, 이 문서 |
| 프린터 변경 | `docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`, 이 문서 |
| LeRobot 변경 | `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`, 이 문서 |
| Windows bridge 변경 | `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`, 이 문서 |
| 설치 의존성 변경 | `REQUIREMENTS.md`, `install/README.md`, 이 문서 |
| Git workflow 변경 | `docs/repository/github_version_control.md` |

## 9. 빠른 판단표

| 상황 | 먼저 볼 곳 |
|---|---|
| 처음 실행 | 이 문서 1장, [../../REQUIREMENTS.md](../../REQUIREMENTS.md) |
| 루프 이해 | [../runtime/closed_loop_and_pages_reference.md](../runtime/closed_loop_and_pages_reference.md) |
| GUI 사용 | [../gui/gui.md](../gui/gui.md) |
| graph 수정 | [../runtime/langgraph_runtime.md](../runtime/langgraph_runtime.md) |
| agent 수정 | `graphs/modules/*/module.yaml`, [../runtime/agent_program_baseline.md](../runtime/agent_program_baseline.md) |
| 프린터 | [../hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](../hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| 로봇 | [../hardware/lerobot_robotis_manipulation_runtime_guideline.md](../hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Windows bridge | [../hardware/windows_pyautogui_equipment_agent_guideline.md](../hardware/windows_pyautogui_equipment_agent_guideline.md) |
| BO | [../agents/bo_agent_runtime_guideline.txt](../agents/bo_agent_runtime_guideline.txt) |
| CAE | [../agents/cae_analysis_runtime_guideline.txt](../agents/cae_analysis_runtime_guideline.txt) |
| 버전관리 | [../repository/github_version_control.md](../repository/github_version_control.md) |
