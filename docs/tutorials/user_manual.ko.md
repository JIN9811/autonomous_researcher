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
- Live GUI의 agent 표시와 일부 report card는 `/api/runtime/agent-manifests`가 기준이며, `graphs/modules/<agent>/ui.yaml`은 표시 전용 descriptor다.
- 현재 코드가 실제로 노출하는 route/API/manifest/model 상태는 [../runtime/current_code_snapshot.md](../runtime/current_code_snapshot.md)에 정리한다.
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
- 3DP: Bambu Lab X2D가 기본 printer profile이며, Prusa MK4S는 명시 선택 profile로 유지된다. Bambu live camera proxy에는 `ffmpeg`가 필요하다.
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
| Module Management `/module-management` | agent module 검증/버전 관리, draft module 생성, `ui.yaml` 표시 descriptor 관리 | 각 module validate/dry-run 확인, draft는 실행되지 않는지 확인 |
| 3DP `/printer` | Bambu Lab X2D 기본 device bridge, printer fleet, camera/status, slicing/start gate, autoejection 설정 | connection/profile/test options 저장 |
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

Specimen Making Agent를 선택하면 Report 영역은 3DP 작업 모니터로 동작합니다. 중앙의 `Live Job Monitor`가 현재 job progress, layer, queue, remaining time, local/remote G-code path를 보여주고, 주변에 `Build Intent`, `Printer Telemetry`, `Readiness Gate`, `Slice Profile`, `Thermal / Material`, `Transfer Queue`, `Layer Preview`, `Camera Evidence`, `Post-Print Automation`, `G-code Validation`, `Handoff / Artifacts` card가 배치됩니다. 이 값들은 `specimen_agent_report.v1`과 3DP bridge API evidence에서 읽으며, 값이 없으면 임의로 만들지 않고 pending/unknown으로 표시합니다.

Live GUI agent 목록은 `web/static/planning.js` 하드코딩 값보다 `/api/runtime/agent-manifests`를 우선합니다. 이 manifest는 graph YAML, module YAML, 선택적 `ui.yaml`을 합칩니다. `ui.yaml`은 label, short name, icon, report card selector 같은 화면 표시만 바꿀 수 있고, handler/tool/graph transition/live device 권한은 바꾸지 않습니다.

### 1.7 작업 결과가 저장되는 곳

| 위치 | 내용 |
|---|---|
| `runs/<run-id>/` | run별 이벤트, 로그, workspace evidence |
| `runs/<run-id>/live_planning_transcript.jsonl` | Live GUI 채팅/시스템 메시지 compact transcript. `/api/planning/messages`가 이 파일을 page 단위로 읽음 |
| `artifacts/` | STL, G-code, CAE, UI audit 결과 |
| `memory/` | 로컬 설정, 장비 연결, graph/module version memory |
| `outputs/train/` | LeRobot training output/checkpoint |
| `user_files/` | 사용자가 넣는 입력 파일 |

## 2. 초보자용: 장비별 설정

### 2.1 3DP / Bambu Lab X2D 기본 + Prusa MK4S 명시 선택

설정 위치:

- GUI: `/printer`
- printer fleet 선택: `memory/printer_fleet.json`
- Bambu 연결 정보: `memory/bambu_connection.json`
- Prusa 연결 정보: `memory/prusa_connection.json`
- 출력 profile: `memory/prusa_print_profile.json`

처음 해야 할 일:

