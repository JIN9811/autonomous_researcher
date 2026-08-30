---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, operator, developer, maintainer]
scope: [agents, equipment, pyautogui, equipment_runtime, vision_link]
summary: Canonical Lab Equipment Agent contract using one Linux-owned Equipment Runtime and bounded local or Windows workers.
source_of_truth:
  - agents/equipment_agent.py
  - utils/equipment_runtime_service.py
  - utils/equipment_profiles.py
  - utils/equipment_skill_runtime.py
  - device_bridges/windows_pyautogui_bridge.py
  - mcp_tools/equipment_tools.py
last_verified: 2026-08-27
verified_against: working-tree-2026-08-27
related_docs:
  - docs/device_bridges/windows_pyautogui_bridge.md
  - docs/hardware/windows_pyautogui_equipment_agent_guideline.md
  - docs/strategy/2026-08-27-windows-lab-equipment-consolidation-report.md
---

# Lab Equipment Agent Reference

## 역할

`LabEquipmentAgent`는 저자동화·반자동화 PC 제어 장비의 실험 단계를 소유합니다. UTM은 현재 등록된 첫 Equipment Profile이며 Agent 본체의 고정 장비가 아닙니다.

Agent는 정확한 Profile/Skill/program을 선택하고 Linux `EquipmentRuntimeService`에 실행을 등록합니다. Windows 또는 Local Bridge는 선택된 프로그램을 결정론적으로 실행하고 원시 증거만 반환합니다. 완료 판정과 Analysis handoff는 Linux에서 한 번만 수행합니다.

## 세 단계 제어

| 제어 수준 | 책임 | 구현 경계 |
|---|---|---|
| High-Level | Equipment 단계 진입/종료, Profile/Skill 선택, 제한적 LLM 복구, 재시도·정지·handoff 결정 | `LabEquipmentAgent` |
| Middle-Level | 실행 ID, worker, 모드, 증거, 완료 판정, 상태 저장과 projection | `EquipmentRuntimeService`, Profile/Skill runtime |
| Low-Level | PyAutoGUI 입력, 창/locator 확인, 화면 캡처, 녹화, 파일과 원시 결과 반환 | Windows/Local Bridge |

Device Workspace는 수동 개발·설정·검증 화면이며 자동 실험 루프의 별도 제어 원본이 아닙니다.

## 유일한 자동 실행 경로

```text
LangGraph Equipment stage
  -> LabEquipmentAgent.run()
  -> EquipmentRuntimeService execution record
  -> equipment.pyautogui.run
  -> selected Windows or Local worker
  -> raw evidence
  -> one Linux completion interpretation
  -> Analysis handoff or explicit block
```

PyAutoGUI tool 부재를 이유로 `utm.run_protocol`에 자동 fallback하지 않습니다. native UTM이 필요하면 별도 provider를 가진 명시적 Profile로 등록해야 합니다.

## Profile과 Skill

Profile은 다음을 선언합니다.

- `profile_id`, label, provider
- 허용 program ID와 기본 program
- 모드별 worker payload
- 필요한 locator/evidence
- 선택적 `vision_link`
- completion interpreter
- manual knowledge scope

Skill은 Linux `memory/equipment_skills/`가 원본입니다. Windows에는 검증된 배포 캐시 또는 로컬 초안만 존재합니다.

```text
record -> transfer -> annotate -> edit/save -> deploy[compile + validate + transfer] -> execute
```

`annotate`는 전체 2 FPS 원본을 한 요청에 적재하지 않습니다. Linux가 16 frame 4x4 스토리보드를 만들고 청크별 상태 변화를 순차 분석한 후 전체 workflow를 합성합니다. Overview 스토리보드는 GUI와 감사용으로 보존하고, 최종 합성에는 순서가 보존된 청크 분석과 아직 분석되지 않은 action locator 이미지만 전달해 동일한 고해상도 상태 프레임을 중복 전송하지 않습니다. 청크 진행 상태는 `ANALYZING_TIMELINE`, 최종 합성은 `SYNTHESIZING`으로 작업 기록과 GUI에 표시됩니다. 정상 실행에는 LLM을 사용하지 않습니다. 녹화 분석과 선언된 복구 상황에서만 현재 선택된 Local/API 모델을 Linux에서 사용합니다.

