# Documentation Index

이 문서는 **운영·개발·튜토리얼용 설명 문서만** 정리합니다. 시스템 지시(코덱스 프롬프트/내부 실행 지침)는 `docs/system/`으로 분리해 두었습니다.

## 1) 설명용 폴더 맵 (실제 파일 기준)

- [`docs/agents`](agents)
  - `specimen_design_existing_runtime_guideline.txt`
  - `bo_agent_runtime_guideline.txt`
  - `vision_pickup_observation_runtime_guideline.txt`
  - `manipulation_pi05_transfer_runtime_guideline.txt`
  - `analysis_utm_runtime_guideline.txt`
  - `cae_analysis_runtime_guideline.txt`

- [`docs/gui`](gui)
  - `gui.md`
  - `live_gui_evolution_plan.md`

- [`docs/hardware`](hardware)
  - `printer_agent_prusabridge_phase1_runtime_guideline.txt`
  - `prusa_mk4s_live_validation_20260506.md`
  - `lerobot_robotis_manipulation_runtime_guideline.md`
  - `windows_pyautogui_bridge_windows_setup.md`
  - `windows_pyautogui_equipment_agent_guideline.md`

- [`docs/process`](process)
  - `codex_workflow.md`

- [`docs/project`](project)
  - `Project_guide.txt`

- [`docs/repository`](repository)
  - `github_version_control.md`

- [`docs/runtime`](runtime)
  - `autonomous_experiment_runtime.md`
  - `langgraph_runtime.md`
  - `agent_program_baseline.md`
  - `architecture.md`
  - `test_mode.md`
  - `logging.md`
  - `lerobot_dataset_policy_naming.md`
  - `self_evolution.md`

- [`docs/strategy`](strategy)
  - `low_cost_sdl_improvement_full_guideline.md`

- [`docs/tutorials`](tutorials)
  - `first_autonomous_run.md`
  - `first_autonomous_run.en.md`
  - `first_autonomous_run.ko.md`

- [`docs/ATR_Live_GUI_Graph_Package`](ATR_Live_GUI_Graph_Package) (실행 스펙 패키지)
  - `ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
  - `package_manifest.json`
  - `backend/runtime_event_types.py`
  - `frontend/design_tokens.css`
  - `frontend/component_map.json`
  - `schemas/runtime_event.schema.json`
  - `schemas/agent_report.schema.json`
  - `schemas/graph_config.schema.json`
  - `docs/UX_SPEC.md`
  - `docs/UI_SPEC.md`
  - `docs/BACKEND_API_SPEC.md`
  - `docs/GRAPH_INTEGRATION_SPEC.md`
  - `docs/PACKAGING_README.md`

- [`docs/ATR_LangGraph_Runtime_IDE_Codex_Package`](ATR_LangGraph_Runtime_IDE_Codex_Package) (런타임 IDE 구현 가이드 패키지)
  - `ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
  - `atr_langgraph_runtime_ide_assets/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
  - `atr_langgraph_runtime_ide_assets/README_ASSETS.md`
  - `atr_langgraph_runtime_ide_assets/icon_manifest.json`
  - `atr_langgraph_runtime_ide_assets/icons/*.svg`
  - `atr_langgraph_runtime_ide_assets/icons_png/*.png`

- [`docs/ATR_Self_Evolution_Package`](ATR_Self_Evolution_Package) (자율진화 가이드 패키지)
  - `ATR_Self_Evolution_Codex_Instructions.txt`
  - `package_manifest.json`
  - `backend/api_routes_reference.py`
  - `backend/self_evolution_models.py`
  - `docs/EVOLUTION_LAB_UI_SPEC.md`
  - `docs/EVOLUTION_SAFETY_POLICY.md`
  - `docs/HERMES_ADAPTATION_NOTES.md`
  - `docs/SELF_EVOLUTION_SPEC.md`
  - `frontend/evolution_lab_tokens.css`
  - `schemas/evolution_gate_result.schema.json`
  - `schemas/evolution_task.schema.json`
  - `schemas/evolution_trace.schema.json`
  - `schemas/evolution_variant.schema.json`

- [`docs/system`](system) (시스템 지시/프롬프트 전용)
  - `ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
  - `ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
  - `ATR_Self_Evolution_Codex_Instructions.txt`
  - `codex_lerobot_robotis_gui_prompt.txt`

- [`docs/lerobot_robotis_pre_research.md`](lerobot_robotis_pre_research.md)
  - Pre-research notes and Codex prompt dependency

## 2) 설명용 핵심 문서별 진입점

- [프로젝트 기본 가이드](project/Project_guide.txt): 전체 시스템 목적, 계약 변경 규칙, 단계/역할 정의
- [실행 계약](runtime/autonomous_experiment_runtime.md): 실험/장비 호출 인터페이스
- [LangGraph 런타임](runtime/langgraph_runtime.md): 그래프 계약, 노드/이벤트 스펙
- [에이전트 프로그램 베이스라인](runtime/agent_program_baseline.md)
- [Live GUI 설명](gui/gui.md): 운영 화면 구성과 동작 규칙
- [첫 실행 튜토리얼](tutorials/first_autonomous_run.en.md): 영문
- [첫 실행 튜토리얼](tutorials/first_autonomous_run.ko.md): 한글

## 3) 추천 읽기 순서 (운영자용)

1. [project/Project_guide.txt](project/Project_guide.txt)
2. [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md)
3. [runtime/autonomous_experiment_runtime.md](runtime/autonomous_experiment_runtime.md)
4. [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md)
5. 하드웨어 브릿지:
   - [hardware/lerobot_robotis_manipulation_runtime_guideline.md](hardware/lerobot_robotis_manipulation_runtime_guideline.md)
   - [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt)
6. [gui/live_gui_evolution_plan.md](gui/live_gui_evolution_plan.md)
7. [tutorials/first_autonomous_run.en.md](tutorials/first_autonomous_run.en.md) 또는 [tutorials/first_autonomous_run.ko.md](tutorials/first_autonomous_run.ko.md)

## 4) 시스템 지시 문서(필요 시만 사용)

- [`docs/system/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`](system/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt)
- [`docs/system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`](system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt)
- [`docs/system/ATR_Self_Evolution_Codex_Instructions.txt`](system/ATR_Self_Evolution_Codex_Instructions.txt)
- [`docs/system/codex_lerobot_robotis_gui_prompt.txt`](system/codex_lerobot_robotis_gui_prompt.txt)

**참고:** 패키지 폴더 안의 `*_Codex_Instructions` 파일은 해당 패키지 해석을 위한 버전 고정 가이드입니다.

## 5) 문서 유지 규칙

- 실행 계약/행동 규칙 변경은 `runtime/*` 또는 관련 `hardware/*`와 `agents/*`를 동시 갱신한다.
- GUI/런타임 기능 변경 시 `gui/live_gui_evolution_plan.md`, `runtime/langgraph_runtime.md`, `process/codex_workflow.md`를 함께 갱신한다.
- 패키지 적용 범위가 바뀌면 해당 패키지 `package_manifest.json`과 `docs/*`를 동기화한다.