1. `/printer`의 Printer Fleet에서 기본 `bambulab_x2d_lab_01` 또는 명시적 `prusa_mk4s_lab_01`을 선택한다.
2. Bambu를 쓸 때는 host/IP, SN, printer name, LAN access code를 저장한다. access code 원문은 GUI/API 응답에 표시되지 않는다.
3. Bambu `Live Status`로 MQTT/FTPS/storage 상태를 확인하고, `Video Status`로 RTSPS/JPEG video port와 `ffmpeg` proxy 준비 상태를 확인한다.
4. profile에서 material, nozzle, layer height, bed temperature, first layer speed를 확인한다.
5. test specimen size와 test unit cell size를 저장한다.
6. 실제 출력 전에는 upload/start gate, camera/video evidence, bed-clear evidence, autoejection 옵션을 확인한다.
7. 현재 3DP GUI는 별도 operator/Guardian/dry-run 체크박스를 노출하지 않는다. `Start Gate Check`, `SPC Readiness`, `Publish Start`는 owner-managed publish 기본값(`operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`, ejection path 관리값 true)을 보내고, 백엔드가 artifact, printer safe-state, camera, bed-clear, post-publish observation으로 최종 차단한다.
8. `SPC Readiness`의 level cards는 connection, transfer path, owner-managed publish default, publish command, autoejection을 분리해서 보여준다. `technical_ready_for_start=true`여도 camera/bed-clear/safe-state/start gate blocker가 있으면 실제 publish는 되지 않는다.
9. Bambu X2D에서 `Upload Path Probe`는 FTPS가 실제로 write/delete 가능한지 확인한다. login/list만 성공해도 upload-ready가 아니다.
10. FTPS가 `read_only` 또는 `BAMBU_FTPS_WRITE_FAILED`이면 sliced `.gcode.3mf` 파일을 `Prepare HTTP Artifact`로 노출한다. 이때 backend가 artifact URL을 실제 GET하고 sha256을 비교해 `server_fetch_probe.ok=true`를 반환해야 Upload gate가 ready로 바뀐다. 이 검증은 프린터가 접근 가능한 LAN URL 기준이다. 서버는 기본적으로 `0.0.0.0:7860`에 바인딩되어야 하며, artifact URL은 `http://<ATR서버-LAN-IP>:7860/printer-artifacts/...` 형태여야 한다. `127.0.0.1` 바인딩 또는 localhost URL은 브라우저에서는 동작해도 Bambu 프린터 transfer evidence로 인정하지 않는다.
11. `cache/specimen.gcode.3mf` 같은 일반 remote path는 HTTP artifact route가 아니다. FTPS write 검증을 우회할 수 있는 것은 `/api/printer/http-artifact-route`가 만든 `http://` 또는 `https://` URL 중 fetch probe가 통과한 URL뿐이다.
12. `HTTP_ARTIFACT_READY_NOT_STARTED`는 artifact URL과 guarded start-command draft가 준비됐다는 뜻이다. 실제 출력 시작은 아니며, `Publish Start`는 browser confirmation 이후에도 owner-managed publish defaults와 backend start gate, camera/bed-clear/safe-state 검증을 모두 통과해야 한다.
13. `Publish Start`가 MQTT `project_file` 명령을 보냈더라도 그것만으로 실제 출력 시작으로 간주하지 않는다. backend는 즉시 fresh printer observation을 다시 읽고 `post_publish_status`를 붙인다. 프린터가 `IDLE` 또는 not-started 상태로 남으면 `published=true`여도 `ok=false`, `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 표시한다.
14. Bambu autoejection의 `Fill Native G-code Defaults`는 native patch 입력값만 채운다. source artifact와 plate target을 확인한 뒤 `Save Autoejection Config`를 눌러야 `memory/bambu_autoejection.json`에 반영된다. 이 단계는 artifact patch/검증 준비이며, 실제 시작은 별도의 `Publish Start` gate가 통과해야 한다.
15. `Validate G-code Preview`와 left/center/right validation은 원본 artifact를 바꾸지 않는 검증 동작이다. 이 validation-only 경로는 `.autoeject.*` 파일이나 manifest를 만들지 않고 would-be tail, object bounds, candidate hash, blocker만 반환한다. `Generate Ejection Test Artifact`와 `Generate Sweep Test Artifact`는 publish 없는 standalone 검증 파일만 만든다. 실제 `.autoeject.*` 출력 파일이 필요하면 `Generate Patched Artifact`를 사용하고, 실제 프린터 motion은 `Publish Start` live gate가 통과한 경우에만 허용한다.
16. Bambu autoejection 조정값은 push direction, Z push offset, push lane offset, push speed, full-bed sweep, sweep Z, sweep speed로 관리한다. P1/P1S/X1/X1C 계열과 A1/A1 Mini 계열은 ejection generator가 다르므로 서로 같은 G-code path를 쓰지 않는다.
17. `.autoeject.*` 실제 publish 전 물리 환경(front path/door, ramp/bin, toolhead cover, release surface/profile, supervised first ejection)은 workstation owner/operator가 프린터 앞에서 직접 관리한다. GUI는 수동 checklist 대신 `operator_managed=true` evidence를 기록하고, backend는 camera/bed-clear/artifact/start-state blocker로 차단한다.
18. `Video Status` 또는 camera refresh가 실패해도 기존 MQTT/progress/material status는 유지되어야 한다. camera는 별도 plane이며, 실패 시 camera 영역에 blocker를 표시한다.
19. Bambu bridge evidence는 `artifact`, `validation`, `transport`, `runtime`, `bed-clear` 5개 plane으로 읽는다. 실제 autoejection 성공은 `published=true`가 아니라 camera/operator observation, post-publish status, bed-clear lock/unlock, 다음 job gate 해제까지 확인됐을 때만 인정한다.
20. 실제 Bambu autoejection 완료 판정은 `/printer`의 `Physical Proof Package` 또는 `scripts/audit_bambu_autoejection_completion.py`로 수행한다. `Build Fail-Closed Proof Template`은 증거 작성용 JSON을 만들 뿐이고, `Run Completion Audit`이 file-backed camera/manifest/post-publish/bed-clear/next-job evidence를 모두 확인하기 전까지 physical success가 아니다.

주의:

- password/API key는 Git에 커밋하지 않는다.
- Bambu LAN access code도 Git에 커밋하지 않는다.
- `/api/bridges`는 graph bridge registry이며 Bambu printer fleet 선택 API가 아니다. Bambu 기본 profile은 `/api/printer/fleet`에서 확인한다.
- Bambu live camera browser view는 `ffmpeg`가 설치되어야 `/api/printer/video-stream.mjpeg`로 표시된다.
- `test` 기본 흐름은 dry/virtual이어야 한다.
- `테스트 모드, 실제 출력`은 명시적으로 실제 출력 경로를 요청한 경우에만 사용한다.
- `Publish Start`를 눌러도 backend gate가 차단하면 MQTT start command는 전송되지 않는다.

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
화면 표시 descriptor는 선택적으로 `graphs/modules/<module>/ui.yaml`에 둔다.

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
- `GET /api/runtime/agent-manifests`
- `GET /api/bridges`
- `POST /api/modules`
- `POST /api/modules/templates/{agent|ui-only|bridge}`
- `GET /api/modules/{module_id}`
- `GET /api/modules/{module_id}/ui`
- `PUT /api/modules/{module_id}/ui`
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
- `ui.yaml`은 Live GUI 표시 전용이다. 실행 handler, tool allowlist, graph transition, device 권한을 바꾸지 않는다.
- `/api/modules/templates/*`가 만든 draft module은 `status=draft`, `enabled=false`, `graph.attached=false`라서 validate/dry-run/graph attach/save 전에는 실행되지 않는다.
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
- 현재 Main GUI/API가 관리하는 로컬 vLLM 모델은 `gemma4:31b`와
  `gemma4:e4b-it-nvfp4` 두 개다. `e2b`는 현재 managed model surface가
  아니다.
- `31b`는 orchestrator route의 primary이며 MTP speculative decoding을
  사용한다. `e4b`는 design/analysis/knowledge/guardian/tool-formatting 등
  하위 route의 primary이며 NVFP4 target-only로 서빙한다.
- OpenAI API key는 Main GUI `Current Models`의 `API Key` 버튼에서
  저장/Loading/Unloading한다. `Loading` 상태에서는 OpenAI가 첫 inference
  route가 되고, `Unloading`하면 저장값은 유지하되 local vLLM이 다시
  우선된다.
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
atr model load 31b
atr model load e4b
atr model unload 31b
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
atr model load 31b
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
- RealSense를 쓰는 경우 SDK serial이 보이는지. 현재 기본값은
  `top=D455F/341522300873`, `wrist=D405/352122273019`이다.

조치:

```bash
atr down
atr up
```

필요하면 LeRobot GUI의 force stop/status를 사용한다.

RealSense 전역 진단:

```bash
rs-enumerate-devices
rs-fw-update -l
python3 - <<'PY'
import pyrealsense2 as rs
ctx = rs.context()
print("device_count", len(list(ctx.query_devices())))
for dev in ctx.query_devices():
    print(
        dev.get_info(rs.camera_info.name),
        dev.get_info(rs.camera_info.serial_number),
        dev.get_info(rs.camera_info.usb_type_descriptor),
    )
PY
```

정상 기준:

- D455F와 D405가 모두 보여야 한다.
- 둘 다 SDK USB `3.2` 또는 sysfs `5000M`으로 잡히는 것이 안정적이다.
- `2.1` 또는 `480M`이면 코드 문제가 아니라 USB 허브/케이블/포트 협상 문제부터 본다.

D455F/D405가 보이는데 스트림만 `RS2_USB_STATUS_BUSY`,
`failed to set power state`, 또는 frame timeout이면:

```bash
fuser -v /dev/video* 2>/dev/null || true
```

점유 프로세스가 없으면 허브를 power-cycle/replug한 뒤 다시 시도한다.
필요할 때만 root smoke test로 power-state를 깨운 뒤 일반 사용자로 재시도한다.
이 상태에서는 카메라 역할 매핑을 OpenCV `/dev/video*`로 바꾸지 않는다.

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
