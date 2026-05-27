# Documentation Index

이 문서는 문서 위치를 빠르게 찾기 위한 항목별 인덱스입니다.

## 1. 프로젝트 기초

- [`project/Project_guide.txt`](project/Project_guide.txt)
  - 전체 시스템 목적, 실행 흐름, 단계별 범위.
- [`README.md` (root)](/home/jin/autonomous_researcher/README.md)
  - 실행 가이드와 전체 문서 맵으로 이동되는 진입점.

## 2. 런타임/실행 계약

- [`runtime/autonomous_experiment_runtime.md`](runtime/autonomous_experiment_runtime.md)
  - 실험/장비 실행 표준 인터페이스 (`experiment.evaluate`, `experiment.benchmark`, 큐/세션 계약).
- [`runtime/langgraph_runtime.md`](runtime/langgraph_runtime.md)
  - LangGraph 실행기, 그래프/모듈 계약, 이벤트 스키마, 안전성 게이트.
- [`runtime/agent_program_baseline.md`](runtime/agent_program_baseline.md)
  - 에이전트 모듈/도구 연동 기본 규약.
- [`runtime/architecture.md`](runtime/architecture.md)
  - 시스템 하위 구조 개요(컨트롤러, 런타임, 장비 브릿지, 추적 데이터).
- [`runtime/test_mode.md`](runtime/test_mode.md)
  - 테스트/가상/리플레이 동작 정의.
- [`runtime/logging.md`](runtime/logging.md)
  - 추적 로그와 이벤트 구조.
- [`runtime/lerobot_dataset_policy_naming.md`](runtime/lerobot_dataset_policy_naming.md)
  - LeRobot 데이터셋/정책 명명 규칙(파이프라인 정합성 유지).

## 3. 에이전트 가이드

- [`agents/specimen_design_existing_runtime_guideline.txt`](agents/specimen_design_existing_runtime_guideline.txt)
- [`agents/bo_agent_runtime_guideline.txt`](agents/bo_agent_runtime_guideline.txt)
- [`agents/vision_pickup_observation_runtime_guideline.txt`](agents/vision_pickup_observation_runtime_guideline.txt)
- [`agents/manipulation_pi05_transfer_runtime_guideline.txt`](agents/manipulation_pi05_transfer_runtime_guideline.txt)
- [`agents/analysis_utm_runtime_guideline.txt`](agents/analysis_utm_runtime_guideline.txt)
- [`agents/cae_analysis_runtime_guideline.txt`](agents/cae_analysis_runtime_guideline.txt)

## 4. 하드웨어/브릿지

- [`hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt)
- [`hardware/prusa_mk4s_live_validation_20260506.md`](hardware/prusa_mk4s_live_validation_20260506.md)
- [`hardware/lerobot_robotis_manipulation_runtime_guideline.md`](hardware/lerobot_robotis_manipulation_runtime_guideline.md)
- [`hardware/windows_pyautogui_equipment_agent_guideline.md`](hardware/windows_pyautogui_equipment_agent_guideline.md)
- [`hardware/windows_pyautogui_bridge_windows_setup.md`](hardware/windows_pyautogui_bridge_windows_setup.md)
- [`codex_lerobot_robotis_gui_prompt.txt`](codex_lerobot_robotis_gui_prompt.txt)

## 5. GUI/운영 화면

- [`gui/gui.md`](gui/gui.md)
  - 페이지 구조와 운영 화면 공통 규칙.
- [`gui/live_gui_evolution_plan.md`](gui/live_gui_evolution_plan.md)
  - Live GUI 진화 항목과 검수 이력.
- [`runtime/agent_program_baseline.md`](runtime/agent_program_baseline.md)
  - 에이전트 메시지/리포트 렌더링이 반영되는 실행 계약.

## 6. 설치 및 실행

- [`../install/README.md`](../install/README.md)
  - `atr` CLI 설치 및 실행/종료 스크립트.
- [`REQUIREMENTS.md`](/home/jin/autonomous_researcher/REQUIREMENTS.md)
  - 비파이썬 의존성, 외부 서비스, 장비 전제 조건.

## 7. 워크플로우/튜토리얼

- [`tutorials/first_autonomous_run.md`](tutorials/first_autonomous_run.md)
  - 첫 번째 운영 실행 가이드.
- [`process/codex_workflow.md`](process/codex_workflow.md)
  - Codex 기반 개발 절차와 변경 관리 방식.
- [`docs` 패키지 가이드 문서]
  - `docs/strategy/low_cost_sdl_improvement_full_guideline.md`
  - `docs/project/...` 하위 문서

## 8. 확장/연구 지점

- [`ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`](/home/jin/autonomous_researcher/docs/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt)
- [`ATR_LangGraph_Runtime_IDE_Codex_Package/...`](ATR_LangGraph_Runtime_IDE_Codex_Package)
- [`ATR_Self_Evolution_Codex_Instructions.txt`](/home/jin/autonomous_researcher/docs/ATR_Self_Evolution_Codex_Instructions.txt)
- [`ATR_Self_Evolution_Package/...`](ATR_Self_Evolution_Package)
- [`repository/github_version_control.md`](repository/github_version_control.md)

## 권장 읽기 순서 (운영자용)

1. `project/Project_guide.txt`
2. `runtime/langgraph_runtime.md`
3. `runtime/autonomous_experiment_runtime.md`
4. `runtime/agent_program_baseline.md`
5. `hardware/lerobot_robotis_manipulation_runtime_guideline.md` 또는 `hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`
6. `gui/live_gui_evolution_plan.md`
7. `tutorials/first_autonomous_run.md`

## 문서 유지 규칙

- 실행 계약/행동 변경은 반드시 `runtime/*`에 반영하고,
  브릿지별 하드웨어 동작 변경은 해당 `hardware/*` 문서도 함께 업데이트합니다.
- 실험/워크플로우 규칙 변경 시 먼저 `tutorials` 또는 `process`를 갱신합니다.
- 패키지 기반 가이드(`ATR_*_Package`, `Strategy`)는 ATR 적용 범위를 명시하고, 동작 문서와 충돌 시 실행 문서를 기준으로 합니다.
