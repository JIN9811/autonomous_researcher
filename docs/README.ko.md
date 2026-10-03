<!-- atr-doc
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - user
  - operator
  - developer
  - researcher
scope:
  - repository_documentation
summary: 설치부터 실험, 복구, 결과 확인, 기능 확장까지 작업별로 안내하는 한국어 문서 시작점.
related_docs:
  - docs/README.md
  - README.ko.md
  - docs/tutorials/first_autonomous_run.ko.md
  - docs/tutorials/user_manual.ko.md
  - docs/runtime/runtime_ide.md
supersedes: []
-->

# AX4LAB 사용 안내

[English](README.md) · [프로젝트 소개](../README.ko.md)

하려는 작업에 맞는 안내부터 읽으면 됩니다. 첫 실험을 시작하기 위해
모듈 계약이나 논문 전체를 먼저 읽을 필요는 없습니다.

## 처음 사용한다면

1. [설치 안내](../install/README.md)에 따라 AX4LAB을 설치하고 화면을 엽니다.
2. [첫 실험 튜토리얼](tutorials/first_autonomous_run.ko.md)을 따라 실행 모드를
   고르고, 필요한 장비를 준비한 뒤 실험 설정을 검토합니다. 실행 승인부터
   결과 확인까지 이어서 설명합니다.
3. 다음 실험부터는 [사용 설명서](tutorials/user_manual.ko.md)에서 필요한
   작업을 찾아보세요. 화면 위치가 헷갈리면 [GUI 둘러보기](gui/visual_structure.md)를
   함께 보세요.

**장비를 준비하기 전에 실행 모드를 확인하세요.** TEST라고 해서 장비가
움직이지 않는 것은 아닙니다. Virtual Bridge, Installed Printer, Physical
Printing은 실제로 수행하는 동작이 다릅니다. 튜토리얼에서 차이를 먼저
살펴보고, 세부 기준은 [실행 모드 안내](runtime/test_mode.md)를 참고하세요.

## 무엇을 하려 하나요?

