# Documentation Index

이 문서는 협업자와 운영자가 읽는 설명용 문서의 진입점입니다. 시스템 지시, Codex 실행 프롬프트, 패키지 원본 지침은 `docs/system/`과 각 `docs/ATR_*_Package/`에 분리되어 있습니다.

## 1. 먼저 읽을 문서

| 목적 | 문서 |
|---|---|
| 전체 프로젝트 흐름 | [../README.ko.md](../README.ko.md), [../README.en.md](../README.en.md) |
| 초보자/상급자 통합 매뉴얼 | [tutorials/user_manual.ko.md](tutorials/user_manual.ko.md), [tutorials/user_manual.en.md](tutorials/user_manual.en.md) |
| 실제 닫힌 루프, 페이지, 에이전트 | [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| LangGraph 실행 계약 | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Experiment API 계약 | [runtime/autonomous_experiment_runtime.md](runtime/autonomous_experiment_runtime.md) |
| Live GUI 운영 | [gui/gui.md](gui/gui.md) |
| 첫 실행 튜토리얼 | [tutorials/first_autonomous_run.ko.md](tutorials/first_autonomous_run.ko.md), [tutorials/first_autonomous_run.en.md](tutorials/first_autonomous_run.en.md) |
| Git/GitHub 운영 | [repository/github_version_control.md](repository/github_version_control.md) |

## 2. 실제 런타임 구조 요약

기본 그래프는 `graphs/configs/atr_closed_loop.yaml`이며, 서버 route는 `app/main.py`에 정의되어 있습니다.

```text
Main GUI -> Live GUI -> /api/run/start -> LangGraphRunLoop
        -> design -> specimen -> vision -> manipulation -> equipment
        -> analysis -> knowledge -> bo -> guardian
        -> continue: design / stop: complete / error: error
```

Live GUI에서 보이는 상태는 다음 소스에서 옵니다.

- `/api/planning/session`: 채팅/오케스트레이션 세션
- `/api/runtime/state`: 현재 runtime 상태
- `/api/events/recent`: 최근 이벤트
- `/api/events/stream`: SSE stream
- `/api/runs/{run_id}/events`: run별 이벤트
- `/api/runs/{run_id}/artifacts`: run별 아티팩트

## 3. 페이지별 문서 맵

| 페이지 | URL | 코드 | 설명 문서 |
|---|---|---|---|
| Main GUI | `/` | `web/templates/index.html`, `web/static/app.js` | [gui/gui.md](gui/gui.md) |
| Live GUI | `/live`, `/planning` | `web/templates/planning.html`, `web/static/planning.js` | [gui/gui.md](gui/gui.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| Runtime IDE | `/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Module Management | `/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md) |
| 3DP Workspace | `/printer` | `web/templates/printer.html`, `web/static/printer.js` | [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| LeRobot Workspace | `/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | [hardware/lerobot_robotis_manipulation_runtime_guideline.md](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| BO Workspace | `/bo` | `web/templates/bo.html`, `web/static/bo.js` | [agents/bo_agent_runtime_guideline.txt](agents/bo_agent_runtime_guideline.txt) |
| CAE Workspace | `/cae` | `web/templates/cae.html`, `web/static/cae.js` | [agents/cae_analysis_runtime_guideline.txt](agents/cae_analysis_runtime_guideline.txt) |
| Windows Equipment | `/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | [hardware/windows_pyautogui_equipment_agent_guideline.md](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Self-Evolution Lab | `/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | [runtime/self_evolution.md](runtime/self_evolution.md) |

## 4. 에이전트별 문서 맵

| Agent | Runtime module | 문서 |
|---|---|---|
| Design | `graphs/modules/design` | [agents/specimen_design_existing_runtime_guideline.txt](agents/specimen_design_existing_runtime_guideline.txt) |
| Specimen Making | `graphs/modules/specimen` | [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| Vision | `graphs/modules/vision` | [agents/vision_pickup_observation_runtime_guideline.txt](agents/vision_pickup_observation_runtime_guideline.txt) |
| Manipulation | `graphs/modules/manipulation` | [agents/manipulation_pi05_transfer_runtime_guideline.txt](agents/manipulation_pi05_transfer_runtime_guideline.txt) |
| Lab Equipment | `graphs/modules/equipment` | [hardware/windows_pyautogui_equipment_agent_guideline.md](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Analysis | `graphs/modules/analysis` | [agents/analysis_utm_runtime_guideline.txt](agents/analysis_utm_runtime_guideline.txt), [agents/cae_analysis_runtime_guideline.txt](agents/cae_analysis_runtime_guideline.txt) |
| Knowledge | `graphs/modules/knowledge` | [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md) |
| BO | `graphs/modules/bo` | [agents/bo_agent_runtime_guideline.txt](agents/bo_agent_runtime_guideline.txt) |
| Guardian | `graphs/modules/guardian` | [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md) |

## 5. 폴더별 책임

| 폴더 | 책임 |
|---|---|
| `app/` | FastAPI route, runtime API, controller 연결 |
| `web/` | HTML/CSS/JS 기반 GUI |
| `graphs/` | LangGraph YAML, compiler/validator, module registry |
| `graphs/modules/` | 각 stage agent의 실행 계약과 handler |
| `device_bridges/` | 프린터, 로봇, Windows, UTM 등 외부 장비 연결 |
| `experiments/` | objective/evaluate/benchmark/queue 공통 실험 API |
| `orchestrator/` | Live planning, handoff, 오케스트레이션 로직 |
| `backends/` | Ollama/vLLM/Nemoclaw LLM 연결 |
| `self_evolution/` | variant 생성, 검증, 승인, rollback |
| `memory/` | 로컬 설정, 장비 연결 정보, graph/module version memory |
| `runs/` | 실행별 로그와 아티팩트 |
| `artifacts/` | STL, G-code, CAE, UI audit 등 산출물 |
| `tests/` | pytest, integration, UI audit |
| `install/` | CLI 설치와 외부 프로그램 설치 보조 |
| `image/` | 발표/논문용 시스템 diagram prompt와 렌더 결과 |
| `user_files/` | 사용자가 넣는 데이터/작업 파일 |

## 6. 설명용 문서 폴더

- `docs/runtime/`: runtime, graph, loop, logging, test mode, self-evolution 설명
- `docs/gui/`: GUI 사용/개선 계획
- `docs/agents/`: agent별 역할과 runtime guideline
- `docs/hardware/`: 장비 브릿지와 실제 장비 연동
- `docs/tutorials/`: 사용자 종합 매뉴얼과 첫 실행 튜토리얼
- `docs/repository/`: GitHub/버전관리 규칙
- `docs/process/`: Codex 작업 절차
- `docs/project/`: 프로젝트 기본 가이드
- `docs/strategy/`: 시스템 개선 전략

## 7. 시스템 지시 문서

일반 협업자는 보통 아래 파일을 직접 수정하지 않습니다. Codex/패키지 적용 기준으로 분리된 자료입니다.

- `docs/system/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
- `docs/system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
- `docs/system/ATR_Self_Evolution_Codex_Instructions.txt`
- `docs/system/codex_lerobot_robotis_gui_prompt.txt`
- `docs/ATR_Live_GUI_Graph_Package/`
- `docs/ATR_LangGraph_Runtime_IDE_Codex_Package/`
- `docs/ATR_Self_Evolution_Package/`

## 8. 문서 유지 규칙

- runtime loop나 API를 바꾸면 `runtime/closed_loop_and_pages_reference.md`를 같이 갱신합니다.
- GUI route/버튼/API가 바뀌면 `gui/gui.md`와 이 인덱스의 페이지 맵을 같이 갱신합니다.
- agent module 계약이 바뀌면 해당 `docs/agents/*` 또는 `docs/hardware/*`를 같이 갱신합니다.
- 설치 의존성이 바뀌면 루트 [REQUIREMENTS.md](../REQUIREMENTS.md)를 갱신합니다.