Skill Workflow Editor는 정확한 `skill_id@version`의 `workflow.json`만 수정하는
순차 편집기입니다. 일반 장비 macro의 실행 순서를 명확하게 유지하기 위해 IF,
loop, 병렬 edge, 사용자 Python을 받지 않습니다. `Timer wait`는 고정 시간을,
`Image/Text/File until wait`는 polling interval과 timeout을 갖는 bounded wait를
표현합니다. 저장하면 이전 compiled program과 validation 결과를 무효화합니다.
GUI의 단일 `Deploy`는 compile, validate, worker transfer/register를 순서대로 수행하며
Skill을 실행하지 않습니다. 배포 또는 비활성화된 정확 버전은 불변이므로 수정하려면
새 버전을 생성해야 합니다. 독립 compile/validate API는 CLI 호환용으로만 유지합니다.

이미지 기반 action의 `Edit Crop`은 hash가 검증된 pre-action 원본 프레임에서
Target ROI만 이동하거나 리사이즈합니다. AI가 만든 최초 ROI는 `Reset to AI` 기준으로
보존되고 Context ROI와 두 번째 locator candidate는 변경하지 않습니다. `Apply Crop`은
편집기 로컬 상태만 바꾸며 `Save` 시 workflow와 annotation을 함께 갱신하고 기존
compiled/validated 산출물을 무효화합니다. `Replace Locator`는 원본 ROI를 조정하는
기능이 아니라 locator PNG 자체를 외부 파일로 교체하는 별도 작업입니다.

## Vision Link

`vision_link.enabled=false`인 Profile은 화면·파일·장비 상태만으로 실행합니다. 활성 Profile은 다음 중 하나를 요구합니다.

1. identity와 freshness가 유효한 기존 Vision evidence
2. 호출 가능한 `vision.equipment_cross_check` tool

둘 다 없으면 `EQUIPMENT_VISION_LINK_UNAVAILABLE`로 실행 전 차단합니다. Vision tool이 있으나 필수 관측 결과가 없으면 UTM 등 해당 Profile의 세부 evidence failure code를 반환합니다. Vision은 관측만 제공하며 장비 입력을 직접 제어하지 않습니다.

## 통합 실행 기록

`EquipmentExecutionRecord`는 다음 식별자를 보존합니다.

- `execution_id`, `sequence_id`
- `run_id`, `experiment_id`, `specimen_id`
- Profile, Skill/program, worker, mode
- event history, raw result, evidence
- completion, failure, recovery, handoff

상태 이름과 전이는 Profile/Skill/provider 계약에 따라 달라질 수 있습니다. `RESOLVING`, `PREFLIGHT`, `EXECUTING`, `VERIFYING`, `COMPLETED`, `BLOCKED` 등은 대표적인 Equipment 상태이지 모든 모듈에 강제되는 전역 수명주기가 아닙니다.

Live GUI, Equipment Workspace, CUI, Runtime IDE는 이 기록의 같은 projection을 읽습니다. Live GUI는 현재 `run_id`로 `/api/equipment/runtime/current`를 조회하므로 다른 실험의 최신 Equipment 실행이 섞이지 않습니다. 브라우저 새로고침은 실행을 새로 만들지 않습니다.

## 입력과 출력

주요 입력:

- `OrchestratorState`
- exact Profile/Skill/program ID
- run/experiment/specimen identity
- mode, worker, preconditions
- Vision/Guardian/operator evidence

주요 출력:

- `equipment_result`
- `equipment_profile`
- `equipment_report`
- `equipment_runtime_execution`
- `equipment_runtime_projection`
- `equipment_handoff`
- evidence/artifact references
- hardware alert와 incident record

## Tool 경계

| Tool | 역할 |
|---|---|
| `equipment.pyautogui.health` | 선택 worker 상태 확인 |
| `equipment.pyautogui.list_programs` | program catalog 확인 |
| `equipment.pyautogui.run` | bounded program 실행 |
| `equipment.pyautogui.request_log` | 실행 identity/audit 확인 |
| `vision.equipment_cross_check` | Profile이 요청한 관측 증거 |

`utm.run_protocol`은 호환용 명시 호출 경로로만 남을 수 있으며 자동 선택되지 않습니다.

## 실패와 복구

- Profile/program 불일치: 실행 전 차단
- worker 없음/불건전: 실행 전 차단
- Vision Link 없음: 실행 전 차단
- locator/checkpoint 실패: Skill에 선언된 bounded recovery만 허용
- invoke 이후 timeout: effect unknown으로 기록하고 상태/화면/파일 확인 전 재실행 금지
- 불완전 파일: 증거로 보존하지만 완료로 승격하지 않음

LLM 결과는 allowlisted 선택과 설명만 제공하며 임의 PyAutoGUI/shell 명령 권한을 만들 수 없습니다.

## 검증 범위

2026-08-27 기준 단위/통합 검증은 generic profile, UTM profile, Skill 실행, Vision Link, canonical runtime projection, Windows pairing/packaging 경로를 포함합니다. 자동 테스트는 물리 UTM을 작동하지 않습니다.
