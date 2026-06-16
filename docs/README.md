# Documentation Index

이 문서는 협업자와 운영자가 읽는 설명용 문서의 진입점입니다. 시스템 지시, Codex 실행 프롬프트, 패키지 원본 지침은 `docs/system/`과 각 `docs/ATR_*_Package/`에 분리되어 있습니다.

## 1. 먼저 읽을 문서

| 목적 | 문서 |
|---|---|
| 전체 프로젝트 흐름 | [../README.ko.md](../README.ko.md), [../README.en.md](../README.en.md) |
| 초보자/상급자 통합 매뉴얼 | [tutorials/user_manual.ko.md](tutorials/user_manual.ko.md), [tutorials/user_manual.en.md](tutorials/user_manual.en.md) |
| 실제 닫힌 루프, 페이지, 에이전트 | [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| LangGraph 실행 계약 | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Guardian safety/alarm 계약 | [runtime/guardian_graphwide_safety.md](runtime/guardian_graphwide_safety.md) |
| Experiment API 계약 | [runtime/autonomous_experiment_runtime.md](runtime/autonomous_experiment_runtime.md) |
| Live GUI 운영 | [gui/gui.md](gui/gui.md) |
| Device Workspaces / 3DP 사용법 | [tutorials/device_workspace_3dp_usage.ko.md](tutorials/device_workspace_3dp_usage.ko.md) |
| BambuLab X2D bridge 구조 | [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md) |
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

3DP/Bambu 경로는 `SpecimenMakingAgent -> printer.prepare -> PrinterDeviceBridgeManager -> Bambu native G-code patch/start gate` 순서로 연결됩니다. 세부 구조는 [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md)에 정리되어 있습니다. BambuLab X2D가 기본 active provider이며, Prusa MK4S는 fallback이 아니라 operator가 선택하는 별도 provider입니다. Bambu의 MQTT publish ack는 실제 출력 시작과 분리해서 기록하며, fresh post-publish observation이 RUNNING/PREPARING 계열 상태로 넘어가지 않으면 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 차단합니다. Native autoejection은 `bambu_gcode_patch` provider로 sliced `.gcode.3mf` 내부 plate G-code에 deterministic tail을 삽입하고, source/patched hash, plate id, loop index, material/bed placeholder, cooldown, sweep, purge/parking strategy, validation evidence를 manifest와 tail comment에 남긴 뒤에만 start gate로 넘어갑니다. Bambu bridge evidence는 `artifact`, `validation`, `transport`, `runtime`, `bed-clear` 5개 plane으로 나뉘며, GUI/Live report/API는 이 구분을 유지해야 합니다. `.autoeject.*` publish가 성공하면 bed-clear evidence는 remote path, subtask, source/patched artifact path와 hash, manifest, publish sequence/topic, post-publish status, camera snapshot reference를 같이 잠그며, 다음 job은 이 evidence가 해제되기 전까지 차단됩니다. 물리 완료 선언 시에도 physical start precheck는 saved prestart snapshot에서 `ready_to_publish_not_started`, `published=false`, `will_publish=false`가 확인되어야 합니다. center standalone ejection, left/right lane ejection, disposable live ejection은 각각 saved `printer.bambu.start_publish` 응답 snapshot을 가져야 하며, snapshot의 `ready_to_publish=true`, `start_enabled=true`, blocker 없음, remote path, publish sequence/topic, post-publish running status가 proof 본문과 일치해야 합니다. disposable live ejection은 추가로 local source/patched artifact file의 sha256이 proof hash와 맞아야 합니다. left/right lane은 marker artifact와 saved validation snapshot도 모두 있어야 하고, post-ejection bed-clear는 `operator`, `camera`, `vision` 중 하나의 검증 방식과 live ejection의 source/patched sha256 매칭을 요구하고, next-job gate는 saved start-gate snapshot에서 `ready_to_publish=true`, `start_enabled=true`, blocker 없음, `BAMBU_POST_EJECT_BED_NOT_CLEAR` 없음이 확인되어야 합니다. 실제 motion은 `.autoeject.*` artifact 검증, camera/bed-clear evidence, Guardian/operator approval, ejection-path operator checklist를 모두 통과한 뒤에만 이어집니다. 물리 완료 선언은 별도 completion audit으로만 가능하며, `/api/printer/bambu-autoejection-proof-template`와 `/api/printer/bambu-autoejection-completion-audit` 또는 `scripts/audit_bambu_autoejection_completion.py`가 file-backed proof package를 검증해야 합니다.

시스템 설명 문서에서 3DP bridge를 설명할 때는 다음 세 계층을 섞지 않습니다.

- `개선안/14_bambulab_gcode_autoejection_runtime_plan.md`: Reddit/GitHub/YouTube/Bambu community 사례조사와 구현 기준을 고정하는 설계 문서
- `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`: 운영자/협업자에게 공개할 BambuLab X2D bridge runtime 설명
- `docs/gui`, `docs/runtime`, `docs/tutorials`: 실제 화면, API, closed-loop, 사용자 절차 설명

즉, 외부 사례의 G-code나 UI를 그대로 복사하지 않고, 검증된 원칙만 ATR의 provider/bridge/evidence 계약으로 재해석합니다.

시스템 설명 문서를 갱신할 때는 코드 파일만 나열하지 않고 runtime path, GUI route, device bridge gate, agent report evidence가 어떻게 이어지는지 같이 적어야 합니다. 특히 Bambu/3DP 변경은 `docs/runtime/closed_loop_and_pages_reference.md`, `docs/gui/gui.md`, `docs/tutorials/device_workspace_3dp_usage.ko.md`, `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`가 같은 의미로 맞아야 합니다.

## 3. 페이지별 문서 맵

| 페이지 | URL | 코드 | 설명 문서 |
|---|---|---|---|
| Main GUI | `/` | `web/templates/index.html`, `web/static/app.js` | [gui/gui.md](gui/gui.md) |
| Live GUI | `/live`, `/planning` | `web/templates/planning.html`, `web/static/planning.js` | [gui/gui.md](gui/gui.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| Runtime IDE | `/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Module Management | `/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md) |
| 3DP Workspace | `/printer` | `web/templates/printer.html`, `web/static/printer.js`, `device_bridges/bambu_bridge.py`, `device_bridges/bambu_autoejection.py` | [gui/gui.md](gui/gui.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md), [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md), [../개선안/13_bambulab_x2d_spc_device_bridge_research.md](../개선안/13_bambulab_x2d_spc_device_bridge_research.md), [../개선안/14_bambulab_gcode_autoejection_runtime_plan.md](../개선안/14_bambulab_gcode_autoejection_runtime_plan.md), [tutorials/device_workspace_3dp_usage.ko.md](tutorials/device_workspace_3dp_usage.ko.md), [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| LeRobot Workspace | `/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | [hardware/lerobot_robotis_manipulation_runtime_guideline.md](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| BO Workspace | `/bo` | `web/templates/bo.html`, `web/static/bo.js` | [agents/bo_agent_runtime_guideline.txt](agents/bo_agent_runtime_guideline.txt) - BO/MBO/LLM preference 설정, lightweight/BoTorch optional backend, reasoning audit, candidate ranking |
| CAE Workspace | `/cae` | `web/templates/cae.html`, `web/static/cae.js` | [agents/cae_analysis_runtime_guideline.txt](agents/cae_analysis_runtime_guideline.txt) |
| Windows Equipment | `/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | [hardware/windows_pyautogui_equipment_agent_guideline.md](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Self-Evolution Lab | `/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | [runtime/self_evolution.md](runtime/self_evolution.md), [agents/knowledge_agent_self_evolution_runtime_guideline.md](agents/knowledge_agent_self_evolution_runtime_guideline.md), [runtime/knowledge_graphify_graph_backend_plan.md](runtime/knowledge_graphify_graph_backend_plan.md) |

## 4. 에이전트별 문서 맵

| Agent | Runtime module | 문서 |
|---|---|---|
| Design | `graphs/modules/design` | [agents/specimen_design_existing_runtime_guideline.txt](agents/specimen_design_existing_runtime_guideline.txt) |
| Specimen Making | `graphs/modules/specimen` | [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md), [../개선안/13_bambulab_x2d_spc_device_bridge_research.md](../개선안/13_bambulab_x2d_spc_device_bridge_research.md), [../개선안/14_bambulab_gcode_autoejection_runtime_plan.md](../개선안/14_bambulab_gcode_autoejection_runtime_plan.md), [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| Vision | `graphs/modules/vision` | [agents/vision_pickup_observation_runtime_guideline.txt](agents/vision_pickup_observation_runtime_guideline.txt) |
| Manipulation | `graphs/modules/manipulation` | [agents/manipulation_pi05_transfer_runtime_guideline.txt](agents/manipulation_pi05_transfer_runtime_guideline.txt) |
| Lab Equipment | `graphs/modules/equipment` | [hardware/windows_pyautogui_equipment_agent_guideline.md](hardware/windows_pyautogui_equipment_agent_guideline.md), [hardware/lab_equipment_utm_visual_control_completion_audit.md](hardware/lab_equipment_utm_visual_control_completion_audit.md) |
| Analysis | `graphs/modules/analysis` | [agents/analysis_utm_runtime_guideline.txt](agents/analysis_utm_runtime_guideline.txt), [agents/cae_analysis_runtime_guideline.txt](agents/cae_analysis_runtime_guideline.txt), [agents/fenicsx_analysis_runtime_assets.md](agents/fenicsx_analysis_runtime_assets.md) |
| Knowledge | `graphs/modules/knowledge` | [agents/knowledge_agent_self_evolution_runtime_guideline.md](agents/knowledge_agent_self_evolution_runtime_guideline.md), [runtime/self_evolution.md](runtime/self_evolution.md), [runtime/knowledge_graphify_graph_backend_plan.md](runtime/knowledge_graphify_graph_backend_plan.md) |
| BO | `graphs/modules/bo` | [agents/bo_agent_runtime_guideline.txt](agents/bo_agent_runtime_guideline.txt) |
| Guardian | `graphs/modules/guardian` | [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md), [runtime/guardian_graphwide_safety.md](runtime/guardian_graphwide_safety.md) |

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
| `memory/` | 로컬 설정, 장비 연결 정보, graph/module version memory, Knowledge JSONL memory |
| `runs/` | 실행별 로그와 아티팩트 |
| `artifacts/` | STL, G-code, CAE, UI audit 등 산출물 |
| `tests/` | pytest, integration, UI audit |
| `scripts/` | live 검증 runner와 운영 보조 스크립트. 예: `lab_equipment_live_utm_validation.py`, `audit_lab_equipment_utm_completion.py`, `audit_bambu_autoejection_completion.py` |
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
- Knowledge memory/evidence schema나 Evolution Lab prefill을 바꾸면 `agents/knowledge_agent_self_evolution_runtime_guideline.md`와 `runtime/self_evolution.md`를 같이 갱신합니다.
- GUI route/버튼/API가 바뀌면 `gui/gui.md`와 이 인덱스의 페이지 맵을 같이 갱신합니다.
- agent module 계약이 바뀌면 해당 `docs/agents/*` 또는 `docs/hardware/*`를 같이 갱신합니다.
- 설치 의존성이 바뀌면 루트 [REQUIREMENTS.md](../REQUIREMENTS.md)를 갱신합니다.
