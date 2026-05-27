# Autonomous Researcher Framework

Autonomous Researcher Framework는 실험 설계, 시편 제작, 장비 제어, 해석, 최적화를 하나의 폐루프 파이프라인으로 연결하는 로컬 멀티 에이전트 연구 자동화 시스템입니다.
현재 코드는 FastAPI 서버, Live GUI, LangGraph 런타임, 장비 브릿지, BO/CAE 워크스페이스, LeRobot 워크스페이스, Self-Evolution/Runtime IDE를 포함합니다.

## 1. 빠른 시작

처음 사용하는 사람은 먼저 [사용자 종합 매뉴얼](docs/tutorials/user_manual.ko.md)을 읽으면 됩니다. 이 문서는 설치, 첫 실행, GUI 사용, 장비 설정, 상급자용 API/graph/module 구조까지 한 번에 정리합니다.


```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
atr up
```

종료:

```bash
atr down
```

직접 실행:

```bash
.venv/bin/python -m app.serve
```

## 2. 주요 접속 경로

| 화면 | URL | 실제 템플릿/스크립트 | 역할 |
|---|---|---|---|
| Main GUI | `http://localhost:7860/` | `web/templates/index.html`, `web/static/app.js` | 전체 상태, 런 시작/정지, 모델/장비 워크스페이스 진입 |
| Live GUI | `http://localhost:7860/live` | `web/templates/planning.html`, `web/static/planning.js` | 채팅 기반 오케스트레이터, 에이전트 진행, 아티팩트/trace 확인 |
| Runtime IDE | `http://localhost:7860/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | LangGraph 그래프/노드/에지 편집, 검증, dry-run, 실행 |
| Module Management | `http://localhost:7860/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | 모듈 로드/검증/버전 관리, 생성 어댑터 관리 |
| 3DP Workspace | `http://localhost:7860/printer` | `web/templates/printer.html`, `web/static/printer.js` | PrusaLink, 슬라이싱 옵션, 오토이젝션, 테스트 출력 설정 |
| LeRobot Workspace | `http://localhost:7860/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | 포트 탐색, teleop, recording, training, visualization, rollout |
| BO Workspace | `http://localhost:7860/bo` | `web/templates/bo.html`, `web/static/bo.js` | BO/MBO/random/grid benchmark, acquisition 설정, 후보 추천 |
| CAE Workspace | `http://localhost:7860/cae` | `web/templates/cae.html`, `web/static/cae.js` | STL 기반 해석 설정, bottom fixed/top cyclic load, 결과 확인 |
| Windows Equipment | `http://localhost:7860/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | Windows PyAutoGUI bridge 검색, 저장, 테스트, 프로그램 실행 |
| Self-Evolution Lab | `http://localhost:7860/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | 프롬프트/모듈/그래프 변형, 검증, 승인, rollback |

API 문서는 서버 실행 후 `http://localhost:7860/docs`에서 확인합니다.

## 3. 실제 닫힌 루프 구조

기본 실행 그래프는 [graphs/configs/atr_closed_loop.yaml](graphs/configs/atr_closed_loop.yaml)입니다.
Run은 `POST /api/run/start` 또는 `POST /api/runtime/start`로 시작하고, 내부적으로 `LangGraphRunLoop`가 현재 stage를 읽어 다음 노드를 호출합니다.

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian
                                                                                                      | continue
                                                                                                      v
                                                                                                    design

guardian -> stop: complete
guardian -> error: error
```

루프가 실제로 돈다는 증거는 event stream에 남습니다.

- `run.started`
- `node.started`
- `node.completed`
- `edge.traversed` 또는 `stage_transition`
- `approval.requested` / `approval.resolved`
- `artifact.created`
- `run.completed` 또는 `run.failed`

관련 API:

- `GET /api/runtime/state`
- `GET /api/events/recent`
- `GET /api/events/stream`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/artifacts`

## 4. 에이전트 역할

| Stage | 모듈 위치 | 주 역할 | 대표 출력 |
|---|---|---|---|
| `design` | `graphs/modules/design` | 실험 목표를 TPMS/시편 설계 변수와 `experiment_spec`으로 변환 | `current_experiment_spec`, STL 후보 조건 |
| `specimen` | `graphs/modules/specimen` | STL/제조 메타데이터 생성, Prusa/virtual bridge handoff | STL, gcode, slicer settings, printer prepare result |
| `vision` | `graphs/modules/vision` | 출력물/작업공간 관측, pickup/검사용 observation 작성 | `observation`, camera artifact |
| `manipulation` | `graphs/modules/manipulation` | LeRobot policy rollout 또는 pick-place handoff | rollout status, policy path, transfer evidence |
| `equipment` | `graphs/modules/equipment` | UTM/Windows bridge/장비 명령 실행 | equipment result, protocol note |
| `analysis` | `graphs/modules/analysis` | UTM/CAE/FEM 기반 성능 지표와 objective score 산출 | metrics, contour artifact, objective_score |
| `knowledge` | `graphs/modules/knowledge` | 실험 결과를 메모리/근거로 정리해 다음 최적화에 전달 | memory update, evidence summary |
| `bo` | `graphs/modules/bo` | acquisition/surrogate/benchmark 기반 다음 후보 선택 | `bo_result`, next candidate |
| `guardian` | `graphs/modules/guardian` | 안전 게이트, 승인 상태, continue/stop/error 결정 | guardian decision |