| 하려는 일 | 읽을 문서 |
|---|---|
| 외부 API 또는 로컬 모델 설정 | [모델과 API 키 설정](runtime/api_keys.md) |
| 슬라이싱, 시편 위치, 출력 옵션 변경 | [3DP 워크스페이스](tutorials/device_workspace_3dp_usage.ko.md) |
| 관측 카메라 연결 및 이미지 확인 | [Vision Camera Bridge](tutorials/device_workspace_vision_camera_bridge_usage.ko.md) |
| 로봇 동작 녹화, 학습, 정책 실행 | [LeRobot 워크스페이스와 실행 경로](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Windows 장비 PC 연결 | [Windows 브릿지 설치](hardware/windows_pyautogui_bridge_windows_setup.md), [장비 운용](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| 현재 실험 단계와 에이전트 카드 확인 | [Live GUI](gui/gui.md) |
| 참고 문서 등록 및 저장된 지식 확인 | [Source Library](knowledge/manual_rag_knowledge.ko.md), [메모리 관리](knowledge/markdown_memory_operations.ko.md) |
| 모듈 추가 또는 실험 구성 변경 | [모듈화](modularity.md), [Runtime IDE](runtime/runtime_ide.md), [패키지](../packages/README.md) |

워크스페이스는 장비를 직접 설정하고 다루는 화면입니다. 여기서 수동으로
한 동작이 실험의 해당 단계를 자동으로 완료시키지는 않습니다. 현재 런의
근거와 다음 단계로 넘어간 상태는 Live GUI에서 확인하세요.

## 실험이 멈추거나 확인을 요청한다면

이전 오류 문구보다는 지금 보이는 증상에 맞는 안내를 선택하세요.

| 상황 | 읽을 문서 |
|---|---|
| 일시정지하거나 중단된 런을 이어가야 함 | [Resume과 복구](gui/run_resume.md) |
| 프린터는 출력 중인데 대기 상태가 갱신되지 않음 | [출력 대기 복구](gui/printer_wait_recovery.md) |
| 카메라 이미지는 왔지만 판정이 끝나지 않음 | [비전 판정 복구](gui/vision_review_recovery.md) |
| 장비 워크플로의 선택값이 없거나 잘못됨 | [장비 선택 복구](gui/equipment_selection_recovery.md) |
| 장비 오류 알림이 계속 남아 있음 | [장비 알림 상태](gui/hardware_alert_lifecycle.md) |

재시도하기 전에는 실제 동작이 이미 실행됐는지 확인해야 합니다.
응답을 못 받았다는 이유만으로 프린터, 로봇, 시험기가 아무 일도 하지
않았다고 판단하면 안 됩니다. 각 복구 안내에서 기록으로 확인할 수 있는
부분과 사람이 확인해야 하는 부분을 구분합니다.

## 결과와 이전 사이클 보기

에이전트별 저장 파일은 **Artifacts**, 완료된 사이클의 파일은 **Loop
Artifacts**에서 확인합니다. [아티팩트 보관 안내](runtime/loop_artifact_archiving.md)는
런·사이클·에이전트·호출별로 파일을 구분하는 방법과 저장이 덜 끝난 상태를
설명합니다.

[Replay](gui/run_replay.md)는 저장된 세션을 읽기 전용으로 다시 보는
화면입니다. 녹화된 로봇 동작을 실제로 실행하는 **robot replay**와는 다릅니다.
런 이름, 시간, 이벤트 파일, 진단 메시지는 [로그 안내](runtime/logging.md)를
참고하세요.

연구 결과를 읽으려면 [연구 개요](paper/README.md)에서 시작해
[결과](paper/06_evaluation_and_results.md), [재현 방법](paper/07_reproducibility.md),
[주장과 근거의 대응표](paper/09_claim_evidence_traceability.md)로 이어가면 됩니다.
보존된 캠페인에는 **완료된 관측 결과 15개**가 있습니다. 이를 중단이나
사람의 개입 없이 15회 연속 수행한 실험으로 해석해서는 안 됩니다.
[캠페인 감사 기록](paper/evidence/2026-09-28-campaign-archive-audit.md)에 근거와
한계가 정리되어 있습니다. [이전 감독하 실험](paper/evidence/2026-09-07-supervised-closed-loop.md)의
혼합 모드와 시편 식별 한계도 별도로 남겨 두었습니다.

## 화면별 안내

| 화면 | 주소 경로 | 안내 |
|---|---|---|
| Main GUI | `/` | [사용 설명서](tutorials/user_manual.ko.md) |
| Live GUI | `/live`, `/planning` | [Live GUI](gui/gui.md) |
| Replay | `/replay` | [다시보기](gui/run_replay.md) |
| Runtime IDE | `/ide` | [Runtime IDE](runtime/runtime_ide.md) |
| Module Management | `/module-management` | [모듈화](modularity.md) |
| Knowledge | `/knowledge` | [Wiki와 메모리](knowledge/wiki_memory.md) |
| 3DP | `/printer` | [3DP 워크스페이스](tutorials/device_workspace_3dp_usage.ko.md) |
| Vision Camera Bridge | `/device-bridge/vision-utm` | [카메라 워크스페이스](tutorials/device_workspace_vision_camera_bridge_usage.ko.md) |
| LeRobot | `/lerobot` | [로봇 워크스페이스](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| BO | `/bo` | [BO 설명](agents/bo_agent.md) |
| Windows Equipment | `/equipment/windows` | [장비 운용](hardware/windows_pyautogui_equipment_agent_guideline.md) |

영문으로만 제공되는 세부 기술 문서는 그대로 연결했습니다. 한국어 본문에
영어 설명을 섞어 놓는 대신, 화면의 실제 버튼명과 전문 용어만 원문으로
유지합니다.

## 구조를 이해하거나 기능을 확장하려면

전체 구성은 [시스템 아키텍처](paper/02_system_architecture.md)에서 설명합니다.
구현 세부 사항이 필요할 때 담당 문서를 찾아보세요.

- [에이전트 목록](agents/README.md)과 [연결표](agents/agent_api_connection_matrix.md):
  각 에이전트의 역할, 도구, 전달하는 정보와 완료 근거.
- [장비 브릿지 목록](device_bridges/README.md)과 [연결표](device_bridges/bridge_api_connection_matrix.md):
  지원 기능, 통신 방식, 실제 동작의 경계.
- [Runtime IDE](runtime/runtime_ide.md), [모듈화](modularity.md), [패키지](../packages/README.md):
  모듈을 살펴보고 조합하는 방법. 패키지 불러오기, 모듈 적용, 그래프 활성화,
  실험 실행은 서로 다른 작업입니다.
- [런타임 개요](runtime/current_code_snapshot.md), [제어 계층](runtime/three_level_control_model.md),
  [그래프 런타임](runtime/langgraph_runtime.md), [실험 경로](runtime/closed_loop_and_pages_reference.md),
  [실험 API](runtime/autonomous_experiment_runtime.md): 연동 개발에 필요한 세부 기준.
- [참고 문서의 권한 경계](knowledge/runtime_reference_safety.md)와
  [공개 자료 관리](knowledge/publication.md): 문서·비공개 기록·실행 권한의 구분.

## 문서 읽을 때 알아둘 점

가이드는 작업 방법, 레퍼런스는 구현 규칙, 근거 보고서는 특정 시점의 확인
결과를 설명합니다. 계획안이나 [과거 문서](oldversion/README.md)를 현재의
운용 지침으로 사용하면 안 됩니다.

문서를 수정하려면 [작성 기준](standards/documentation_standard.md),
[템플릿](templates/document_types.md), [논문 문서 기준](standards/paper_documentation_standard.md)을
확인하세요. [문서 목록](document_manifest.yaml)은 형식 검사를 받는 문서의
목록이며 저장소 전체 파일 목록은 아닙니다.
[문서별 검토 기록](maintenance/documentation_review_20260929.md)과
[코드 대조 기록](maintenance/code_documentation_audit_20260928.md)은 당시의 확인
범위를 그대로 유지합니다.

런 데이터, 인증 정보, 비공개 메모리는 공개 검토를 거치기 전까지 로컬 자료입니다.
문서에서 연결했다고 공개되는 것은 아닙니다. 문장을 다듬거나 링크를 확인한
작업도 새 장비 시험이나 실험 검증을 의미하지 않습니다.
