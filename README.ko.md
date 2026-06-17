# Autonomous Researcher Framework

Autonomous Researcher Framework는 실험 설계, 시편 제작, 장비 제어, 해석, 최적화를 하나의 폐루프 파이프라인으로 연결하는 로컬 멀티 에이전트 연구 자동화 시스템입니다.
현재 코드는 FastAPI 서버, Live GUI, LangGraph 런타임, 장비 브릿지, BO/CAE 워크스페이스, LeRobot 워크스페이스, Self-Evolution/Runtime IDE를 포함합니다.

## 1. 빠른 시작

처음 사용하는 사람은 먼저 [사용자 종합 매뉴얼](docs/tutorials/user_manual.ko.md)을 읽으면 됩니다. 이 문서는 설치, 첫 실행, GUI 사용, 장비 설정, 상급자용 API/graph/module 구조까지 한 번에 정리합니다.

현재 코드와 문서가 다르게 보일 때는
[현재 코드/API 스냅샷](docs/runtime/current_code_snapshot.md)을 먼저
확인하세요. 이 스냅샷은 `app/main.py`, `graphs/configs/*.yaml`,
`graphs/modules/*`, `device_bridges/*`, `web/templates/*`,
`web/static/*` 기준으로 현재 route/API/manifest 상태를 정리합니다.
2026-06-17 기준 `app/main.py`에는 FastAPI `APIRoute` endpoint 224개가
있습니다. `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`,
`/static`까지 포함한 전체 `app.routes` 등록 수는 229개입니다. 이 수치는
문서 갱신 시 실제 코드와 맞는지 확인하는 sanity check로 사용합니다.
단순 decorator grep가 아니라 FastAPI app을 import해 `APIRoute` 객체를
세는 기준입니다. 일부 route는 단일 줄 decorator literal이 아니기 때문에
grep 수치와 다를 수 있습니다.

Windows에서 로컬 AI 없이 API key만 사용할 때는 `.env`에
`AUTONOMOUS_BACKEND=openai`와 `OPENAI_API_KEY`를 설정한 뒤
`python -m app.serve`로 실행합니다. Linux 로컬 우선 워크스테이션은
`AUTONOMOUS_BACKEND=vllm`을 유지하고, `configs/models.yaml`의
`backend.fallback: openai`를 통해 OpenAI를 최종 fallback으로 사용합니다.
Main GUI의 `Current Models` 영역에는 `API Key` 버튼이 있으며,
저장된 key는 `memory/api_keys.json`에 로컬 전용으로 보관됩니다.
`Loading` 상태에서는 OpenAI API가 첫 inference route가 되고,
`Unloading`하면 저장값은 유지하되 로컬 vLLM route가 다시 우선됩니다.
현재 관리되는 로컬 vLLM 모델은 `gemma4:31b`와
`gemma4:e4b-it-nvfp4` 두 개입니다. `e2b`는 Main GUI/API의 managed model
목록에서 제거된 상태입니다. `31b`는 MTP speculative decoding을 사용하고,
`e4b`는 안정성을 위해 NVFP4 target-only로 서빙합니다.

### Linux 설치 - 기본 경로

Linux/WSL 기본 설치는 저장소 루트에서 bootstrap을 실행합니다. 이 경로는
서버, GUI, Python 의존성, `atr` CLI, `.env` 템플릿까지 준비합니다.
LeRobot, RealSense RSUSB, Bambu Studio, Docker/vLLM 같은 장비별 외부
프로그램은 [REQUIREMENTS.md](REQUIREMENTS.md)의 해당 섹션을 이어서
설치합니다.