기존 단독 `agents/` 폴더는 agent 구현/호환 레이어이고, 현재 runtime loop에서 우선 보는 실행 계약은 `graphs/modules/*/module.yaml`과 `graphs/configs/*.yaml`입니다.

## 5. Live/Test/Virtual 모드

- `live`: 실제 장비 호출 경로입니다. Prusa, LeRobot, Windows bridge, UTM 등 장비 설정이 맞아야 합니다.
- `test`: 실제 장비를 호출하지 않는 검증 경로입니다. 단, 테스트 안의 일부 옵션은 사용자가 선택하면 실제 bridge 직전까지 또는 실제 출력으로 갈 수 있습니다.
- `virtual`: 장비 없이 experiment API, benchmark, dry-run 중심으로 검증합니다.

공통 계약:

- `experiment.evaluate`
- `experiment.benchmark`
- `experiment.queue.status`
- graph dry-run gate
- Guardian approval gate

## 6. 실제 폴더 구조와 책임

| 폴더 | 설명 |
|---|---|
| `app/` | FastAPI 앱, route, runtime controller, API endpoint |
| `web/templates/` | HTML 템플릿 |
| `web/static/` | GUI JavaScript/CSS/icon 정적 파일 |
| `graphs/configs/` | LangGraph 실행 그래프 YAML |
| `graphs/modules/` | stage agent module 계약, handler, tool allowlist |
| `device_bridges/` | Prusa, LeRobot, Windows, UTM 등 장비 연동 레이어 |
| `experiments/` | experiment objective/evaluate/benchmark/queue 계약 |
| `orchestrator/` | 오케스트레이션 및 planning flow |
| `backends/` | Ollama/vLLM/Nemoclaw 등 LLM backend 연결 |
| `gui/` | GUI viewmodel/panel 보조 코드 |
| `knowledge/` | memory/retrieval 관련 코드 |
| `learning/` | LeRobot/학습 관련 helper |
| `self_evolution/` | Self-Evolution variant/task/validation 로직 |
| `mcp_tools/` | tool-call/MCP 연계 레이어 |
| `memory/` | 로컬 설정/장비 연결/그래프 버전/세션성 메모리 |
| `runs/` | run별 로그, artifact, printer/robot session 기록 |
| `artifacts/` | STL, gcode, CAE, UI audit 결과물 |
| `image/` | 시스템/에이전트 다이어그램 prompt, SVG, rendered image |
| `install/` | `atr` CLI 설치, PrusaSlicer 등 설치 보조 |
| `tests/` | unit/integration/UI audit 테스트 |
| `docs/` | 설명 문서와 시스템 지시 문서 분리 보관 |
| `user_files/` | 사용자 입력 파일/작업 파일 보관 영역 |

## 7. 주요 설정 파일

- [REQUIREMENTS.md](REQUIREMENTS.md): 설치 필요 항목, 외부 의존성, git clone/다운로드 항목
- [requirements.txt](requirements.txt): Python 패키지
- [pyproject.toml](pyproject.toml): 프로젝트/pytest 설정
- [graphs/configs/atr_closed_loop.yaml](graphs/configs/atr_closed_loop.yaml): 기본 폐루프 그래프
- `memory/prusa_connection.json`: PrusaLink 연결 정보
- `memory/bo_workspace_settings.json`: BO GUI 저장 설정
- `memory/cae_workspace_settings.json`: CAE GUI 저장 설정
- `memory/lerobot/`: LeRobot profile/calibration/port memory

## 8. 운영 순서

1. `atr up`으로 서버를 시작합니다.
2. Main GUI에서 모델과 장비 상태를 확인합니다.
3. `/live`에서 목표를 입력하고 테스트 모드로 먼저 실행합니다.
4. Live GUI의 Report, Backend, Graph, Artifacts, Timeline 탭에서 각 stage 결과를 확인합니다.
5. 3DP/LeRobot/CAE/BO/Windows workspace에서 필요한 장비 설정을 저장합니다.
6. Live 모드로 전환할 때는 Guardian approval과 장비 gate를 확인합니다.
7. 실험 결과는 `runs/`, `artifacts/`, `memory/`에 남습니다.

## 9. 문서 진입점

- [문서 전체 인덱스](docs/README.md)
- [사용자 종합 매뉴얼](docs/tutorials/user_manual.ko.md)
- [닫힌 루프와 페이지/에이전트 상세](docs/runtime/closed_loop_and_pages_reference.md)
- [LangGraph runtime](docs/runtime/langgraph_runtime.md)
- [Experiment runtime](docs/runtime/autonomous_experiment_runtime.md)
- [Live GUI 설명](docs/gui/gui.md)
- [첫 자동 실행 튜토리얼](docs/tutorials/first_autonomous_run.ko.md)
- [GitHub/버전관리 규칙](docs/repository/github_version_control.md)

## 10. 유지보수 규칙

- 런타임 동작을 바꾸면 관련 `docs/runtime`, `docs/gui`, `docs/agents`, `docs/hardware`를 같이 수정합니다.
- 위험한 변경은 요청받은 경우에만 브랜치를 만들고, 검증 후 병합합니다.
- `main`은 항상 실행 가능한 기준선으로 유지합니다.
- 시스템 지시 문서는 `docs/system/`에, 사용자/협업용 설명 문서는 그 외 docs 하위 폴더에 둡니다.
