# Lab Equipment Agent / Windows Bridge 통합 운영 지침

## 구조 원칙

Linux ATR이 판단과 실행 기록을 소유하고 Windows Bridge는 경량 PyAutoGUI worker로 동작합니다.

```text
LabEquipmentAgent (High-Level)
  -> EquipmentRuntimeService (Middle-Level)
  -> Windows/Local Bridge (Low-Level)
```

UTM은 `utm_windows_v1` Profile의 첫 적용 사례입니다. Agent 본체에 장비명, 프로그램명, 창 제목, 저장 경로를 고정하지 않습니다.

## 실행 원칙

1. 사용할 Profile과 정확한 program/Skill 버전을 확정합니다.
2. 하나의 `EquipmentExecutionRecord`를 생성합니다.
3. 선택한 provider의 `equipment.pyautogui.run`만 호출합니다.
4. worker의 원시 결과와 증거를 수집합니다.
5. Linux에서 completion policy를 한 번 적용합니다.
6. 완료된 증거 패키지를 보존하고, Manipulation의 시험 후 정리(post-test clear)와 새 Vision clearance 검증을 통과한 뒤 Analysis에 전달합니다.

`utm.run_protocol`은 tool 부재 시 자동 fallback으로 사용하지 않습니다. native/direct UTM은 별도 Profile로 명시 등록해야 합니다.

## 상태 투영

Agent, Workspace, Live GUI, CUI, Runtime IDE는 같은 실행 기록을 읽습니다.
상태 목록은 Profile/Skill/provider마다 다를 수 있으므로, 대표 상태 예시를
모든 실행에 강제하지 않습니다.

## Program과 Skill

- builtin: Bridge 포함 읽기 전용
- local draft: Windows 개발/테스트
- validated/deployed: Linux 검증 후 배포
- retired: 신규 실행 금지

Skill 원본은 Linux `memory/equipment_skills/`입니다. 정상 Skill block 실행은 결정론적입니다.
Managed Flow의 정상 경로에도 시작 전 제한된 범위의 LLM 선택과 종료 후 결과 검토가 포함되며,
block 사이마다 모델을 반복 호출하지 않습니다. 예외 복구도 별도의 제한된 권한과 증거를 따릅니다.

## 녹화 기반 Skill 생성

```text
Windows Record
  -> bounded event/frame package
  -> Linux transfer
  -> selected Local/API LLM annotation
  -> deterministic compile
  -> static/simulator/local validation
  -> approval
  -> version/hash deployment
  -> Windows cache
```

Windows에는 모델과 API key를 두지 않습니다.

## Vision Link

Vision Link는 Profile에서 선택적으로 활성화합니다. 최신성 조건과 대상 식별
정보를 충족하는 기존 증거를 사용하거나 Vision Agent tool을 호출합니다.
둘 다 없으면 실행 전에 차단합니다. Vision은 관측만 제공하며 worker에
직접 명령하지 않습니다.

## 완료 증거

Profile이 요구하는 증거 예:

- request/sequence/run/specimen identity
- target window/checkpoint screenshot
- locator state
- output file와 hash/row probe
- Vision cross-check
- worker raw status/step trace

HTTP 요청 성공만으로 완료 처리하지 않습니다. 불완전한 파일과 시간 초과
결과는 증거로 보존하지만 handoff는 허용하지 않습니다.

## Windows Console 범위

Windows 기본 화면은 Bridge Status, Program Manager, Recording, Latest Local Result만 제공합니다. UTM proof, Guardian, Analysis, Skill lifecycle, closed loop, ATR Controller 탐색은 Linux Workspace 기능입니다.

## 최초 연결

4자리 일회성 페어링 코드를 사용합니다. 성공 후 내부 키는 보호 파일에 자동 저장되고 사용자 UI에는 표시하지 않습니다. 장기 토큰을 입력하거나 복사하는 절차는 사용하지 않습니다.

## 안전 및 복구

- unknown Profile/program: no effect block
- worker unavailable: no automatic provider fallback
- locator/checkpoint failure: compiled recovery only
- invoke timeout: effect unknown, inspect before retry
- LLM: allowlisted selection/reasoning only
- physical equipment: Profile별 live 승인과 stop path 필요

## 검증 기준

- generic profile이 UTM/Vision hidden dependency 없이 실행
- UTM Profile이 required Vision evidence를 검증
- source/install Windows server parity
- 4자리 pairing TTL/attempt/lockout/persistence
- recording frame buffer bounded memory
- canonical runtime projection 일치
- browser refresh가 실행을 중복 생성하지 않음
- 자동 테스트는 물리 장비를 구동하지 않음