```bash
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
bash install/bootstrap_linux.sh
atr doctor
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

### Windows 설치 - 지원 범위와 제한사항

Windows 기본 설치는 API key 기반 GUI/API 실행과 Windows PyAutoGUI bridge
운영을 우선 지원합니다. Bash 기반 `atr` 런처, Linux Docker/RSUSB/vLLM
경로, ROBOTIS/RealSense live robot 경로는 WSL/Linux 또는 별도 conda 설정이
필요합니다.

```powershell
git clone <private-repo-url> autonomous_researcher
cd autonomous_researcher
powershell -ExecutionPolicy Bypass -File .\install\bootstrap_windows.ps1
python -m app.serve
```

Windows에서 local AI 없이 쓰려면 `.env`에 `AUTONOMOUS_BACKEND=openai`와
`OPENAI_API_KEY`를 설정합니다. 장비 제어용 Windows PyAutoGUI bridge는
별도 PowerShell에서 `install\windows_pyautogui_bridge_server.py`를 실행합니다.

## 2. 주요 접속 경로

| 화면 | URL | 실제 템플릿/스크립트 | 역할 |
|---|---|---|---|
| Main GUI | `http://localhost:7860/` | `web/templates/index.html`, `web/static/app.js` | 전체 상태, 런 시작/정지, 모델/장비 워크스페이스 진입 |
| Live GUI | `http://localhost:7860/live` | `web/templates/planning.html`, `web/static/planning.js` | 채팅 기반 오케스트레이터, 에이전트 진행, 아티팩트/trace 확인 |
| Runtime IDE | `http://localhost:7860/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | LangGraph 그래프/노드/에지 편집, 검증, dry-run, 실행 |
| Module Management | `http://localhost:7860/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | 모듈 로드/검증/버전 관리, draft module 생성, `ui.yaml` descriptor 관리, 생성 어댑터 관리 |
| 3DP Workspace | `http://localhost:7860/printer` | `web/templates/printer.html`, `web/static/printer.js` | Bambu Lab X2D 기본 브릿지, Prusa 명시 선택, live video/status, 슬라이싱/start gate, 오토이젝션, 테스트 출력 설정 |
| LeRobot Workspace | `http://localhost:7860/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | 포트 탐색, teleop, recording, training, visualization, rollout |
| BO Workspace | `http://localhost:7860/bo` | `web/templates/bo.html`, `web/static/bo.js` | BO/MBO/LLM preference 전략, lightweight/BoTorch optional backend, reasoning audit, 후보 ranking/추천 |
| CAE Workspace | `http://localhost:7860/cae` | `web/templates/cae.html`, `web/static/cae.js` | STL 기반 해석 설정, bottom fixed/top cyclic load, 결과 확인 |
| Windows Equipment | `http://localhost:7860/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | Windows PyAutoGUI bridge 검색, 저장, 테스트, 프로그램 실행 |
| Self-Evolution Lab | `http://localhost:7860/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | 프롬프트/모듈/그래프 변형, 검증, 승인, rollback |

API 문서는 서버 실행 후 `http://localhost:7860/docs`에서 확인합니다.

기본 서버 바인딩은 `0.0.0.0:7860`입니다. 브라우저는 계속
`http://localhost:7860/`로 접속해도 되지만, Bambu Lab HTTP artifact
route를 실제 프린터가 가져가려면 같은 LAN에서 보이는
`http://<ATR서버-LAN-IP>:7860/printer-artifacts/...` URL이 필요합니다.
서버를 `127.0.0.1`에만 바인딩하면 GUI는 열리더라도 Bambu fetch probe와
SPC Readiness transfer gate가 실패합니다.

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
| `specimen` | `graphs/modules/specimen` | STL/제조 메타데이터 생성, 선택된 Bambu/Prusa/virtual printer bridge handoff | STL, gcode/sliced artifact, slicer settings, printer prepare result |
| `vision` | `graphs/modules/vision` | 출력물/작업공간 관측, pickup/검사용 observation 작성 | `observation`, camera artifact |
| `manipulation` | `graphs/modules/manipulation` | LeRobot policy rollout 또는 pick-place handoff | rollout status, policy path, transfer evidence |
| `equipment` | `graphs/modules/equipment` | UTM/Windows bridge/장비 명령 실행 | equipment result, protocol note |
| `analysis` | `graphs/modules/analysis` | UTM/CAE/FEM 기반 성능 지표와 objective score 산출 | metrics, contour artifact, objective_score |
| `knowledge` | `graphs/modules/knowledge` | 실험 결과를 메모리/근거로 정리해 다음 최적화에 전달 | memory update, evidence summary |
| `bo` | `graphs/modules/bo` | Analysis/Knowledge evidence 기반 numeric BO + LLM reasoning soft prior로 다음 후보 선택 | `bo_result`, `candidate_ranking`, `next_design_request` |
| `guardian` | `graphs/modules/guardian` | 안전 게이트, 승인 상태, continue/stop/error 결정 | guardian decision |

기존 단독 `agents/` 폴더는 agent 구현/호환 레이어이고, 현재 runtime loop에서 우선 보는 실행 계약은 `graphs/modules/*/module.yaml`과 `graphs/configs/*.yaml`입니다.

Live GUI의 agent 목록과 일부 report card/section은 `/api/runtime/agent-manifests`를 통해 graph/module/`ui.yaml`에서 읽습니다. 이 API는 `agents[]`를 포함한 manifest payload를 반환하고, `web/static/planning.js`의 `DEFAULT_LIVE_AGENTS`는 manifest 요청 실패 시 사용하는 fallback입니다. 현재 `design`, `equipment`, `guardian`은 `graphs/modules/<agent>/ui.yaml` descriptor card와 selector 기반 `report_sections`를 사용하며, descriptor가 없는 agent는 기존 generic renderer를 사용합니다. 현재 generic descriptor는 selector row/card/report section, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, 내부 GUI navigation action, read-only GET API action, 안전한 workspace handoff 버튼을 처리합니다. 백엔드는 chart/action descriptor를 표시용 계약으로 정규화해 `supported`, `render_mode`, `safe_navigation`, `live_card_runnable`, `handoff_required`, `handoff_workspace`, `execution_scope`, `blocked_reason`을 붙이고, 프론트엔드는 이 계약을 다시 안전 필터링해 렌더링합니다. `ui.renderer.dashboard/report/fallback`은 `descriptor`, `generic`, `<agent>_reference` allowlist 안에서만 presentation-only profile로 동작하며, 임의 외부 renderer/plugin 코드를 로드하지 않습니다. `kind=api`, `method=GET`, `read_only=true`이고 FastAPI GET route가 존재하는 내부 `/api/*`만 `read_only_api`로 호출됩니다. POST/confirmation/non-read-only API descriptor는 안전한 operator workspace로만 handoff할 수 있고, 물리 장비 action은 이 descriptor 경로에서 실행하지 않습니다. 새 draft module은 `/api/modules/templates/{agent|ui-only|bridge}`로 만들 수 있지만, 기본값은 `status=draft`, `enabled=false`, `graph.attached=false`라서 검증/graph attach/save 전에는 실행되지 않습니다.

Live GUI 대화는 `runs/<active_run_id>/live_planning_transcript.jsonl`에 저장되고 `/api/planning/messages`로 페이지 단위 로딩됩니다. Module Management의 `Load/Unload`는 관리 화면 선택 상태이며 실제 runtime activation이 아닙니다. 실행에는 Runtime IDE에서 graph attach, validate, dry-run, save/version, live gate가 필요합니다. Graph에 아직 연결되지 않은 module은 Module Management의 Runtime IDE 버튼이 `/ide?module=<id>&action=attach`로 열어 Module Library attach 대상을 강조합니다.

Custom stage는 현재 graph/module validation과 `Stage._missing_()`를 통해 최소 실행할 수 있습니다. Stage별 follow-up 문구를 바꾸려면 payload 또는 `module_runtime`의 `supervisor_policy`를 사용합니다. 현재 Module Management typed form은 handler/LLM/tool/prompt/safety/step과 `supervisor_policy`의 required outputs, opinion/recommendation template, response-required status, concern rules, options를 편집할 수 있습니다. Graph attach/save는 Runtime IDE의 main graph drag/drop과 validate/dry-run/Save Version gate를 사용합니다.

## 5. Live/Test/Virtual 모드

- `live`: 실제 장비 호출 경로입니다. 선택된 printer bridge(Bambu Lab X2D가 기본, Prusa는 명시 선택), LeRobot, Windows bridge, UTM 등 장비 설정이 맞아야 합니다.
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
| `device_bridges/` | Bambu, Prusa, LeRobot, Windows, UTM 등 장비 연동 레이어 |
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
- `graphs/modules/*/module.yaml`: stage별 실행 계약, handler, tool allowlist, safety 설정
- `graphs/modules/*/ui.yaml`: Live GUI 표시용 card/report section descriptor. 실행 권한은 바꾸지 않음
- `memory/printer_fleet.json`: 현재 선택된 printer profile
- `memory/bambu_connection.json`: Bambu Lab LAN 연결 정보
- `memory/bambu_autoejection.json`: Bambu autoejection handoff용 provider routine 및 pre/post vision evidence
- `memory/manipulation_agent_bridge.json`: Bambu handoff를 소비할 Manipulation Agent profile 및 policy 경로
- `memory/prusa_connection.json`: PrusaLink 연결 정보
- `memory/bo_workspace_settings.json`: BO GUI 저장 설정
- `memory/cae_workspace_settings.json`: CAE GUI 저장 설정
- `memory/lerobot/`: LeRobot profile/calibration/port memory

현재 코드가 실제로 노출하는 page route, API group, agent manifest,
printer fleet, model/API-key 상태는
[현재 코드 스냅샷](docs/runtime/current_code_snapshot.md)에 정리합니다.
설계 문서와 코드가 다르게 보일 때는 이 스냅샷과 `app/main.py`의 route를
먼저 확인합니다.

주의: `/api/bridges`는 현재 `graphs/configs/atr_closed_loop.yaml`의
graph metadata bridge registry를 normalized contract로 반환합니다.
반환값에는 workspace, health/preflight endpoint, `actions[]`에 들어간
standard/custom action descriptor, evidence contract, health snapshot이
포함되며 같은 shape가
`/api/runtime/state.runtime_ide_contract.device_bridges`에도 들어갑니다.
Bambu Lab X2D는 이 목록이 아니라 `/api/printer/fleet`와 `/api/printer/*`
provider 계층에서 기본 active profile로 관리됩니다. 따라서 Bambu가
`/api/bridges`에 없다고 Bambu printer bridge가 비활성이라는 뜻은
아닙니다.

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
- [현재 코드/API 스냅샷](docs/runtime/current_code_snapshot.md)
- [LangGraph runtime](docs/runtime/langgraph_runtime.md)
- [Experiment runtime](docs/runtime/autonomous_experiment_runtime.md)
- [Live GUI 설명](docs/gui/gui.md)
- [API key / OpenAI fallback](docs/runtime/api_keys.md)
- [첫 자동 실행 튜토리얼](docs/tutorials/first_autonomous_run.ko.md)
- [GitHub/버전관리 규칙](docs/repository/github_version_control.md)

## 10. 유지보수 규칙

- 런타임 동작을 바꾸면 관련 `docs/runtime`, `docs/gui`, `docs/agents`, `docs/hardware`를 같이 수정합니다.
- 위험한 변경은 요청받은 경우에만 브랜치를 만들고, 검증 후 병합합니다.
- `main`은 항상 실행 가능한 기준선으로 유지합니다.
- 시스템 지시 문서는 `docs/system/`에, 사용자/협업용 설명 문서는 그 외 docs 하위 폴더에 둡니다.
